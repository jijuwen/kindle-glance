"""A date-driven landscape garden drawn in black pen on white paper."""
from __future__ import annotations

import calendar
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont

RENDER_REVISION = 6
SIZE = (1648, 1236)
ASSETS = Path(__file__).with_name('assets') / 'annual-garden'
INK = 0
PAPER = 255
SEED_INK = 80
SECONDARY_INK = 96
WEEKDAYS = '一二三四五六日'
GRID = (44, 174, 1604, 1176)
COLUMNS = 25
OUTLINE_GAP = 2


@lru_cache(maxsize=1)
def library() -> tuple[str, ...]:
    manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    ids = tuple(item['id'] for item in manifest['assets'])
    if manifest['count'] != 365 or len(ids) != 365 or len(set(ids)) != 365:
        raise RuntimeError('年度花园素材库不完整')
    return ids


@lru_cache(maxsize=512)
def asset_mask(asset_id: str) -> Image.Image:
    if asset_id != 'leap-day' and asset_id not in library():
        raise ValueError('unknown garden illustration')
    with Image.open(ASSETS / 'png' / f'{asset_id}.png') as image:
        return image.getchannel('A').copy()


@lru_cache(maxsize=128)
def handwriting(size: int, chinese: bool = False, bold: bool = False):
    name = 'Yozai-Medium.ttf' if chinese else 'ShantellSans.ttf'
    face = ImageFont.truetype(str(ASSETS / 'fonts' / name), size)
    if not chinese:
        face.set_variation_by_axes([650 if bold else 500, 45, 25, 0])
    return face


def hand_text(draw, position, text, size, anchor='lt', bold=False, ink=INK):
    """Use the matching pen faces for Chinese and numeric/Latin runs."""
    runs = []
    for character in str(text):
        chinese = ord(character) > 127
        if runs and runs[-1][0] == chinese:
            runs[-1] = (chinese, runs[-1][1] + character)
        else:
            runs.append((chinese, character))
    faces = [(value, handwriting(size, chinese, bold)) for chinese, value in runs]
    width = sum(face.getlength(value) for value, face in faces)
    x,y = position
    if anchor[0]=='r': x-=width
    elif anchor[0]=='m': x-=width/2
    # Baseline alignment avoids the Chinese labels floating above the numerals.
    baseline = y + size*.84
    for value, face in faces:
        draw.text((x,baseline),value,font=face,fill=ink,anchor='ls')
        x += face.getlength(value)
    return width


def day_counts(now):
    total = 366 if calendar.isleap(now.year) else 365
    ordinal = now.timetuple().tm_yday
    return ordinal, total


@lru_cache(maxsize=128)
def order_for_year(year: int, seed: str) -> tuple[str, ...]:
    order = list(library())
    digest = hashlib.sha256(f'annual-garden:v1:{year}:{seed}'.encode()).digest()
    random.Random(int.from_bytes(digest,'big')).shuffle(order)
    if calendar.isleap(year):
        order.insert(59,'leap-day')
    return tuple(order)


CANOPY_SUBJECTS = frozenset(('tree','pine','palm','bush','fern','seaweed','bamboo','vine','rosemary','twig'))
ACCENT_SUBJECTS = frozenset(('apple','pumpkin','fig','onion','acorn','cherry','banana','grapes','raspberry',
    'mushroom','ladybug','bee','butterfly','snail','fish','frog','mouse','hedgehog','tortoise','worm',
    'bird','cow','rainbow','house','camp','log','stones','honeycomb','watermelon'))
SMALL_SUBJECTS = frozenset(('sprout','clover','bell','droop','tulip'))


def plant_size(subject: str, rng, row_height: float):
    """Size by visual mass: tall foliage, smaller round accents, mixed flowers."""
    if subject in CANOPY_SUBJECTS:
        return rng.uniform(1.23,1.43)*row_height, 88, 'canopy'
    if subject in ACCENT_SUBJECTS:
        return rng.uniform(.87,1.05)*row_height, 72, 'accent'
    if subject in SMALL_SUBJECTS:
        return rng.uniform(.96,1.17)*row_height, 70, 'small'
    return rng.uniform(1.08,1.30)*row_height, 82, 'flower'


@lru_cache(maxsize=4096)
def silhouette_rows(asset_id: str, width: int, height: int):
    """Protect the whole drawing, including white interiors and open branches.

    Fill the span between the outermost ink pixels on each scanline. Unlike a
    bounding rectangle this retains the narrower stem and concave sides, while
    preventing another plant from entering a flower, rainbow or bamboo clump.
    Include antialiasing, the future seed and the possible today underline.
    """
    original = asset_mask(asset_id)
    mask = original.crop(original.getbbox()).resize((width, height), Image.Resampling.LANCZOS)
    pixels = mask.tobytes()
    spans = {}

    def reserve(y, left, right):
        if y in spans:
            previous = spans[y]
            left, right = min(left, previous[0]), max(right, previous[1])
        spans[y] = (left, right)

    for y in range(height):
        row = pixels[y*width:(y+1)*width]
        left = width-len(row.lstrip(b'\0'))
        right = len(row.rstrip(b'\0'))
        if right > left:
            reserve(y, left, right)
    cx, cy = width//2, height//2
    for y in range(cy-2, cy+3):
        reserve(y, cx-2, cx+3)
    for y in range(height+1, height+5):
        reserve(y, cx-7, cx+8)
    return tuple((y, left, right) for y, (left, right) in sorted(spans.items()))


def row_bits(spans):
    """Pack occupied scanlines into integers for inexpensive exact collisions."""
    origin = min(left for _, left, _ in spans)
    return origin, tuple((y, ((1 << (right-left))-1) << (left-origin))
                         for y, left, right in spans)


def spaced_rows(spans):
    expanded = {}
    for y, left, right in spans:
        for yy in range(y-OUTLINE_GAP, y+OUTLINE_GAP+1):
            a, b = expanded.get(yy, (left-OUTLINE_GAP, right+OUTLINE_GAP))
            expanded[yy] = min(a, left-OUTLINE_GAP), max(b, right+OUTLINE_GAP)
    return tuple((y, left, right) for y, (left, right) in sorted(expanded.items()))


POSITION_OFFSETS = tuple(sorted(
    ((dx, dy) for dx in range(-24, 25, 3) for dy in range(-30, 31, 3)),
    key=lambda offset: (abs(offset[0])*.09+abs(offset[1])*.07,
                        abs(offset[1]), abs(offset[0]), offset)))


def occupy(slot, occupied, *, remove=False):
    spans = silhouette_rows(slot['asset_id'], slot['width'], slot['height'])
    origin, bits = row_bits(spans)
    for yy, line in bits:
        value = line << (slot['x']+origin)
        if remove:
            occupied[slot['y']+yy] ^= value
        else:
            occupied[slot['y']+yy] |= value


def place_plant(plant, cx, cy, occupied, row_top, row_bottom, fallback):
    """Accept only collision-free candidates; movement and scale rank those."""
    left, top, right, bottom = GRID
    best = (12*(1-fallback['scale'])+abs(fallback['x']+fallback['width']/2-cx)*.09
            +abs(fallback['y']+fallback['height']/2-cy)*.07,
            fallback['x'], fallback['y'], fallback['width'], fallback['height'], fallback['scale'])
    for reduction in (1, .96, .92, .88, .84, .80, .76, .72, .68, .64, .60, .56):
        if reduction < fallback['scale']:
            break
        shrink_cost = (1-reduction)*12
        if shrink_cost >= best[0]:
            break
        w, h = max(1, round(plant['width']*reduction)), max(1, round(plant['height']*reduction))
        safe_spans = spaced_rows(silhouette_rows(plant['asset_id'], w, h))
        origin, bits = row_bits(safe_spans)
        min_x = min(a for _, a, _ in safe_spans)
        max_x = max(b for _, _, b in safe_spans)
        min_y, max_y = safe_spans[0][0], safe_spans[-1][0]+1
        x_low, x_high = left-min_x, right-max_x
        y_low = math.ceil(max(top, row_top-14)-min_y)
        y_high = math.floor(min(bottom, row_bottom+14)-max_y)
        if x_high < x_low or y_high < y_low:
            continue
        for dx, dy in POSITION_OFFSETS:
            score = shrink_cost+abs(dx)*.09+abs(dy)*.07
            if score >= best[0]:
                break
            x = max(x_low, min(round(cx-w/2+dx), x_high))
            y = max(y_low, min(round(cy-h/2+dy), y_high))
            shift = x+origin
            if any((line << shift) & occupied[y+yy] for yy, line in bits):
                continue
            best = (score, x, y, w, h, reduction)
            break
    _, x, y, w, h, reduction = best
    slot = {**plant, 'x': x, 'y': y, 'width': w, 'height': h,
            'seed_x': x+w//2, 'seed_y': y+h//2, 'scale': reduction,
            'overlap_fraction': 0.0}
    occupy(slot, occupied)
    return slot


@lru_cache(maxsize=32)
def planned_slots(year: int, seed: str):
    """Compose the whole year once; daily growth never moves existing plants.

    Unequal widths drive horizontal positions. Small groups sit closer together
    with wider pockets between them, and their baselines rise and fall.
    Silhouette-aware placement forbids overlaps, including white interiors.
    """
    order = order_for_year(year, seed)
    left,top,right,bottom = GRID
    rows=math.ceil(len(order)/COLUMNS)
    sy=(bottom-top)/rows
    rng=random.Random(hashlib.sha256(f'positions:v3:{year}:{seed}'.encode()).digest())
    occupied=[0]*SIZE[1]
    anchors=[]
    for row in range(rows):
        row_order=order[row*COLUMNS:(row+1)*COLUMNS]
        plants=[]; gaps=[]; group_remaining=0; phase=rng.uniform(0,math.tau)
        for column,asset_id in enumerate(row_order):
            bounds=asset_mask(asset_id).getbbox()
            subject=asset_id.split('-',1)[-1]
            height,cap,role=plant_size(subject,rng,sy)
            width=height*(bounds[2]-bounds[0])/(bounds[3]-bounds[1])
            if width>cap:height*=cap/width;width=cap
            plants.append({'index':row*COLUMNS+column,'asset_id':asset_id,'bounds':bounds,
                           'width':width,'height':height,'role':role})
            if column:
                # Short, irregular clusters, with pockets that do not form
                # continuous vertical channels through the garden.
                gaps.append(rng.uniform(13,21) if group_remaining==0 else rng.uniform(2,5))
            if group_remaining==0:group_remaining=rng.randint(3,5)
            group_remaining-=1
        count=len(plants)
        span=(right-left)*min(1,count/COLUMNS)
        margins=rng.uniform(OUTLINE_GAP+1,12)
        available=span-margins*2
        widths=sum(p['width'] for p in plants)
        scale=min(1.08,(available-sum(gaps))/widths)
        for plant in plants:
            plant['width']=max(18,round(plant['width']*scale))
            plant['height']=max(1,round(plant['height']*scale))
        # Add spare room mainly to the breathing pockets. Preserve close local
        # neighbours instead of diluting all gaps into the same spacing.
        spare=available-sum(p['width'] for p in plants)-sum(gaps)
        weights=[2.8 if gap>10 else 1 for gap in gaps]
        weight_sum=sum(weights) or 1
        gaps=[gap+spare*weight/weight_sum for gap,weight in zip(gaps,weights)]
        cursor=left+margins
        for column,plant in enumerate(plants):
            w,h=plant['width'],plant['height']
            allocated_width=w
            cx=cursor+w/2
            cy=top+(row+.5)*sy+math.sin(column*.83+phase)*9+rng.uniform(-3,3)
            if plant['role']=='accent':cy+=6
            elif plant['role']=='canopy':cy-=3
            anchors.append((plant, cx, cy, top+row*sy, top+(row+1)*sy))
            if column<len(gaps):cursor+=allocated_width+gaps[column]
    # Reserve a readable minimum silhouette for every day before enlarging any
    # of them. This prevents large early plants from consuming the space needed
    # by smaller neighbours or the last row. The placeholders are disjoint.
    slots = [None]*len(order)
    for plant, cx, cy, row_top, row_bottom in anchors:
        reduction = min(.76, math.floor(sy-12)/plant['height'])
        w, h = round(plant['width']*reduction), round(plant['height']*reduction)
        x, y = round(cx-w/2), round(row_top+(sy-h-5)/2)
        slot = {**plant, 'x': x, 'y': y, 'width': w, 'height': h,
                'seed_x': x+w//2, 'seed_y': y+h//2, 'scale': reduction,
                'overlap_fraction': 0.0}
        safe = spaced_rows(silhouette_rows(plant['asset_id'], w, h))
        origin, bits = row_bits(safe)
        if (x+min(a for _, a, _ in safe) < left or x+max(b for _, _, b in safe) > right
                or y+safe[0][0] < top or y+safe[-1][0] >= bottom):
            raise RuntimeError('年度花园最小轮廓超出画布')
        if any((line << (x+origin)) & occupied[y+yy] for yy, line in bits):
            raise RuntimeError('年度花园最小轮廓预留空间不足')
        slots[plant['index']] = slot
        occupy(slot, occupied)
    # Compose structural foliage first, then fit flowers and smaller accents
    # around it. A final pass reclaims remaining pockets for crowded plants.
    priority = {'canopy': 0, 'flower': 1, 'small': 2, 'accent': 3}
    for plant, cx, cy, row_top, row_bottom in sorted(anchors, key=lambda a: (priority[a[0]['role']], a[0]['index'])):
        old = slots[plant['index']]
        occupy(old, occupied, remove=True)
        slots[plant['index']] = place_plant(plant, cx, cy, occupied, row_top, row_bottom, old)
    for plant, cx, cy, row_top, row_bottom in sorted(anchors, key=lambda a: (slots[a[0]['index']]['scale'], a[0]['index'])):
        old = slots[plant['index']]
        occupy(old, occupied, remove=True)
        slots[plant['index']] = place_plant(plant, cx, cy, occupied, row_top, row_bottom, old)
    return tuple(slots)


def garden_slots(year: int, seed: str):
    # Do not expose the cached dictionaries for mutation by callers.
    return (dict(slot) for slot in planned_slots(year,seed))


def draw_annual_garden(now, seed: str, *, full: bool = False) -> Image.Image:
    ordinal,total=day_counts(now)
    image=Image.new('L',SIZE,PAPER)
    draw=ImageDraw.Draw(image)
    hand_text(draw,(54,40),'年度花园',48)
    hand_text(draw,(58,98),f'{now.month}月{now.day}日 · 周{WEEKDAYS[now.weekday()]}',30)
    hand_text(draw,(824,53),f'第 {ordinal} 天 · 还剩 {total-ordinal} 天',30,'mt')
    hand_text(draw,(1590,50),f'{now.year} · 已过 {ordinal/total*100:.1f}%',32,'rt',ink=SECONDARY_INK)

    grown=total if full else ordinal
    slots=list(garden_slots(now.year,seed))
    # Each future seed and today marker has space reserved by the annual plan.
    for slot in slots[grown:]:
        cx,cy=slot['seed_x'],slot['seed_y']
        draw.ellipse((cx-2,cy-2,cx+2,cy+2),fill=SEED_INK)
    for slot in slots[:grown]:
        x,y,w,h=slot['x'],slot['y'],slot['width'],slot['height']
        mask=asset_mask(slot['asset_id']).crop(slot['bounds']).resize((w,h),Image.Resampling.LANCZOS)
        image.paste(INK,(x,y,x+w,y+h),mask)
    if not full:
        slot=slots[ordinal-1];middle=slot['x']+slot['width']/2
        y=slot['y']+slot['height']+2
        draw.line([(middle-6,y),(middle-1,y+1),(middle+6,y)],fill=INK,width=2)
    return image
