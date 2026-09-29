"""Device code lifecycle regressions; unrelated credentials must remain intact."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settings
import test_settings


class DeviceCodeTest(unittest.TestCase):
    def test_bootstrap_preserves_codes_and_strong_internal_keys(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            directory = Path(temporary)
            settings.bootstrap(directory)
            original = settings.credentials(directory)
            self.assertRegex(original['DEVICE_TOKEN'], r'^[A-HJ-NP-Z2-9]{6}$')
            for key in ('IMAGE_SIGNING_KEY', 'ADMIN_SESSION_KEY'):
                self.assertGreaterEqual(len(original[key]), 40)
            settings.bootstrap(directory)
            self.assertEqual(settings.credentials(directory), original)
            original['DEVICE_TOKEN'] = 'existing-long-token-must-remain-valid'
            settings.atomic_json(directory / 'credentials.json', original)
            settings.bootstrap(directory)
            self.assertEqual(settings.credentials(directory), original)

    def test_rotation_never_reissues_previous_code(self):
        with patch.object(settings.secrets, 'choice', side_effect=list('AAAAAABBBBBB')):
            self.assertEqual(settings.generate_device_token('AAAAAA'), 'BBBBBB')

    def test_authenticated_rotation_invalidates_old_code(self):
        fixture = test_settings.SettingsTest()
        fixture.setUp()
        try:
            self.assertEqual(fixture.claim().status_code, 200)
            self.assertEqual(fixture.client.post('/admin/api/device/rotate', json={}).status_code, 403)
            before = settings.credentials(fixture.directory)
            response = fixture.client.post('/admin/api/device/rotate', json={}, headers=fixture.csrf())
            self.assertEqual(response.status_code, 200)
            token = response.json()['token']
            self.assertRegex(token, r'^[A-HJ-NP-Z2-9]{6}$')
            after = settings.credentials(fixture.directory)
            old_token = before.pop('DEVICE_TOKEN')
            self.assertNotEqual(old_token, after.pop('DEVICE_TOKEN'))
            self.assertEqual(before, after)
            self.assertEqual(fixture.client.get('/api/display', headers={'access-token': old_token}).status_code, 401)
            self.assertEqual(fixture.client.get('/api/display', headers={'access-token': token}).status_code, 503)
        finally:
            fixture.tearDown()
