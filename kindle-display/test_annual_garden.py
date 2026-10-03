"""Garden identity, calendar boundaries, asset integrity and display regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from fastapi import HTTPException
from app import annual_garden as garden, main


class AnnualGardenTest(unittest.TestCase):
    def test_complete_individual_assets_and_fonts(self):
        ids=garden.library()
        self.assertEqual(len(ids),365)
        hashes=set()
        for asset_id in ids+('leap-day',):
            mask=garden.asset_mask(asset_id)
            self.assertIsNotNone(mask.getbbox(),asset_id)
            left,top,right,bottom=mask.getbbox()
            self.assertGreater(left,0,asset_id)
            self.assertGreater(top,0,asset_id)
            self.assertLess(right,mask.width,asset_id)
            self.assertLess(bottom,mask.height,asset_id)
            self.assertEqual(mask.getextrema()[1],255,asset_id)
            self.assertLess(sum(mask.histogram()[192:]),mask.width*mask.height*.55,asset_id)
            hashes.add(hashlib.sha256(mask.tobytes()).hexdigest())
            self.assertIn('viewBox="0 0 100 120"',(garden.ASSETS/'svg'/f'{asset_id}.svg').read_text())
        self.assertEqual(len(hashes),366)
        self.assertIn('Shantell',garden.handwriting(32).getname()[0])
        self.assertIn('Yozai',garden.handwriting(32,True).getname()[0])

    def test_calendar_order_has_no_repeats_and_is_stable(self):
        order=garden.order_for_year(2026,'garden-a')
        self.assertEqual(set(order),set(garden.library()))
        self.assertEqual(order,garden.order_for_year(2026,'garden-a'))
        self.assertNotEqual(order,garden.order_for_year(2026,'garden-b'))
        self.assertNotEqual(order,garden.order_for_year(2027,'garden-a'))
        leap=garden.order_for_year(2024,'garden-a')
        self.assertEqual(len(set(leap)),366)
        self.assertEqual(leap[59],'leap-day')
        self.assertEqual(garden.day_counts(datetime(2024,2,29)),(60,366))
        self.assertEqual(garden.day_counts(datetime(2026,12,31)),(365,365))

    def test_growth_keeps_existing_drawings_and_replaces_the_next_seed(self):
        seed='calendar-growth'
        first=garden.draw_annual_garden(datetime(2026,1,1),seed)
        second=garden.draw_annual_garden(datetime(2026,1,2),seed)
        slots=list(garden.garden_slots(2026,seed))
        slot=slots[0];x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        # Adjacent leaves now intentionally share some space. New ink can enter
        # the old drawing's bounds, but cannot erase its existing black strokes.
        before=first.crop((x,y,x+w,y+h));after=second.crop((x,y,x+w,y+h))
        self.assertTrue(all(b==0 for a,b in zip(before.tobytes(),after.tobytes()) if a==0))
        slot=slots[1];x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        self.assertEqual(first.getpixel((slot['seed_x'],slot['seed_y'])),176)
        self.assertEqual(second.crop((x,y,x+w,y+h)).getextrema()[0],0)
        self.assertEqual(first.mode,'L')
        self.assertEqual(first.size,(1648,1236))
        self.assertEqual(first.getpixel((0,0)),255)
        for rectangle in [(48,35,285,88),(640,45,1010,88)]:
            self.assertEqual(first.crop(rectangle).getextrema()[0],0)
        self.assertEqual(first.crop((1150,40,1600,95)).getextrema()[0],96)

    def test_year_boundaries_and_positions_stay_in_frame(self):
        for year in (2024,2026,2027):
            slots=list(garden.garden_slots(year,'bounds'))
            self.assertEqual(len(slots),366 if year==2024 else 365)
            for slot in slots:
                self.assertGreaterEqual(slot['x'],0)
                self.assertGreaterEqual(slot['y'],garden.GRID[1]-18)
                self.assertLess(slot['x']+slot['width'],1648)
                self.assertLess(slot['y']+slot['height']+3,1236)
        image=garden.draw_annual_garden(datetime(2026,12,31),'bounds')
        # A completed year contains no future gray seed centers.
        self.assertEqual(image.crop((0,1189,1648,1236)).getextrema(),(255,255))

    def test_tight_header_and_dense_garden_preserve_readable_shapes(self):
        image=garden.draw_annual_garden(datetime(2026,12,31),'density')
        self.assertEqual(image.crop((1150,40,1600,95)).getextrema()[0],garden.SECONDARY_INK)
        self.assertEqual(image.crop((48,35,285,88)).getextrema()[0],0)
        # The garden starts below the compact date line and occupies substantially
        # more of the paper, without becoming a field of solid black.
        body=image.crop((44,174,1604,1184))
        density=sum(body.histogram()[:128])/(body.width*body.height)
        self.assertGreater(density,.20)
        self.assertLess(density,.40)
        slots=list(garden.garden_slots(2026,'density'))
        close=sum(b['x']-a['x']-a['width']<=8 for a,b in zip(slots,slots[1:])
                  if a['index']//garden.COLUMNS==b['index']//garden.COLUMNS)
        self.assertGreater(close,200)
        self.assertGreater(max(s['height'] for s in slots)-min(s['height'] for s in slots),15)

    def test_daily_growth_is_stable_with_touching_neighbours(self):
        first=garden.draw_annual_garden(datetime(2026,5,10),'touching')
        next_day=garden.draw_annual_garden(datetime(2026,5,11),'touching')
        grown=130
        slots=list(garden.garden_slots(2026,'touching'))
        for slot in slots[:grown-1]:
            x,y,w,h=(slot[k] for k in ('x','y','width','height'))
            mask=garden.asset_mask(slot['asset_id']).crop(slot['bounds']).resize((w,h),Image.Resampling.LANCZOS)
            # Check solid strokes, excluding yesterday's movable today marker.
            for offset,value in enumerate(mask.tobytes()):
                if value==255:
                    px=x+offset%w;py=y+offset//w
                    self.assertEqual(first.getpixel((px,py)),0)
                    self.assertEqual(next_day.getpixel((px,py)),0)
        self.assertEqual(list(garden.garden_slots(2026,'touching')),slots)

    def test_composition_has_size_hierarchy_and_local_breathing_room(self):
        slots=list(garden.garden_slots(2026,'composition'))
        roles={role:[s['height'] for s in slots if s['role']==role]
               for role in ('canopy','accent','small','flower')}
        self.assertGreater(sum(roles['canopy'])/len(roles['canopy']),
                           sum(roles['accent'])/len(roles['accent'])+15)
        self.assertGreater(max(s['height'] for s in slots)-min(s['height'] for s in slots),40)
        gaps=[b['x']-a['x']-a['width'] for a,b in zip(slots,slots[1:])
              if a['index']//garden.COLUMNS==b['index']//garden.COLUMNS]
        self.assertGreater(sum(g<=8 for g in gaps),150)
        self.assertGreater(sum(g>=14 for g in gaps),40)
        # Variable-width composition must not settle back into equal-pitch rows.
        pitches={b['seed_x']-a['seed_x'] for a,b in zip(slots,slots[1:])
                 if a['index']//garden.COLUMNS==b['index']//garden.COLUMNS}
        self.assertGreater(max(pitches)-min(pitches),35)
        self.assertLess(max(s['overlap_fraction'] for s in slots),.16)
        self.assertEqual(tuple(s['asset_id'] for s in slots),garden.order_for_year(2026,'composition'))
        slots[0]['x']=-999
        self.assertGreaterEqual(next(garden.garden_slots(2026,'composition'))['x'],0)

    def test_persistent_identity_concurrent_calls_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(main,'DATA_DIR',Path(directory)):
            with ThreadPoolExecutor(max_workers=6) as pool:
                seeds=list(pool.map(lambda _:main.annual_garden_seed(),range(12)))
            self.assertEqual(len(set(seeds)),1)
            path=Path(directory)/'annual-garden.json'
            self.assertEqual(json.loads(path.read_text())['seed'],seeds[0])
            path.write_text('{invalid',encoding='utf-8')
            with self.assertRaises(HTTPException):main.annual_garden_seed()
            self.assertEqual(path.read_text(),'{invalid')

    def test_registered_landscape_daily_cache_in_display_timezone(self):
        self.assertEqual(main.PAGE_DEFINITIONS['annual-garden']['orientation'],'landscape')
        self.assertEqual(main.default_playlist_item('annual-garden')['rotation'],90)
        with tempfile.TemporaryDirectory() as directory,patch.object(main,'DATA_DIR',Path(directory)),patch.object(main,'board_settings',return_value={'revision':4}):
            (Path(directory)/'cached.png').write_bytes(b'cached')
            now=datetime(2026,10,2,23,59,tzinfo=ZoneInfo('Asia/Shanghai'))
            page={'filename':'cached.png','config_revision':4,'render_revision':garden.RENDER_REVISION,'rendered_at':now.timestamp()}
            self.assertFalse(main.page_needs_render('annual-garden',page,now))
            self.assertTrue(main.page_needs_render('annual-garden',page,now+timedelta(minutes=2)))
            self.assertTrue(main.page_needs_render('annual-garden',{**page,'render_revision':0},now))


if __name__=='__main__':unittest.main()
