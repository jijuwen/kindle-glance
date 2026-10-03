"""A date-driven landscape garden drawn in black pen on white paper."""
from __future__ import annotations

import calendar
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageChops, ImageDraw, ImageFont

RENDER_REVISION = 4
SIZE = (1648, 1236)
ASSETS = Path(__file__).with_name('assets') / 'annual-garden'
INK = 0
PAPER = 255
SEED_INK = 176
SECONDARY_INK = 96
WEEKDAYS = '一二三四五六日'
GRID = (44, 174, 1604, 1176)
COLUMNS = 25


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


@lru_cache(maxsize=32)
def planned_slots(year: int, seed: str):
    """Compose the whole year once; daily growth never moves existing plants.

    Unequal widths drive horizontal positions. Small groups sit closer together
    with wider pockets between them, and their baselines rise and fall. A modest
    ink-aware vertical adjustment prevents dense strokes merging into a blob.
    """
    order = order_for_year(year, seed)
    left,top,right,bottom = GRID
    rows=math.ceil(len(order)/COLUMNS)
    sy=(bottom-top)/rows
    rng=random.Random(hashlib.sha256(f'positions:v3:{year}:{seed}'.encode()).digest())
    occupied=Image.new('L',SIZE,0)
    slots=[]
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
                gaps.append(rng.uniform(13,21) if group_remaining==0 else rng.uniform(-5,4))
            if group_remaining==0:group_remaining=rng.randint(3,5)
            group_remaining-=1
        count=len(plants)
        span=(right-left)*min(1,count/COLUMNS)
        margins=rng.uniform(0,12)
        available=span-margins*2
        widths=sum(p['width'] for p in plants)
        scale=min(1.08,(available-sum(gaps))/widths)
        for plant in plants:
            plant['width']=max(1,round(plant['width']*scale))
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
            proposed=round(cy-h/2)
            choices=[]
            original=asset_mask(plant['asset_id']).crop(plant['bounds'])
            for reduction in (1,.94,.88,.82,.76):
                trial_w,trial_h=round(w*reduction),round(h*reduction)
                mask=original.resize((trial_w,trial_h),Image.Resampling.LANCZOS)
                solid=mask.point(lambda value:255 if value>=192 else 0)
                ink=max(1,solid.histogram()[255])
                for dx in ((0,) if reduction==1 else (0,-4,4)):
                    x=round(max(left,min(cx-trial_w/2+dx,right-trial_w)))
                    for offset in ((0,-5,5,-10,10) if reduction==1 else (0,-5,5,-10,10,-15,15)):
                        y=round(max(top-18,min(proposed+(h-trial_h)/2+offset,bottom+8-trial_h)))
                        overlap=ImageChops.multiply(solid,occupied.crop((x,y,x+trial_w,y+trial_h))).histogram()[255]/ink
                        score=overlap*240+abs(offset)*.04+abs(dx)*.04+(1-reduction)*8
                        choices.append((score,x,y,trial_w,trial_h,overlap,solid))
                # Keep the intended scale whenever its strokes are legible.
                # Only crowded silhouettes need a small local reduction.
                if min(choice[5] for choice in choices)<=.07:break
            _,x,y,w,h,overlap,solid=min(choices,key=lambda choice:choice[0])
            occupied.paste(ImageChops.lighter(solid,occupied.crop((x,y,x+w,y+h))),(x,y))
            slots.append({**plant,'x':x,'y':y,'width':w,'height':h,'seed_x':round(x+w/2),'seed_y':round(y+h/2),
                          'overlap_fraction':overlap})
            if column<len(gaps):cursor+=allocated_width+gaps[column]
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
    # Lay future seeds down first, so they cannot paint gray over the new,
    # intentionally larger neighbouring leaves.
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
