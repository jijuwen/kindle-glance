from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from PIL import Image, ImageStat

from app.shan_shui import apply_render_mode, scene_period, scene_seed


TZ = ZoneInfo("Asia/Shanghai")


class ShanShuiTest(unittest.TestCase):
    def test_scene_period_boundaries(self) -> None:
        self.assertEqual(scene_period(datetime(2026, 9, 4, 5, 59, tzinfo=TZ)), ("2026-09-03", "night"))
        self.assertEqual(scene_period(datetime(2026, 9, 4, 6, 0, tzinfo=TZ)), ("2026-09-04", "morning"))
        self.assertEqual(scene_period(datetime(2026, 9, 4, 12, 0, tzinfo=TZ)), ("2026-09-04", "noon"))
        self.assertEqual(scene_period(datetime(2026, 9, 4, 18, 0, tzinfo=TZ)), ("2026-09-04", "evening"))
        self.assertEqual(scene_period(datetime(2026, 9, 4, 23, 0, tzinfo=TZ)), ("2026-09-04", "night"))

    def test_scene_seed_is_stable_and_variant_changes_it(self) -> None:
        now = datetime(2026, 9, 4, 20, 30, tzinfo=TZ)
        self.assertEqual(scene_seed(now, 0), scene_seed(now, 0))
        self.assertNotEqual(scene_seed(now, 0), scene_seed(now, 1))

    def test_kindle_gray_strengthens_ink_without_losing_dimensions(self) -> None:
        original = Image.linear_gradient("L").resize((160, 120))
        optimized = apply_render_mode(original, "kindle_gray")
        self.assertEqual(optimized.size, original.size)
        self.assertLess(ImageStat.Stat(optimized).mean[0], ImageStat.Stat(original).mean[0])
        self.assertEqual(apply_render_mode(original, "original_gray").tobytes(), original.tobytes())
