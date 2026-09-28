import math
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import main
from app.hourly_weather import (draw_hourly_weather, hourly_slots, slot_time,
                                smooth_separator_path, wind_direction)


class HourlyWeatherTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 5, 23, 35, tzinfo=ZoneInfo("Asia/Shanghai"))

    def test_slots_cross_midnight_without_compressing_gaps(self):
        weather = {"hourly": [
            {"time": "2026-09-06T00:00", "temperature": 27},
            {"time": "2026-09-06T02:00", "temperature": 25},
        ]}
        slots = hourly_slots(weather, self.now)
        self.assertEqual([item["stamp"].hour for item in slots], [0, 1, 2, 3, 4])
        self.assertEqual(slots[0]["temperature"], 27)
        self.assertNotIn("temperature", slots[1])
        self.assertEqual(slots[2]["temperature"], 25)
        self.assertEqual(slot_time(slots[0]["stamp"], self.now), "明日 00时")

    def test_wind_direction_boundaries(self):
        self.assertEqual(wind_direction(0), "北风")
        self.assertEqual(wind_direction(44), "东北风")
        self.assertEqual(wind_direction(225), "西南风")
        self.assertEqual(wind_direction(359), "北风")
        self.assertEqual(wind_direction(float("nan")), "风向--")

    def test_separator_is_dense_deterministic_and_continuous(self):
        first = smooth_separator_path()
        second = smooth_separator_path()
        self.assertEqual(first, second)
        self.assertGreater(len(first), 180)
        self.assertEqual(first[0][0], 64)
        self.assertEqual(first[-1], (1584, 520))
        self.assertTrue(all(a[0] < b[0] for a, b in zip(first, first[1:])))
        self.assertLess(max(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(first, first[1:])), 10)

    def test_complete_and_missing_data_render_native_grayscale(self):
        weather = {
            "temperature": -3, "apparent": -8, "label": "雷暴冰雹", "code": 96,
            "is_day": False, "observed_at": "2026-09-05T23:30", "rain_now": 85,
            "wind": 19, "wind_direction": 225, "gust": 34,
            "hourly": [{
                "time": f"2026-09-06T0{hour}:00", "temperature": -hour,
                "apparent": -hour - 4, "rain": 70 + hour, "wind": 15 + hour,
                "wind_direction": hour * 45, "code": 95, "is_day": 0,
            } for hour in range(5)],
        }
        for data in (weather, {}):
            image = draw_hourly_weather(data, self.now, main.font)
            self.assertEqual((image.mode, image.size), ("L", (1648, 1236)))


if __name__ == "__main__":
    unittest.main()
