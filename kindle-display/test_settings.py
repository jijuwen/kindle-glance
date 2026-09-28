"""First-run, migration, security and timezone regressions with isolated data."""
import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from app import main, settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.paths = []
        for key, name in (("DATA_DIR", ""), ("STATE_PATH", "current.json"), ("PAGES_STATE_PATH", "pages.json"),
                          ("PLAYLIST_PATH", "playlist.json"), ("EVENTS_PATH", "events.jsonl")):
            p = patch.object(main, key, self.directory / name)
            p.start()
            self.paths.append(p)
        main.LOGIN_ATTEMPTS.clear()
        main._JSON_CACHE.clear()
        main._PLAYLIST_CACHE.clear()
        settings.bootstrap(self.directory)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.paths):
            p.stop()
        self.env.stop()
        self.temp.cleanup()

    def claim(self):
        code = settings.read_json(self.directory / "setup-code.json")["code"]
        return self.client.post('/admin/api/setup/claim', json={"code": code, "password": "correct horse battery"})

    def csrf(self):
        return {"X-CSRF-Token": main.csrf_token(self.client.cookies.get(main.ADMIN_SESSION_COOKIE))}

    def region(self):
        return {"revision": main.board_settings()["revision"], "timezone": "America/Los_Angeles",
                "location": {"name": "Los Angeles", "latitude": 34.05, "longitude": -118.24, "id": "test"}}

    def test_empty_install_no_default_location_or_weather(self):
        self.assertIsNone(main.board_settings()["location"])
        self.assertEqual(self.client.get('/admin', follow_redirects=False).headers['location'], '/admin/settings')
        with patch.object(main, 'get_weather') as fetch:
            response = self.client.get('/api/display', headers={'access-token': main.required_env('DEVICE_TOKEN')})
        self.assertEqual(response.status_code, 503)
        fetch.assert_not_called()
        secrets = settings.credentials(self.directory)
        self.assertEqual(len(set(secrets.values())), 3)

    def test_claim_resume_csrf_and_finish_without_device(self):
        self.assertEqual(self.claim().status_code, 200)
        self.assertFalse((self.directory / 'setup-code.json').exists())
        stored = settings.credentials(self.directory)['ADMIN_PASSWORD_HASH']
        self.assertTrue(stored.startswith('scrypt$'))
        self.assertNotIn('correct horse', stored)
        self.assertEqual(self.client.post('/admin/api/settings', json=self.region()).status_code, 403)
        result = self.client.post('/admin/api/settings', json=self.region(), headers=self.csrf())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(settings.load(self.directory)['location']['name'], 'Los Angeles')
        response = self.client.post('/admin/api/setup/finish', json={'revision': result.json()['revision']}, headers=self.csrf())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(main.board_settings()['setup_state'], 'complete')
        self.assertNotIn('ai-accounts', [i['page_id'] for i in main.read_playlist_state()['items']])

    def test_claim_code_expiry_and_reuse(self):
        code = settings.read_json(self.directory / 'setup-code.json')
        code['expires_at'] = 1
        settings.atomic_json(self.directory / 'setup-code.json', code)
        self.assertEqual(self.claim().status_code, 400)
        settings.renew_setup_code(self.directory)
        self.assertEqual(self.claim().status_code, 200)
        self.assertEqual(self.client.post('/admin/api/setup/claim', json={'code':'bad','password':'another password'}).status_code, 409)

    def test_simultaneous_initialization_has_one_winner(self):
        code = settings.read_json(self.directory / 'setup-code.json')['code']
        def claim():
            with main.STATE_LOCK:
                try:
                    settings.establish_admin(self.directory, code, 'correct horse battery')
                    return 'ok'
                except settings.Conflict:
                    return 'conflict'
        with ThreadPoolExecutor(2) as executor:
            self.assertCountEqual(list(executor.map(lambda _: claim(), range(2))), ['ok', 'conflict'])

    def test_conflict_invalid_coordinates_and_corrupt_file(self):
        self.claim()
        candidate = self.region()
        self.assertEqual(self.client.post('/admin/api/settings', json=candidate, headers=self.csrf()).status_code, 200)
        self.assertEqual(self.client.post('/admin/api/settings', json=candidate, headers=self.csrf()).status_code, 409)
        candidate['revision'] += 1
        candidate['location']['latitude'] = 100
        self.assertEqual(self.client.post('/admin/api/settings', json=candidate, headers=self.csrf()).status_code, 400)
        path = self.directory / 'settings.json'
        path.write_text('{broken')
        with self.assertRaises(settings.SettingsError):
            settings.load(self.directory)
        self.assertEqual(path.read_text(), '{broken')

    def test_legacy_migration_is_idempotent_preserves_original(self):
        (self.directory / 'settings.json').unlink()
        original = {'version': 4, 'revision': 12, 'items': [{'id': 'original'}]}
        settings.atomic_json(self.directory / 'playlist.json', original)
        with patch.dict(os.environ, {'WEATHER_CITY':'Example City','TIMEZONE':'Asia/Shanghai'}):
            first = settings.load(self.directory)
        self.assertEqual(first, settings.load(self.directory))
        self.assertEqual(first['timezone'], 'Asia/Shanghai')
        self.assertEqual(settings.read_json(self.directory / 'playlist.json'), original)
        self.assertEqual(settings.read_json(self.directory / 'migration-v1-backup/playlist.json'), original)

    def test_dst_gaps_duplicates_and_fractional_zone(self):
        with self.assertRaises(settings.SettingsError):
            settings.local_timestamp('2026-03-08T02:30', 'America/Los_Angeles')
        with self.assertRaises(settings.SettingsError):
            settings.local_timestamp('2026-11-01T01:30', 'America/Los_Angeles')
        a = settings.local_timestamp('2026-11-01T01:30', 'America/Los_Angeles', 0)
        b = settings.local_timestamp('2026-11-01T01:30', 'America/Los_Angeles', 1)
        self.assertEqual(b-a, 3600)
        stamp = settings.local_timestamp('2026-09-28T12:00', 'Asia/Kolkata')
        self.assertEqual(datetime.fromtimestamp(stamp, ZoneInfo('UTC')).hour, 6)

    def test_password_invalidates_sessions_and_token_rotation(self):
        self.claim()
        old = main.required_env('DEVICE_TOKEN')
        response = self.client.post('/admin/api/device/rotate', json={}, headers=self.csrf())
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(old, main.required_env('DEVICE_TOKEN'))
        self.assertEqual(self.client.get('/api/display', headers={'access-token':old}).status_code, 401)
        response = self.client.post('/admin/api/password', headers=self.csrf(), json={'current':'correct horse battery','password':'another long password'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/admin/api/settings').status_code, 401)

    def test_collector_optional_and_exports_no_credentials(self):
        self.claim()
        with patch('app.codex_bridge.collector_request') as call:
            self.assertFalse(self.client.get('/admin/api/codex/accounts').json()['installed'])
            call.assert_not_called()
        exported = self.client.get('/admin/api/settings/export').text
        for secret in settings.credentials(self.directory).values():
            self.assertNotIn(secret, exported)

    def test_old_render_cannot_overwrite_new_settings(self):
        self.claim()
        self.client.post('/admin/api/settings', json=self.region(), headers=self.csrf())
        def draw(*args):
            with main.STATE_LOCK:
                old = main.board_settings()
                settings.save(self.directory, {'timezone':'Asia/Tokyo'}, old['revision'])
            return main.Image.new('L', (1648,1236), 255)
        with patch.object(main, 'draw_calendar', side_effect=draw):
            with self.assertRaises(main.HTTPException) as raised:
                main.render_page('simple-calendar')
        self.assertEqual(raised.exception.status_code, 409)
        self.assertNotIn('simple-calendar', main.read_pages_state().get('pages', {}))


if __name__ == '__main__':
    unittest.main()
