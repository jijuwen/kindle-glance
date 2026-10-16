"""Daily settings, first-run routing and background preview regressions."""
import unittest
from unittest.mock import patch

import test_settings
from app import main, settings


class PreviewTest(unittest.TestCase):
    setUp = test_settings.SettingsTest.setUp
    tearDown = test_settings.SettingsTest.tearDown
    claim = test_settings.SettingsTest.claim
    csrf = test_settings.SettingsTest.csrf
    region = test_settings.SettingsTest.region

    def configure(self, pages=('simple-calendar', 'weather-glance', 'annual-garden'), finish=False):
        self.claim()
        response = self.client.post('/admin/api/settings', json={**self.region(), 'selected_pages': list(pages)}, headers=self.csrf())
        self.assertEqual(response.status_code, 200, response.text)
        if finish:
            response = self.client.post('/admin/api/setup/finish', json={'revision': main.board_settings()['revision']}, headers=self.csrf())
            self.assertEqual(response.status_code, 200, response.text)

    def fake_render(self, page_id):
        main.Image.new('L', (12, 16), 255).save(self.directory / (page_id + '.png'))
        state = main.read_pages_state()
        state.setdefault('pages', {})[page_id] = {'filename': page_id + '.png', 'config_revision': main.board_settings()['revision'], 'rendered_at': main.time.time()}
        revisions = {'day-night': main.DAY_NIGHT_REVISION,
                     'annual-garden': main.ANNUAL_GARDEN_REVISION}
        if page_id in revisions:
            state['pages'][page_id]['render_revision'] = revisions[page_id]
        main.write_pages_state(state)
        return state['pages'][page_id]

    def test_routes_separate_first_run_and_daily_settings(self):
        for path in ('/admin', '/admin/settings', '/admin/playlist'):
            self.assertEqual(self.client.get(path, follow_redirects=False).headers['location'], '/admin/setup')
        self.assertIn('id="steps"', self.client.get('/admin/setup').text)
        self.configure(finish=True)
        playlist = main.read_playlist_state()
        for path, view in (('/admin', 'dashboard'), ('/admin/settings', 'settings'), ('/admin/playlist', 'playlist')):
            page = self.client.get(path)
            self.assertIn(f'data-view="{view}"', page.text)
            self.assertIn('class="dock"', page.text)
            self.assertNotIn('id="steps"', page.text)
        self.assertEqual(self.client.get('/admin/setup', follow_redirects=False).headers['location'], '/admin')
        self.assertEqual(main.read_playlist_state(), playlist)
        data = self.client.get('/admin/api/view/dashboard').json()
        self.assertIn('画面正在准备', data['greeting'])
        self.assertEqual(data['current']['preview_url'], '')

    def test_all_selected_previews_generate_before_finish_and_survive_finish(self):
        self.configure()
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        self.assertEqual(render.call_count, 3)
        self.assertEqual(main.preview_progress()['ready'], 3)
        response = self.client.post('/admin/api/setup/finish', json={'revision': main.board_settings()['revision']}, headers=self.csrf())
        self.assertEqual(response.status_code, 200)
        with patch.object(main, 'render_page_if_stale') as render:
            main.render_preview_pass()
        render.assert_not_called()
        self.assertEqual(main.preview_progress()['ready'], 3)
        self.assertIn('等待 Kindle 连接', main.admin_bootstrap('dashboard')['greeting'])

    def test_failure_does_not_stop_other_pages_and_retry_is_explicit(self):
        self.configure()
        def fail_one(page_id):
            if page_id == 'weather-glance':
                raise RuntimeError('synthetic renderer failure')
            return self.fake_render(page_id)
        with patch.object(main, 'render_page_if_stale', side_effect=fail_one):
            main.render_preview_pass()
        progress = main.preview_progress()
        self.assertEqual((progress['ready'], progress['failed']), (2, 1))
        self.assertNotIn('synthetic', str(progress))
        with patch.object(main, 'render_page_if_stale') as render:
            main.render_preview_pass()
        render.assert_not_called()
        self.assertEqual(self.client.post('/admin/api/previews/retry').status_code, 403)
        self.assertEqual(self.client.post('/admin/api/previews/retry', headers=self.csrf()).status_code, 200)
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        render.assert_called_once_with('weather-glance')
        self.assertEqual(main.preview_progress()['ready'], 3)

    def test_existing_playlist_gets_missing_previews_without_changing_schedule(self):
        self.configure(finish=True)
        playlist = main.read_playlist_state()
        playlist['items'][0]['enabled'] = False
        playlist['items'].append({**playlist['items'][1], 'id': 'same-page-second-item'})
        main.save_unified_playlist(playlist)
        before = main.read_playlist_state()
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        self.assertEqual(render.call_count, 3)
        self.assertEqual(main.read_playlist_state(), before)
        self.assertEqual(main.preview_progress()['ready'], 3)
        self.client.post('/admin/api/playlist/items', headers=self.csrf(), json={'page_id': 'day-night'})
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        render.assert_called_once_with('day-night')

    def test_nonvisual_save_reuses_images_and_region_invalidates_weather_only(self):
        self.configure()
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render):
            main.render_preview_pass()
        response = self.client.post('/admin/api/settings', headers=self.csrf(), json={'revision': main.board_settings()['revision'], 'external_base_url': 'https://board.example.test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.preview_progress()['ready'], 3)
        region = main.board_settings()['location']
        response = self.client.post('/admin/api/settings', headers=self.csrf(), json={'revision': main.board_settings()['revision'], 'location': {**region, 'name': 'New city', 'latitude': 1}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.preview_progress()['ready'], 2)
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        render.assert_called_once_with('weather-glance')

    def test_garden_rerenders_only_when_the_hemisphere_changes(self):
        self.configure(pages=('annual-garden', 'weather-glance'))
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render):
            main.render_preview_pass()
        region = main.board_settings()['location']
        for latitude, expected in ((1, {'weather-glance'}), (-33.87, {'weather-glance', 'annual-garden'})):
            response = self.client.post('/admin/api/settings', headers=self.csrf(), json={'revision': main.board_settings()['revision'], 'location': {**region, 'latitude': latitude}})
            self.assertEqual(response.status_code, 200)
            with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
                main.render_preview_pass()
            self.assertEqual({call.args[0] for call in render.call_args_list}, expected)

    def test_changed_configuration_and_restart_do_not_leave_jobs_stuck(self):
        self.configure()
        revision = main.board_settings()['revision']
        main.set_preview_job('simple-calendar', revision, 'running')
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render):
            main.render_preview_pass()
        self.assertEqual(main.preview_progress()['ready'], 3)
        main.save_board_settings({'timezone': 'Asia/Tokyo'}, revision)
        main.set_preview_job('simple-calendar', revision, 'error', 'stale failure')
        self.assertEqual(main.preview_progress()['failed'], 0)
        self.assertEqual(main.preview_progress()['ready'], 0)
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render):
            main.render_preview_pass()
        self.assertEqual(main.preview_progress()['ready'], 3)

    def test_missing_image_is_queued_again_even_after_success(self):
        self.configure()
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render):
            main.render_preview_pass()
        (self.directory / 'annual-garden.png').unlink()
        progress = main.preview_progress()
        self.assertEqual(progress['ready'], 2)
        self.assertTrue(progress['active'])
        self.assertEqual(next(p for p in progress['pages'] if p['page_id'] == 'annual-garden')['status'], 'queued')
        with patch.object(main, 'render_page_if_stale', side_effect=self.fake_render) as render:
            main.render_preview_pass()
        render.assert_called_once_with('annual-garden')
        self.assertEqual(main.preview_progress()['ready'], 3)

    def test_retired_boards_left_in_saved_settings_are_ignored(self):
        self.configure()
        saved = settings.load(self.directory)
        saved['selected_pages'] = ['year-progress', 'simple-calendar', 'time-scales']
        settings.atomic_json(self.directory / 'settings.json', saved)
        self.assertEqual(main.preview_targets(), ['simple-calendar'])
        saved['selected_pages'] = ['year-progress']
        settings.atomic_json(self.directory / 'settings.json', saved)
        self.assertEqual(main.preview_targets(), settings.defaults()['selected_pages'])
        response = self.client.post('/admin/api/setup/finish', json={'revision': main.board_settings()['revision']}, headers=self.csrf())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item['page_id'] for item in main.read_playlist_state()['items']], settings.defaults()['selected_pages'])

    def test_new_progress_and_view_endpoints_require_admin(self):
        self.claim()
        self.client.cookies.clear()
        for path in ('/admin/api/previews', '/admin/api/view/settings'):
            self.assertEqual(self.client.get(path).status_code, 401)


if __name__ == '__main__':
    unittest.main()
