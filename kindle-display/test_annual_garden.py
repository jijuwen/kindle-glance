"""Garden identity, calendar boundaries, asset integrity and display regressions."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from fastapi import HTTPException
from app import annual_garden as garden, garden_drawings, main

# Each year and seed grows its own drawings, so most tests share the public
# example garden; drawing a year costs a few seconds. Hands are cached on disk
# for the module so evicted ones are read back rather than drawn again.
SEED='public-example-garden'
CACHE=tempfile.TemporaryDirectory()


def setUpModule():
    garden.configure_hands_cache(CACHE.name)


def tearDownModule():
    CACHE.cleanup()


def shape(mask):
    mask=mask.crop(mask.getbbox()).resize((50,60),Image.Resampling.LANCZOS)
    return {i for i,value in enumerate(mask.tobytes()) if value>96}


class AnnualGardenTest(unittest.TestCase):
    def test_complete_individual_assets_and_fonts(self):
        ids=garden.library()
        self.assertEqual(len(ids),365)
        additions=garden.pool()[365:]
        self.assertEqual(len(additions),54)
        self.assertEqual(len({garden.subject_of(asset_id) for asset_id in additions}),29)
        hashes=set()
        for asset_id in garden.pool()+('leap-day',):
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
        self.assertEqual(len(hashes),420)
        manifest=garden.manifest()
        for item in manifest['assets']+manifest['additions']:
            self.assertEqual(hashlib.sha256((garden.ASSETS/item['svg']).read_bytes()).hexdigest(),item['sha256'],item['id'])
            self.assertEqual(hashlib.sha256((garden.ASSETS/item['png']).read_bytes()).hexdigest(),item['png_sha256'],item['id'])
        self.assertIn('Shantell',garden.handwriting(32).getname()[0])
        self.assertIn('Yozai',garden.handwriting(32,True).getname()[0])

    def test_calendar_order_has_no_repeats_and_is_stable(self):
        order=garden.order_for_year(2026,'garden-a')
        self.assertEqual(len(order),365)
        self.assertEqual(len(set(order)),365)
        self.assertLessEqual(set(order),set(garden.pool()))
        self.assertEqual(order,garden.order_for_year(2026,'garden-a'))
        self.assertNotEqual(order,garden.order_for_year(2026,'garden-b'))
        self.assertNotEqual(order,garden.order_for_year(2027,'garden-a'))
        leap=garden.order_for_year(2024,'garden-a')
        self.assertEqual(len(set(leap)),366)
        self.assertEqual(leap[59],'leap-day')
        self.assertEqual(garden.day_counts(datetime(2024,2,29)),(60,366))
        self.assertEqual(garden.day_counts(datetime(2026,12,31)),(365,365))

    def test_growth_keeps_existing_drawings_and_replaces_the_next_seed(self):
        seed=SEED
        first=garden.draw_annual_garden(datetime(2026,1,1),seed)
        second=garden.draw_annual_garden(datetime(2026,1,2),seed)
        slots=list(garden.garden_slots(2026,seed))
        slot=slots[0];x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        # Growth preserves yesterday's strokes and uses its reserved space.
        before=first.crop((x,y,x+w,y+h));after=second.crop((x,y,x+w,y+h))
        self.assertTrue(all(b==0 for a,b in zip(before.tobytes(),after.tobytes()) if a==0))
        slot=slots[1];x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        self.assertEqual(first.getpixel((slot['seed_x'],slot['seed_y'])),80)
        self.assertEqual(second.crop((x,y,x+w,y+h)).getextrema()[0],0)
        self.assertEqual(first.mode,'L')
        self.assertEqual(first.size,(1648,1236))
        self.assertEqual(first.getpixel((0,0)),255)
        # Black date and today's featured drawing; the merged counts are gray.
        for rectangle in [(50,38,320,90),(1340,30,1600,150)]:
            self.assertEqual(first.crop(rectangle).getextrema()[0],0)
        self.assertEqual(first.crop((55,97,620,132)).getextrema()[0],96)

    def test_year_boundaries_and_positions_stay_in_frame(self):
        for year in (2024,2026,2027):
            slots=list(garden.garden_slots(year,SEED))
            self.assertEqual(len(slots),366 if year==2024 else 365)
            for slot in slots:
                self.assertGreaterEqual(slot['x'],0)
                self.assertGreaterEqual(slot['y'],garden.GRID[1]-18)
                self.assertLess(slot['x']+slot['width'],1648)
                self.assertLess(slot['y']+slot['height']+3,1236)
        image=garden.draw_annual_garden(datetime(2026,12,31),SEED)
        # A completed year contains no future gray seed centers.
        self.assertEqual(image.crop((0,1189,1648,1236)).getextrema(),(255,255))

    def test_tight_header_and_dense_garden_preserve_readable_shapes(self):
        image=garden.draw_annual_garden(datetime(2026,12,31),SEED)
        self.assertEqual(image.crop((55,97,620,132)).getextrema()[0],garden.SECONDARY_INK)
        self.assertEqual(image.crop((50,38,320,90)).getextrema()[0],0)
        # The garden starts below the compact date line and occupies substantially
        # more of the paper, without becoming a field of solid black.
        body=image.crop((44,174,1604,1184))
        density=sum(body.histogram()[:128])/(body.width*body.height)
        self.assertGreater(density,.20)
        self.assertLess(density,.40)
        slots=list(garden.garden_slots(2026,SEED))
        close=sum(b['x']-a['x']-a['width']<=8 for a,b in zip(slots,slots[1:])
                  if a['row']==b['row'])
        # Clear contours need positive gaps; retain substantial close grouping.
        self.assertGreater(close,120)
        self.assertGreater(max(s['height'] for s in slots)-min(s['height'] for s in slots),15)

    def test_rows_hold_24_or_25_days_and_the_finished_year_fills_the_page(self):
        for year,days in ((2026,365),(2028,366)):
            slots=list(garden.garden_slots(year,SEED))
            rows=[[s for s in slots if s['row']==row] for row in range(15)]
            self.assertEqual(sum(map(len,rows)),days)
            self.assertEqual({len(row) for row in rows},{24,25})
            self.assertEqual(sum(len(row)==25 for row in rows),days-15*24)
            self.assertEqual([s['index'] for s in slots],list(range(days)))
            # Every row, the last one included, reaches across the page: no
            # further in than the widest row margin plus the largest shift a
            # plant may take while it is fitted (12 + 24 pixels).
            for row in rows:
                self.assertLessEqual(min(s['x'] for s in row),garden.GRID[0]+36)
                self.assertGreaterEqual(max(s['x']+s['width'] for s in row),garden.GRID[2]-36)
        self.assertNotEqual(garden.row_counts(365,2026,'full-page'),garden.row_counts(365,2026,'other'))
        image=garden.draw_annual_garden(datetime(2026,12,31),SEED)
        self.assertEqual(image.crop((1300,1110,1600,1176)).getextrema()[0],0)

    def test_daily_growth_is_stable_with_touching_neighbours(self):
        first=garden.draw_annual_garden(datetime(2026,5,10),'touching')
        next_day=garden.draw_annual_garden(datetime(2026,5,11),'touching')
        grown=130
        slots=list(garden.garden_slots(2026,'touching'))
        for slot in slots[:grown-1]:
            x,y,w,h=(slot[k] for k in ('x','y','width','height'))
            mask=garden.asset_mask(slot['asset_id']).crop(slot['bounds']).resize((w,h),Image.Resampling.LANCZOS)
            # Every solid stroke of an earlier day stays in place.
            for offset,value in enumerate(mask.tobytes()):
                if value==255:
                    px=x+offset%w;py=y+offset//w
                    self.assertEqual(first.getpixel((px,py)),0)
                    self.assertEqual(next_day.getpixel((px,py)),0)
        self.assertEqual(list(garden.garden_slots(2026,'touching')),slots)

    def test_composition_has_size_hierarchy_and_local_breathing_room(self):
        slots=list(garden.garden_slots(2026,SEED))
        roles={role:[s['height'] for s in slots if s['role']==role]
               for role in ('canopy','accent','small','flower')}
        self.assertGreater(sum(roles['canopy'])/len(roles['canopy']),
                           sum(roles['accent'])/len(roles['accent'])+15)
        self.assertGreater(max(s['height'] for s in slots)-min(s['height'] for s in slots),40)
        gaps=[b['x']-a['x']-a['width'] for a,b in zip(slots,slots[1:])
              if a['row']==b['row']]
        self.assertGreater(sum(g<=8 for g in gaps),120)
        self.assertGreater(sum(g>=14 for g in gaps),40)
        # Variable-width composition must not settle back into equal-pitch rows.
        pitches={b['seed_x']-a['seed_x'] for a,b in zip(slots,slots[1:])
                 if a['row']==b['row']}
        self.assertGreater(max(pitches)-min(pitches),35)
        self.assertEqual(tuple(s['asset_id'].split('~')[0] for s in slots),garden.order_for_year(2026,SEED))
        slots[0]['x']=-999
        self.assertGreaterEqual(next(garden.garden_slots(2026,SEED))['x'],0)

    def test_complete_year_contours_and_seeds_have_clearance(self):
        # Rebuild the visible envelopes independently with Pillow. Test the
        # actual resized ink (including faint antialiasing), enclosed white
        # space and future seeds, rather than planner scores.
        for year,seed in ((2024,SEED),(2026,SEED),(2026,'touching'),(2027,SEED),(2028,SEED)):
            with self.subTest(year=year,seed=seed):
                occupied=Image.new('L',garden.SIZE,0)
                for slot in garden.garden_slots(year,seed):
                    x,y,w,h=(slot[k] for k in ('x','y','width','height'))
                    mask=garden.asset_mask(slot['asset_id']).crop(slot['bounds']).resize((w,h),Image.Resampling.LANCZOS)
                    envelope=Image.new('L',(w+16,h+12),0)
                    draw=ImageDraw.Draw(envelope)
                    for yy in range(h):
                        xs=[xx for xx,value in enumerate(mask.crop((0,yy,w,yy+1)).tobytes()) if value]
                        if xs:draw.line((8+min(xs),2+yy,8+max(xs),2+yy),fill=255)
                    cx,cy=8+w//2,2+h//2
                    draw.ellipse((cx-2,cy-2,cx+2,cy+2),fill=255)
                    spaced=envelope.filter(ImageFilter.MaxFilter(2*garden.OUTLINE_GAP+1))
                    rectangle=(x-8,y-2,x+w+8,y+h+10)
                    old=occupied.crop(rectangle)
                    self.assertIsNone(ImageChops.multiply(spaced,old).getbbox(),slot['asset_id'])
                    occupied.paste(ImageChops.lighter(envelope,old),(x-8,y-2))
                left,top,right,bottom=garden.GRID
                bounds=occupied.getbbox()
                self.assertGreaterEqual(bounds[0],left+garden.OUTLINE_GAP)
                self.assertGreaterEqual(bounds[1],top+garden.OUTLINE_GAP)
                self.assertLessEqual(bounds[2],right-garden.OUTLINE_GAP)
                self.assertLessEqual(bounds[3],bottom-garden.OUTLINE_GAP)

    def test_today_is_featured_in_the_header_without_an_underline(self):
        names={garden.subject_of(asset_id) for asset_id in garden.pool()+('leap-day',)}
        self.assertLessEqual(names,set(garden.SUBJECT_NAMES))
        seed=SEED
        slots=list(garden.garden_slots(2026,seed))
        today=garden.draw_annual_garden(datetime(2026,10,3),seed)
        tomorrow=garden.draw_annual_garden(datetime(2026,10,4),seed)
        # The header follows the newest drawing while the garden keeps growing.
        self.assertNotEqual(today.crop((1340,30,1600,150)).tobytes(),tomorrow.crop((1340,30,1600,150)).tobytes())
        slot=slots[275];middle=slot['x']+slot['width']//2;bottom=slot['y']+slot['height']+1
        self.assertEqual(today.crop((middle-7,bottom,middle+8,bottom+4)).getextrema(),(255,255))
        leap=garden.draw_annual_garden(datetime(2028,2,29),seed)
        self.assertEqual(leap.crop((1340,30,1600,150)).getextrema()[0],0)

    def test_seasons_follow_the_hemisphere_in_every_year(self):
        # Pin the public example's subjects and days. The drawings themselves
        # are computed with floating point, so their pixels and the layout are
        # checked for repeatability rather than pinned across platforms.
        order=garden.order_for_year(2026,SEED)
        self.assertEqual(hashlib.sha256('|'.join(order).encode()).hexdigest()[:16],'b229be62ac20296a')
        layout=[(s['asset_id'],s['x'],s['y'],s['width'],s['height']) for s in garden.planned_slots(2026,SEED)]
        garden.planned_slots.cache_clear()
        self.assertEqual([(s['asset_id'],s['x'],s['y'],s['width'],s['height'])
                          for s in garden.planned_slots(2026,SEED)],layout)
        for year in (2026,2027,2028):
            for southern in (False,True):
                with self.subTest(year=year,southern=southern):
                    order=garden.order_for_year(year,'seasons',southern)
                    self.assertEqual(len(set(order)),366 if year==2028 else 365)
                    if year==2028:self.assertEqual(order[59],'leap-day')
                    for day,asset_id in enumerate(order):
                        months=garden.season_months(garden.subject_of(asset_id),southern)
                        if months:
                            self.assertIn((datetime(year,1,1)+timedelta(day)).month,months,asset_id)
                    tulips=[day for day,asset_id in enumerate(order) if asset_id.endswith('-tulip')]
                    self.assertGreaterEqual(min(b-a for a,b in zip(tulips,tulips[1:])),3)
        self.assertEqual(garden.season_months('snowman',True),(6,7,8))
        self.assertEqual(garden.season_months('blossom',True),(9,10))
        self.assertNotEqual(garden.order_for_year(2026,'seasons'),garden.order_for_year(2026,'seasons',True))

    def test_each_year_draws_365_by_quota_with_rare_surprises(self):
        variants=Counter(garden.subject_of(asset_id) for asset_id in garden.pool())
        appearances=Counter()
        selections=set()
        for index in range(24):
            order=garden.order_for_year(2027,f'quota-{index}')
            counts=Counter(garden.subject_of(asset_id) for asset_id in order)
            rares=sum(counts[subject] for subject in garden.RARE)
            for subject in garden.RARE:
                self.assertLessEqual(counts[subject],1)
                appearances[subject]+=counts[subject]
            # Absent rare subjects hand their days to the wildflowers and daisies.
            self.assertEqual(counts['clover']+counts['daisy'],52+6-rares)
            self.assertGreaterEqual(counts['clover'],30)
            self.assertGreaterEqual(counts['daisy'],22)
            for subject,count in variants.items():
                if subject not in garden.RARE+garden.FILLERS:
                    self.assertEqual(counts[subject],garden.QUOTAS.get(subject,count),subject)
            selections.add(frozenset(order))
        # Look-alike subjects show a different subset of their drawings each year.
        self.assertGreater(len(selections),20)
        for subject in garden.RARE:
            self.assertTrue(4<=appearances[subject]<=20,(subject,appearances[subject]))

    def test_the_server_pen_still_draws_the_committed_library(self):
        # New hands use the same pen; its numbered drawings must stay exactly
        # the committed files, which the asset builder also relies on.
        manifest=garden.manifest()
        for item in manifest['assets'][::23]+manifest['additions'][::9]:
            number=int(item['id'].split('-',1)[0])
            if number<garden_drawings.FIRST_ADDITION:
                drawing=garden_drawings.draw_asset(item['subject'],number)
            else:
                _,drawer,variant=garden_drawings.ADDITIONS[number-garden_drawings.FIRST_ADDITION]
                drawing=garden_drawings.Pen(number);drawer(drawing,variant)
            self.assertEqual(drawing.mask().tobytes(),garden.asset_mask(item['id']).tobytes(),item['id'])

    def test_every_day_grows_its_own_hand_of_its_subject(self):
        slots=list(garden.garden_slots(2026,SEED))
        keys=[s['asset_id'] for s in slots]
        self.assertEqual(len(set(keys)),365)
        masks=[garden.asset_mask(key) for key in keys]
        self.assertEqual(len({mask.tobytes() for mask in masks}),365)
        # The library drawing is only a rare fallback when no hand fits.
        library=sum(mask.tobytes()==garden.asset_mask(key.split('~')[0]).tobytes() for key,mask in zip(keys,masks))
        self.assertLessEqual(library,3)
        # Subjects the library held as near-copies now differ day by day.
        groups={}
        for key,mask in zip(keys,masks):
            groups.setdefault(garden.subject_of(key),[]).append(shape(mask))
        for subject in ('berries','succulent','apple','fish','bush','seaweed'):
            pairs=[len(a&b)/len(a|b) for i,a in enumerate(groups[subject]) for b in groups[subject][i+1:]]
            self.assertLess(max(pairs),.8,subject)
        # The same library drawing grows as a different hand in another year.
        later={key.split('~')[0]:key for key in (s['asset_id'] for s in garden.garden_slots(2027,SEED))}
        shared=[key for key in keys if key.split('~')[0] in later][:40]
        self.assertTrue(all(garden.asset_mask(key).tobytes()!=garden.asset_mask(later[key.split('~')[0]]).tobytes() for key in shared))
        # Every hand lies within its subject's darkness, ink and proportions.
        for key,mask in zip(keys[:120],masks[:120]):
            subject=garden.subject_of(key)
            self.assertTrue(garden.hand_fits(mask,subject) or mask.tobytes()==garden.asset_mask(key.split('~')[0]).tobytes(),key)

    def test_hands_cache_is_warmed_in_batches_repaired_and_pruned(self):
        previous=garden.HANDS_CACHE
        with tempfile.TemporaryDirectory() as directory:
            garden.configure_hands_cache(directory)
            try:
                passes=1
                while not garden.warm_hands(2031,'cache-test',budget=120):
                    passes+=1
                self.assertEqual(passes,4)
                folder=Path(directory)/f'r{garden.HANDS_REVISION}'
                self.assertEqual(len(list(folder.glob('*.png'))),365)
                key=garden.hand_key(2031,'cache-test',garden.order_for_year(2031,'cache-test')[0])
                fresh,_=garden.draw_hand_mask(key)
                cached,attempt=garden.hand_mask(key)
                self.assertIsNone(attempt)
                self.assertEqual(cached.tobytes(),fresh.tobytes())
                garden.hand_file(key).write_bytes(b'damaged')
                repaired,attempt=garden.hand_mask(key)
                self.assertIsNotNone(attempt)
                self.assertEqual(repaired.tobytes(),fresh.tobytes())
                self.assertIsNone(garden.hand_mask(key)[1])
                # Earlier years and earlier revisions go; this year's hands stay.
                (folder/'2029-old.png').write_bytes(b'old')
                (Path(directory)/'r0').mkdir()
                (Path(directory)/'r0'/'2031-old.png').write_bytes(b'old')
                garden.prune_hands(2031)
                self.assertFalse((folder/'2029-old.png').exists())
                self.assertFalse((Path(directory)/'r0').exists())
                self.assertEqual(len(list(folder.glob('*.png'))),365)
            finally:
                garden.HANDS_CACHE=previous

    def test_server_warms_this_year_and_next_year_in_december(self):
        calls=[]

        def warm(year,seed,budget=40):
            calls.append(year)
            return True
        settings={'latitude':24.0,'timezone':'Asia/Shanghai'}
        playlist={'items':[main.default_playlist_item('annual-garden')]}
        with tempfile.TemporaryDirectory() as directory,patch.object(main,'DATA_DIR',Path(directory)), \
                patch.object(main,'board_settings',return_value=settings), \
                patch.object(main,'read_playlist_state',return_value=playlist), \
                patch.object(main,'warm_hands',side_effect=warm),patch.object(main,'prune_hands') as prune:
            main._GARDEN_PRUNED.clear()
            main.warm_annual_garden(datetime(2026,10,18,9))
            self.assertEqual(calls,[2026])
            main.warm_annual_garden(datetime(2026,12,2,9))
            self.assertEqual(calls,[2026,2026,2027])
            main.warm_annual_garden(datetime(2026,12,2,10))
            self.assertEqual(prune.call_count,2)
            calls.clear()
            with patch.object(main,'read_playlist_state',return_value={'items':[main.default_playlist_item('simple-calendar')]}):
                main.warm_annual_garden(datetime(2026,10,18,9))
            self.assertEqual(calls,[])
            self.assertEqual(garden.HANDS_CACHE,Path(directory)/'annual-garden-hands')
        garden.configure_hands_cache(CACHE.name)

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
