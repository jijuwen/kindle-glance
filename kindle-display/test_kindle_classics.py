import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app import main
from app.kindle_classics import (draw_calendar, draw_time_scales, draw_weather_glance,
    draw_year_progress, month_grid, period_progress, seven_days, temperature_extent, year_progress,
    YEAR_PROGRESS_REVISION)

cached_weather = main.get_weather


class ClassicsTest(unittest.TestCase):
    def test_month_boundaries_and_six_rows(self):
        for stamp, count, rows in [(datetime(2024,2,29),29,5),(datetime(2026,8,31),31,6),(datetime(2026,2,1),28,4)]:
            grid=month_grid(stamp)
            self.assertEqual(len(grid),rows)
            self.assertEqual([d for week in grid for d in week if d],list(range(1,count+1)))
            first=next(i for i,d in enumerate(grid[0]) if d)
            self.assertEqual(first,(stamp.replace(day=1).weekday()+1)%7)
            im=draw_calendar(stamp,main.font)
            self.assertEqual(im.size,(1648,1236))

    def test_forecast_gaps_keep_correct_dates(self):
        now=datetime(2026,12,31)
        days=seven_days({'forecast':[{'date':'2027-01-02','high':-3,'low':-12}]},now)
        self.assertEqual(days[0][0].isoformat(),'2026-12-31')
        self.assertEqual(days[1][1],{})
        self.assertEqual(days[2][1]['high'],-3)
        self.assertEqual(days[-1][0].isoformat(),'2027-01-06')

    def test_degenerate_and_missing_weather_renders(self):
        now=datetime(2026,9,5)
        for data in [{},{'temperature':-15,'forecast':[{'date':'2026-09-05','high':-15,'low':-15,'code':71}]},
                     {'temperature':float('nan'),'forecast':[{'date':'2026-09-05','high':-2,'low':4}]}]:
            lo,hi=temperature_extent(seven_days(data,now),data.get('temperature'))
            self.assertLess(lo,hi)
            image=draw_weather_glance(data,now,main.font)
            self.assertEqual((image.mode,image.size),('L',(1648,1236)))

    def test_calendar_changes_at_local_midnight_and_missing_cache(self):
        with tempfile.TemporaryDirectory() as root, patch.object(main,'DATA_DIR',Path(root)):
            file=Path(root)/'calendar.png'
            file.touch()
            now=datetime(2026,9,5,0,1,tzinfo=timezone(timedelta(hours=8)))
            previous=now-timedelta(minutes=2)
            page={'filename':file.name,'rendered_at':previous.timestamp(),
                  'config_revision':main.board_settings()['revision'], 'render_revision':YEAR_PROGRESS_REVISION}
            self.assertTrue(main.page_needs_render('simple-calendar',page,now))
            self.assertTrue(main.page_needs_render('year-progress',page,now))
            page['rendered_at']=now.timestamp()
            self.assertFalse(main.page_needs_render('simple-calendar',page,now))
            self.assertFalse(main.page_needs_render('year-progress',page,now))
            file.unlink()
            self.assertTrue(main.page_needs_render('simple-calendar',page,now))

    def test_year_progress_handles_common_and_leap_years(self):
        cases=[(datetime(2026,1,1),1,365),(datetime(2026,12,31,23,59),365,365),
               (datetime(2024,2,29,12),60,366)]
        for now,ordinal,total in cases:
            actual_ordinal,actual_total,fraction=year_progress(now)
            self.assertEqual((actual_ordinal,actual_total),(ordinal,total))
            self.assertGreaterEqual(fraction,0)
            self.assertLessEqual(fraction,1)
            self.assertEqual(draw_year_progress(now,main.font).size,(1648,1236))

    def test_year_primary_information_and_today_are_pure_black(self):
        image=draw_year_progress(datetime(2026,9,5,13,30),main.font)
        self.assertEqual(image.getpixel((238,350)),0)  # Past date.
        self.assertEqual(image.getpixel((406,910)),0)  # Today.
        self.assertEqual(image.getpixel((406,890)),0)  # Today's outer ring.
        self.assertEqual(image.getpixel((406,893)),255)  # White gap inside ring.
        self.assertEqual(image.getpixel((364,890)),255)  # Past date has no ring.
        self.assertEqual(image.getpixel((1498,1126)),192)  # Future date.
        self.assertEqual(image.crop((78,76,600,206)).getextrema()[0],0)  # Year.
        self.assertEqual(image.crop((900,76,1568,206)).getextrema()[0],0)  # Percent.
        self.assertEqual(image.crop((900,220,1568,266)).getextrema()[0],0)  # Day numbers.
        self.assertEqual(image.crop((66,330,165,374)).getextrema()[0],96)  # Month.
        self.assertEqual(image.crop((78,228,580,266)).getextrema()[0],96)  # Date caption.
        self.assertEqual(image.crop((78,278,1580,326)).getextrema(),(255,255))  # No date axis.
        self.assertEqual(image.crop((0,1150,1648,1236)).getextrema(),(255,255))  # No footer.

    def test_year_grid_respects_month_lengths_and_boundary_today_markers(self):
        for now in (datetime(2026,1,1),datetime(2026,12,31),datetime(2024,2,29)):
            with self.subTest(date=now.date()):
                image=draw_year_progress(now,main.font)
                y=336+(now.month-1)*64+((now.month-1)//3)*24
                x=224+(now.day-1)*42
                self.assertEqual(image.getpixel((x+14,y+14)),0)
                self.assertEqual(image.getpixel((x+14,y-6)),0)
                self.assertEqual(image.getpixel((x+14,y-3)),255)
                self.assertEqual(image.getpixel((1498,414)),255)  # February has no 31st.
        common=draw_year_progress(datetime(2026,2,28),main.font)
        self.assertEqual(common.getpixel((1414,414)),255)  # No February 29th.

    def test_year_layout_revision_invalidates_same_day_cache(self):
        with tempfile.TemporaryDirectory() as root, patch.object(main,'DATA_DIR',Path(root)):
            image=Path(root)/'year.png'
            image.touch()
            now=datetime.now(main.display_timezone())
            page={'filename':image.name,'rendered_at':now.timestamp(),
                  'config_revision':main.board_settings()['revision']}
            self.assertTrue(main.page_needs_render('year-progress',page,now))
            page['render_revision']=YEAR_PROGRESS_REVISION
            self.assertFalse(main.page_needs_render('year-progress',page,now))
            page['render_revision']=YEAR_PROGRESS_REVISION-1
            self.assertTrue(main.page_needs_render('year-progress',page,now))

    def test_time_scales_use_current_units_and_render(self):
        now=datetime(2026,9,5,13,30)
        rows=period_progress(now)
        self.assertEqual([(row[0],row[1],row[2]) for row in rows],
                         [('今日',24,13),('本周',7,5),('本月',30,4),('今年',12,8)])
        for row in rows:
            self.assertGreaterEqual(row[3],0)
            self.assertLess(row[3],1)
        self.assertEqual(draw_time_scales(now,main.font).size,(1648,1236))

    def test_shared_weather_cache_and_outage_retention(self):
        settings={'latitude':24,'longitude':118,'timezone':'Asia/Shanghai'}
        sample={'temperature':28,'forecast':[{'date':'2026-09-05','high':30,'low':25}]}
        with tempfile.TemporaryDirectory() as root, patch.object(main,'DATA_DIR',Path(root)), patch.object(main,'fetch_weather',return_value=sample) as fetch:
            first=cached_weather(settings)
            second=cached_weather(settings)
            self.assertEqual(first,second)
            self.assertEqual(fetch.call_count,1)
            file=Path(root)/'weather-cache.json'
            cache=json.loads(file.read_text()); cache['fetched_at']=1; file.write_text(json.dumps(cache))
            fetch.side_effect=OSError('offline')
            retained=cached_weather(settings)
            self.assertTrue(retained['_stale'])
            self.assertEqual(retained['temperature'],28)
            self.assertEqual(retained['_fetched_at'],1)

    def test_image_cleanup_protects_registered_page_previews(self):
        with tempfile.TemporaryDirectory() as root, patch.object(main,'DATA_DIR',Path(root)), \
             patch.object(main,'read_pages_state',return_value={'pages':{'simple-calendar':{'filename':'page-calendar.png'}}}), \
             patch.object(main,'read_state',return_value={}), patch.object(main,'MAX_PAGE_IMAGES',0):
            for name in ('page-calendar.png','page-unused.png'): (Path(root)/name).touch()
            main.cleanup_page_images()
            self.assertTrue((Path(root)/'page-calendar.png').exists())
            self.assertFalse((Path(root)/'page-unused.png').exists())


if __name__=='__main__': unittest.main()
