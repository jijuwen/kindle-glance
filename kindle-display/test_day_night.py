import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import main
from app.day_night import (MAP_LEFT, MAP_TOP, draw_day_night, glass_fields,
                           land_points, project, solar_dot, sun_position,
                           sun_times, unproject)


class DayNightTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 6, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai"))

    def test_solar_position_timezone_and_opposite_hemisphere(self):
        lat, lon = sun_position(self.now)
        self.assertEqual((lat, lon), sun_position(self.now.astimezone(timezone.utc)))
        self.assertAlmostEqual(solar_dot(lat, lon, lat, lon), 1)
        self.assertAlmostEqual(solar_dot(-lat, lon + 180, lat, lon), -1)
        self.assertLess(solar_dot(24.48, 118.09, lat, lon), 0)
        later_lon = sun_position(self.now + timedelta(hours=1))[1]
        self.assertAlmostEqual((lon - later_lon) % 360, 15, delta=.1)
        with self.assertRaises(ValueError):
            sun_position(datetime(2026, 1, 1))

    def test_seasons_and_polar_conditions(self):
        for month, expected in ((6, 23.44), (12, -23.44)):
            now = self.now.replace(month=month, day=21)
            self.assertAlmostEqual(sun_position(now)[0], expected, delta=.25)
            info = sun_times(now, 89, 0)
            self.assertEqual(info["polar"], "极昼" if month == 6 else "极夜")

    def test_sunrise_and_date_near_dateline(self):
        times = sun_times(self.now, 24.4798, 118.0894)
        self.assertEqual(times["rise"].date(), self.now.date())
        self.assertEqual(times["rise"].hour, 5)
        self.assertTrue(46 <= times["rise"].minute <= 55)
        self.assertEqual(times["set"].hour, 18)
        self.assertTrue(745 <= times["minutes"] <= 760)
        pacific = self.now.astimezone(ZoneInfo("Pacific/Kiritimati"))
        result = sun_times(pacific, 1.87, -157.4)
        self.assertEqual(result["rise"].date(), pacific.date())
        self.assertEqual(result["set"].date(), pacific.date())

    def test_map_projection_and_asset(self):
        for lon, lat in ((0, 0), (118.09, 24.48), (-170, 75), (150, -50)):
            actual_lon, actual_lat = unproject(*project(lon, lat))
            self.assertAlmostEqual(lon, actual_lon)
            self.assertAlmostEqual(lat, actual_lat)
        self.assertGreater(len(land_points()), 900)
        self.assertLess(len(land_points()), 1800)

    def test_equinox_rim_and_dateline_no_join(self):
        bg, rim = glass_fields(0, 0)
        row = bg.height // 2
        self.assertEqual(bg.getpixel((0, row)), bg.getpixel((bg.width - 1, row)))
        self.assertEqual(bg.getpixel((0, row)), 204)
        self.assertTrue(184 <= bg.getextrema()[0] <= 190)
        self.assertEqual(rim.getpixel((0, row)), 0)
        self.assertGreater(rim.getextrema()[1], 180)
        # Four decades of gray values in the edge, not a binary white outline.
        self.assertGreater(len(set(rim.tobytes())), 40)

    def test_native_render_deterministic_and_transport(self):
        first = draw_day_night(self.now, main.font)
        second = draw_day_night(self.now, main.font)
        self.assertEqual((first.mode, first.size), ("L", (1648, 1236)))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(first.rotate(90, expand=True).size, (1236, 1648))
        self.assertEqual(first.getpixel((0, 600)), 255)
        x, y = project(118.0894, 24.4798)
        x, y = round(x + MAP_LEFT), round(y + MAP_TOP)
        self.assertEqual(first.getpixel((x, y)), 0)
        self.assertGreater(first.getpixel((x + 7, y)), 240)
        self.assertLess(first.getpixel((x + 9, y)), 20)

    def test_long_city_and_polar_copy_render_without_overflow_error(self):
        polar = self.now.replace(month=12, day=21, hour=13)
        image = draw_day_night(polar, main.font, 69.6492, 18.9553,
                               "基里巴斯·圣诞岛")
        self.assertEqual(image.size, (1648, 1236))
        self.assertEqual(image.getpixel((1647, 1100)), 255)

    def test_paper_is_white_with_legible_night_dots_not_inversion(self):
        paper = draw_day_night(self.now, main.font)
        self.assertEqual((paper.mode, paper.size), ("L", (1648, 1236)))
        self.assertEqual(paper.getpixel((0, 600)), 255)
        bg, _ = glass_fields(0, 0)
        self.assertEqual(bg.getpixel((bg.width // 2, bg.height // 2)), 255)
        self.assertEqual(bg.getpixel((0, bg.height // 2)), 204)
        # An interior land point in central Asia stays dark under the night sheet.
        x, y, _, _ = next(p for p in land_points() if 75 < p[2] < 90 and 30 < p[3] < 40)
        self.assertTrue(25 <= paper.getpixel((x + 60, y + 120)) <= 40)
        sun_lat, sun_lon = sun_position(self.now)
        x, y, _, _ = next(p for p in land_points() if solar_dot(p[3], p[2], sun_lat, sun_lon) > .5 and 100 < p[1] < 600)
        self.assertEqual(paper.getpixel((x + 60, y + 120)), 0)

    def test_legacy_style_removed_other_settings_preserved(self):
        old = main.default_playlist_item("day-night")
        self.assertEqual(main.normalize_playlist_item(old, 0)["config"], {})
        for value in (None, "paper_glass", "dark_glass", "bad-value"):
            old["config"] = {"render_mode": value, "note": "keep"}
            self.assertEqual(main.normalize_playlist_item(old, 0)["config"], {"note": "keep"})

    def test_migration_preserves_settings_and_deleted_items(self):
        kept = main.default_playlist_item("hourly-weather")
        kept.update(enabled=False, rotation=270, duration_slots=3)
        old = {"version": 3, "revision": 8, "smart_skip": False, "items": [kept]}
        migrated = main.migrate_playlist(old)
        self.assertEqual(old["version"], 3)
        self.assertEqual(migrated["items"][0], kept)
        self.assertEqual(migrated["items"][-1]["page_id"], "day-night")
        self.assertFalse(migrated["smart_skip"])
        self.assertEqual(migrated["revision"], 9)
        self.assertEqual(main.migrate_playlist(migrated), migrated)
        removed = {**migrated, "items": [kept]}
        self.assertEqual(main.migrate_playlist(removed), removed)


if __name__ == "__main__":
    unittest.main()
