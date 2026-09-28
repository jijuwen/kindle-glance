"""Regression coverage for the personal dashboard's first delivery slice."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app import main


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        # Restore module functions, paths and environment after each test. A
        # leaked weather stub previously hid failures in later cache tests.
        attributes = ('DATA_DIR', 'STATE_PATH', 'EVENTS_PATH', 'PAGES_STATE_PATH', 'PLAYLIST_PATH', 'get_weather')
        module_patch = patch.multiple(main, **{name:getattr(main,name) for name in attributes})
        module_patch.start()
        self.addCleanup(module_patch.stop)
        environment_patch = patch.dict(os.environ)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        main.LOGIN_ATTEMPTS.clear()
        main._JSON_CACHE.clear()
        main._PLAYLIST_CACHE.clear()
        self.temporary = tempfile.TemporaryDirectory()
        data_dir = Path(self.temporary.name)
        main.DATA_DIR = data_dir
        main.STATE_PATH = data_dir / "current.json"
        main.EVENTS_PATH = data_dir / "events.jsonl"
        main.PAGES_STATE_PATH = data_dir / "pages.json"
        main.PLAYLIST_PATH = data_dir / "playlist.json"
        os.environ.update(
            {
                "DEVICE_TOKEN": "test-device-token",
                "IMAGE_SIGNING_KEY": "test-image-signing-key",
                "EXTERNAL_BASE_URL": "https://kindle.example.test",
                "ADMIN_PASSWORD": "admin123!",
                "TIMEZONE": "UTC",
            }
        )
        main.get_weather = lambda _settings: {
            "temperature": 25,
            "apparent": 26,
            "label": "晴朗",
            "high": 28,
            "low": 23,
            "rain": 0,
            "forecast": [
                {"date": "2026-09-03", "label": "晴朗", "high": 28, "low": 23, "rain": 0},
                {"date": "2026-09-04", "label": "多云", "high": 29, "low": 24, "rain": 10},
                {"date": "2026-09-05", "label": "小雨", "high": 27, "low": 23, "rain": 40},
            ],
        }
        image = main.Image.new("L", (1236, 1648), 255)
        image.save(data_dir / "screen-initial.png", "PNG")
        main.write_state(
            {
                "filename": "screen-initial.png",
                "width": 1236,
                "height": 1648,
                "rendered_at": 1_700_000_000,
                "weather_status": {"ok": True, "checked_at": 1_700_000_000},
            }
        )
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def test_login_preview_render_and_device_fetch(self) -> None:
        self.assertEqual(self.client.get("/admin", follow_redirects=False).status_code, 303)
        login = self.client.post("/admin/login", json={"password": "admin123!"})
        self.assertEqual(login.status_code, 200)

        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('data-view="dashboard"', dashboard.text)
        self.assertIn("/admin/static/admin.js", dashboard.text)
        playlist_page = self.client.get("/admin/playlist")
        self.assertEqual(playlist_page.status_code, 200)
        self.assertIn('data-view="playlist"', playlist_page.text)
        self.assertEqual(self.client.get("/admin/preview").headers["content-type"], "image/png")

        self.assertEqual(self.client.post("/admin/api/actions/render").status_code, 403)
        session = self.client.cookies.get(main.ADMIN_SESSION_COOKIE)
        rendered = self.client.post(
            "/admin/api/actions/render",
            headers={"X-CSRF-Token": main.csrf_token(session)},
        )
        self.assertEqual(rendered.status_code, 200)

        display = self.client.get(
            "/api/display",
            headers={"access-token": "test-device-token", "png-width": "1236", "png-height": "1648"},
        )
        self.assertEqual(display.status_code, 200)
        self.assertIn("image_url", display.json())
        self.assertIn(display.json()["page_id"], main.PAGE_DEFINITIONS)
        self.assertTrue(display.json()["filename"].startswith("screen-"))
        self.assertIn(display.json()["rotation"], (0, 90, 270))
        image_path = urlsplit(display.json()["image_url"])
        downloaded = self.client.get(f"{image_path.path}?{image_path.query}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("last_device_request", main.read_state())

    def test_phase_two_pages_have_independent_artifacts(self) -> None:
        for page_id, definition in main.PAGE_DEFINITIONS.items():
            rendered = main.render_page(page_id)
            self.assertTrue((main.DATA_DIR / rendered["filename"]).is_file())
            self.assertEqual((rendered["width"], rendered["height"]), definition["size"])
        self.assertIn("daily-overview", main.read_pages_state()["pages"])

    def test_playlist_selection_is_stable_within_a_refresh_slot(self) -> None:
        playlist = main.playlist_for_profile("landscape")
        self.assertEqual(playlist["mode"], "cycle")
        start = datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc)
        first = main.select_playlist_page("portrait", start)
        retry = main.select_playlist_page("portrait", start.replace(minute=45))
        next_slot = main.select_playlist_page("portrait", start.replace(hour=2, minute=5))
        self.assertEqual(first["slot"], retry["slot"])
        self.assertEqual(first["page_id"], retry["page_id"])
        self.assertNotEqual(first["slot"], next_slot["slot"])

    def test_playlist_admin_actions_persist(self) -> None:
        self.client.post("/admin/login", json={"password": "admin123!"})
        session = self.client.cookies.get(main.ADMIN_SESSION_COOKIE)
        added = self.client.post(
            "/admin/api/playlist/items",
            json={"page_id": "daily-overview"},
            headers={"X-CSRF-Token": main.csrf_token(session)},
        )
        self.assertEqual(added.status_code, 200)
        item_id = added.json()["item"]["id"]
        updated = self.client.post(
            f"/admin/api/playlist/items/{item_id}",
            json={
                "name": "晚间概览",
                "duration_slots": 3,
                "rotation": 270,
                "schedule": {"days": [1, 3, 5], "start": "18:00", "end": "23:00"},
            },
            headers={"X-CSRF-Token": main.csrf_token(session)},
        )
        self.assertEqual(updated.status_code, 200)
        stored = main.playlist_item(item_id)
        self.assertEqual(stored["name"], "晚间概览")
        self.assertEqual(stored["duration_slots"], 3)
        self.assertEqual(stored["rotation"], 270)

        order = [item["id"] for item in main.read_playlist_state()["items"]]
        reordered = self.client.post(
            "/admin/api/playlist/reorder",
            json={"item_ids": list(reversed(order))},
            headers={"X-CSRF-Token": main.csrf_token(session)},
        )
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual(main.read_playlist_state()["items"][0]["id"], item_id)

    def test_unified_playlist_migrates_legacy_profiles(self) -> None:
        main.write_playlist_state({
            "playlists": {
                "portrait": {"page_ids": ["countdown", "weather"], "enabled": {"countdown": True, "weather": False}},
                "landscape": {"page_ids": ["daily-overview"], "enabled": {"daily-overview": True}},
            }
        })
        migrated = main.read_playlist_state()
        self.assertEqual(migrated["version"], main.PLAYLIST_VERSION)
        self.assertEqual([item["page_id"] for item in migrated["items"]],
                         ["daily-overview", "simple-calendar", "weather-glance", "hourly-weather",
                          "day-night", "year-progress", "time-scales", "shan-shui", "ai-accounts"])
        overview = next(item for item in migrated["items"] if item["page_id"] == "daily-overview")
        self.assertEqual(overview["rotation"], 90)

    def test_retired_pages_are_removed_and_rejected(self) -> None:
        kept = main.default_playlist_item("shan-shui", 4)
        kept.update(name="保留山水", rotation=270, duration_slots=3)
        kept["config"]["render_mode"] = "kindle_gray"
        main.write_playlist_state({"version": 2, "revision": 9, "smart_skip": False,
            "items": [{"id": "old-" + p, "page_id": p} for p in ("weather", "countdown", "reading-note")] + [kept]})
        migrated = main.read_playlist_state()
        self.assertEqual(migrated["items"][0], kept)
        self.assertEqual([item["page_id"] for item in migrated["items"]], ["shan-shui", "hourly-weather", "day-night"])
        self.assertEqual(migrated["version"], main.PLAYLIST_VERSION)
        self.assertEqual(migrated["revision"], 10)
        self.assertFalse(migrated["smart_skip"])
        self.assertEqual(main.read_playlist_state(), migrated)

        # Once upgraded, an intentional removal remains removed.
        main.write_playlist_state({**migrated, "items": [kept]})
        self.assertEqual(main.read_playlist_state()["items"], [kept])
        self.client.post("/admin/login", json={"password": "admin123!"})
        session = self.client.cookies.get(main.ADMIN_SESSION_COOKIE)
        for page_id in ("weather", "countdown", "reading-note"):
            with self.assertRaises(ValueError):
                main.render_page(page_id)
            response = self.client.post("/admin/api/playlist/items", json={"page_id": page_id},
                headers={"X-CSRF-Token": main.csrf_token(session)})
            self.assertEqual(response.status_code, 404)

    def test_landscape_item_is_composited_to_portrait_transport(self) -> None:
        native = main.render_page("daily-overview")
        item = main.default_playlist_item("daily-overview")
        rendered = main.compose_playlist_item(item)
        self.assertEqual((rendered["width"], rendered["height"]), main.TRANSPORT_SIZE)
        with main.Image.open(main.DATA_DIR / rendered["filename"]) as image:
            self.assertEqual(image.size, main.TRANSPORT_SIZE)
        self.assertEqual((native["width"], native["height"]), (1648, 1236))

    def test_unchanged_transport_image_is_reused_without_re_encoding(self) -> None:
        """A device fetch that changes nothing must not redo the rotate/pad/encode."""
        main.render_page("year-progress")
        item = main.default_playlist_item("year-progress")
        first = main.compose_playlist_item(item)

        saves: list[str] = []
        original_save = main.Image.Image.save

        def counting_save(image, target, *args, **kwargs):
            saves.append(str(target))
            return original_save(image, target, *args, **kwargs)

        main.Image.Image.save = counting_save
        try:
            second = main.compose_playlist_item(item)
        finally:
            main.Image.Image.save = original_save

        self.assertEqual(second["filename"], first["filename"])
        self.assertEqual(saves, [])

    def test_display_version_is_stable_when_only_signature_expiry_changes(self) -> None:
        """The plugin may compare filename without comparing the expiring URL."""
        main.render_page("year-progress")
        item = main.default_playlist_item("year-progress")
        selection = {"item": item, "page_id": "year-progress", "slot": 0}
        current = int(time.time())
        headers = {"access-token": "test-device-token"}
        with patch.object(main, "select_playlist_item", return_value=selection):
            with patch.object(main.time, "time", return_value=current):
                first = self.client.get("/api/display", headers=headers).json()
            with patch.object(main.time, "time", return_value=current + 30):
                second = self.client.get("/api/display", headers=headers).json()
                self.assertEqual(first["filename"], second["filename"])
                self.assertNotEqual(first["image_url"], second["image_url"])
                images = []
                for metadata in (first, second):
                    address = urlsplit(metadata["image_url"])
                    response = self.client.get(f"{address.path}?{address.query}")
                    self.assertEqual(response.status_code, 200)
                    images.append(response.content)
                self.assertEqual(*images)

    def test_transport_version_changes_with_native_pixels(self) -> None:
        """A newly rendered native PNG must invalidate the device's filename cache."""
        native = main.render_page("year-progress")
        item = main.default_playlist_item("year-progress")
        before = main.compose_playlist_item(item)
        with main.Image.open(main.DATA_DIR / native["filename"]) as opened:
            changed = opened.copy()
        changed.putpixel((0, 0), 0 if changed.getpixel((0, 0)) else 255)
        import hashlib
        import io
        encoded = io.BytesIO()
        changed.save(encoded, "PNG")
        changed.close()
        data = encoded.getvalue()
        name = f"page-year-progress-changed-{hashlib.sha256(data).hexdigest()[:16]}.png"
        (main.DATA_DIR / name).write_bytes(data)
        pages = main.read_pages_state()
        pages["pages"]["year-progress"]["filename"] = name
        main.write_pages_state(pages)
        after = main.compose_playlist_item(item)
        self.assertNotEqual(before["filename"], after["filename"])

    def test_concurrent_stale_fetches_render_the_page_only_once(self) -> None:
        """Eight simultaneous callers must not launch eight renders."""
        main.write_pages_state({"pages": {}})
        attempts: list[str] = []
        original = main._render_page_locked

        def slow_render(page_id: str):
            attempts.append(page_id)
            time.sleep(0.2)
            return original(page_id)

        main._render_page_locked = slow_render
        failures: list[Exception] = []

        def worker() -> None:
            try:
                main.render_page_if_stale("time-scales")
            except Exception as error:  # pragma: no cover - surfaced by the assert
                failures.append(error)

        try:
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            main._render_page_locked = original

        self.assertEqual(failures, [])
        self.assertEqual(attempts, ["time-scales"])

    def test_concurrent_first_transport_fetch_encodes_once(self) -> None:
        main.render_page("year-progress")
        item = main.default_playlist_item("year-progress")
        start = threading.Barrier(8)
        saves = []
        original = main.Image.Image.save

        def slow_save(image, target, *args, **kwargs):
            saves.append(str(target))
            time.sleep(0.1)
            return original(image, target, *args, **kwargs)

        def fetch(_):
            start.wait(timeout=5)
            return main.compose_playlist_item(item)

        with patch.object(main.Image.Image, "save", slow_save), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(fetch, range(8)))
        self.assertEqual(len(saves), 1)
        self.assertEqual(len({result["filename"] for result in results}), 1)
        with main.Image.open(main.DATA_DIR / results[0]["filename"]) as image:
            image.load()
            self.assertEqual(image.size, main.TRANSPORT_SIZE)
        self.assertEqual(list(main.DATA_DIR.glob("screen-working-*.png")), [])

    def test_concurrent_rotations_of_same_item_keep_correct_pixels(self) -> None:
        main.render_page("year-progress")
        item = main.default_playlist_item("year-progress")
        variants = [{**item, "rotation": rotation} for rotation in (90, 270)]
        expected = []
        for variant in variants:
            result = main.compose_playlist_item(variant)
            path = main.DATA_DIR / result["filename"]
            with main.Image.open(path) as image:
                expected.append(image.tobytes())
            path.unlink()
        start = threading.Barrier(2)

        def fetch(variant):
            start.wait(timeout=5)
            return main.compose_playlist_item(variant)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(fetch, variants))
        self.assertNotEqual(results[0]["filename"], results[1]["filename"])
        for result, pixels in zip(results, expected):
            with main.Image.open(main.DATA_DIR / result["filename"]) as image:
                self.assertEqual(image.tobytes(), pixels)

    def test_image_cleanup_preserves_in_progress_files(self) -> None:
        working = [main.DATA_DIR / name for name in ("page-working-year-progress.png", "screen-working-test.png")]
        obsolete = [main.DATA_DIR / name for name in ("page-obsolete.png", "screen-obsolete.png")]
        for path in working + obsolete:
            path.write_bytes(b"in progress")
        with patch.object(main, "MAX_PAGE_IMAGES", 0), patch.object(main, "MAX_IMAGES", 0):
            with main.STATE_LOCK:
                main.cleanup_page_images()
            main.cleanup_images("screen-initial.png")
        self.assertTrue(all(path.exists() for path in working))
        self.assertTrue(all(not path.exists() for path in obsolete))

    def test_concurrent_renders_of_different_pages_all_persist(self) -> None:
        """pages.json is read-modify-write; parallel renders must not drop entries."""
        main.write_pages_state({"pages": {}})
        page_ids = ["time-scales", "year-progress", "simple-calendar", "weather-glance"]
        failures: list[Exception] = []

        def worker(page_id: str) -> None:
            try:
                main.render_page(page_id)
            except Exception as error:  # pragma: no cover - surfaced by the assert
                failures.append(error)

        threads = [threading.Thread(target=worker, args=(page_id,)) for page_id in page_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(sorted(main.read_pages_state()["pages"]), sorted(page_ids))

    def test_bootstrap_preserves_existing_secrets_when_environment_removed(self):
        main.verify_configuration()
        originals = {name: main.required_env(name) for name in ("DEVICE_TOKEN", "IMAGE_SIGNING_KEY")}
        with patch.dict(os.environ, {name: "" for name in originals}):
            main.verify_configuration()
            self.assertEqual({name: main.required_env(name) for name in originals}, originals)
        with patch.dict(os.environ, {"DEVICE_TOKEN": "replace-with-placeholder"}):
            with self.assertRaises(ValueError):
                main.verify_configuration()


    def test_day_night_single_style_preview_cache_and_duplicate(self):
        from io import BytesIO
        item = main.default_playlist_item("day-night")
        item["config"] = {"render_mode": "dark_glass", "note": "keep"}
        main.write_playlist_state({"version": main.PLAYLIST_VERSION, "revision": 1, "smart_skip": True, "items": [item]})
        page = main.render_page("day-night")
        self.assertEqual(page["render_revision"], main.DAY_NIGHT_REVISION)
        self.assertNotIn("render_variants", page)
        self.assertEqual(main.read_playlist_state()["items"][0]["config"], {"note": "keep"})
        dark = main.compose_playlist_item(item)
        self.client.post("/admin/login", json={"password": "admin123!"})
        headers = {"X-CSRF-Token": main.csrf_token(self.client.cookies.get(main.ADMIN_SESSION_COOKIE))}
        path = "/admin/api/playlist/items/" + item["id"]
        changed = self.client.post(path, json={"config": {"render_mode": "paper_glass", "note": "keep"}}, headers=headers)
        self.assertEqual(changed.status_code, 200)
        paper_item = main.read_playlist_state()["items"][0]
        with patch.object(main, "draw_day_night", side_effect=AssertionError("legacy style must use single cache")):
            light = main.compose_playlist_item(paper_item)
            native = self.client.get(main.admin_item_view(paper_item)["preview_url"])
            self.assertEqual(native.status_code, 200)
            self.assertEqual(main.Image.open(BytesIO(native.content)).getpixel((0, 600)), 255)
            self.assertEqual(light["filename"], dark["filename"])
            legacy = self.client.get("/admin/pages/day-night/preview?render_mode=dark_glass")
            self.assertEqual(legacy.content, native.content)
            with patch.object(main.Image.Image, "save", side_effect=AssertionError("repeat encode")):
                self.assertEqual(main.compose_playlist_item(paper_item)["filename"], light["filename"])
                self.assertEqual(main.compose_playlist_item(item)["filename"], dark["filename"])
        duplicate = self.client.post(path + "/duplicate", headers=headers)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(main.read_playlist_state()["items"][1]["config"], {"note": "keep"})
        self.assertEqual(main.read_playlist_state()["items"][0]["rotation"], item["rotation"])
        # The sole native image remains pinned past the retention cutoff.
        with patch.object(main, "MAX_PAGE_IMAGES", 0):
            main.cleanup_page_images()
        self.assertTrue((main.DATA_DIR / page["filename"]).is_file())

    def test_day_night_legacy_cache_requests_new_revision(self):
        page = main.render_page("day-night")
        self.assertFalse(main.page_needs_render("day-night", page))
        del page["render_revision"]
        self.assertTrue(main.page_needs_render("day-night", page))


if __name__ == "__main__":
    unittest.main()
