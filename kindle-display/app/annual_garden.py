"""A date-driven landscape garden drawn in black pen on white paper."""
from __future__ import annotations

import calendar
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import random
import threading

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from app import garden_drawings

RENDER_REVISION = 10
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
# Header feature for the drawing that grew today: right edge, bottom, size cap.
TODAY_RIGHT, TODAY_BOTTOM, TODAY_HEIGHT, TODAY_WIDTH = 1590, 146, 112, 150

SUBJECT_NAMES = {
    'acorn': '橡果', 'apple': '苹果', 'bamboo': '竹子', 'banana': '香蕉', 'bee': '蜜蜂', 'bell': '风铃草',
    'berries': '浆果', 'bird': '小鸟', 'bush': '灌木', 'butterfly': '蝴蝶', 'cactus': '仙人掌', 'camp': '帐篷',
    'carrot': '胡萝卜', 'caterpillar': '毛毛虫', 'cherry': '樱桃', 'clover': '小野花', 'cow': '奶牛',
    'daisy': '雏菊', 'droop': '垂头花', 'fern': '蕨叶', 'fig': '无花果', 'fish': '小鱼', 'frog': '青蛙',
    'grapes': '葡萄', 'grass': '草丛', 'hedgehog': '刺猬', 'heron': '苍鹭', 'honeycomb': '蜂巢',
    'house': '小屋', 'ladybug': '瓢虫', 'lily': '百合', 'log': '原木', 'moon': '月亮', 'mouse': '小老鼠',
    'mushroom': '蘑菇', 'onion': '洋葱', 'owl': '猫头鹰', 'palm': '棕榈', 'pepper': '甜椒', 'pine': '松树',
    'pumpkin': '南瓜', 'rainbow': '彩虹', 'rake': '耙子', 'raspberry': '树莓', 'rose': '玫瑰',
    'rosemary': '迷迭香', 'sailboat': '帆船', 'seaweed': '水草', 'sheep': '绵羊', 'shrub': '树丛',
    'signpost': '路牌', 'slug': '蛞蝓', 'snail': '蜗牛', 'snake': '小蛇', 'snowman': '雪人', 'spade': '铲子',
    'spiderweb': '蛛网', 'spiralflower': '黑心菊', 'sprout': '新芽', 'star': '星星', 'stones': '叠石',
    'strawberry': '草莓', 'stump': '树桩', 'succulent': '多肉', 'sun': '太阳', 'sunflower': '向日葵',
    'tortoise': '乌龟', 'tree': '小树', 'tulip': '郁金香', 'twig': '枝条', 'vine': '藤蔓',
    'wateringcan': '洒水壶', 'waterlily': '睡莲', 'well': '水井', 'witch': '小女巫', 'worm': '小虫',
    'ant': '蚂蚁', 'beehive': '蜂箱', 'birdhouse': '鸟屋', 'blossom': '樱花枝', 'boots': '雨靴', 'cat': '小猫',
    'dandelion': '蒲公英', 'dragonfly': '蜻蜓', 'flowerpot': '花盆', 'foxtail': '狗尾巴草', 'gourd': '葫芦',
    'hydrangea': '绣球', 'lavender': '薰衣草', 'lotus': '荷花', 'lotuspod': '莲蓬', 'luckyclover': '幸运草',
    'maple': '枫叶', 'mole': '鼹鼠', 'morningglory': '牵牛花', 'peapod': '豌豆', 'persimmon': '柿子',
    'pinwheel': '风车', 'rabbit': '兔子', 'scarecrow': '稻草人', 'shamrock': '三叶草', 'snowflake': '雪花',
    'squirrel': '松鼠', 'tomato': '番茄', 'wheelbarrow': '手推车',
    'leap-day': '闰日花',
}

# Northern-hemisphere months; the southern hemisphere shifts them by six.
SEASONS = {
    'blossom': (3, 4), 'dandelion': (3, 4, 5), 'tulip': (3, 4, 5), 'peapod': (4, 5, 6),
    'cherry': (5, 6), 'strawberry': (5, 6, 7), 'raspberry': (6, 7, 8), 'waterlily': (6, 7, 8),
    'lotus': (6, 7, 8), 'tomato': (6, 7, 8, 9), 'lotuspod': (7, 8, 9), 'sunflower': (7, 8, 9),
    'grapes': (8, 9, 10), 'fig': (8, 9, 10), 'apple': (9, 10, 11), 'persimmon': (9, 10, 11),
    'pumpkin': (10, 11), 'acorn': (10, 11), 'maple': (10, 11), 'snowman': (12, 1, 2), 'snowflake': (12, 1, 2),
}
# Each year grows 365 drawings from the library. Subjects with many look-alike
# drawings contribute only part of them, chosen anew each year; every other
# subject contributes all of its drawings.
QUOTAS = {'clover': 30, 'daisy': 22, 'berries': 6, 'succulent': 4, 'apple': 4, 'bell': 6}
# Rare subjects appear at most once, in about half of all years. Their unused
# days go to further wildflowers and daisies.
RARE = ('luckyclover', 'rainbow', 'sailboat', 'scarecrow', 'witch')
FILLERS = ('clover', 'daisy')
MONTH_OF_DAY = tuple(month for month in range(1, 13) for _ in range(calendar.mdays[month]))


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def library() -> tuple[str, ...]:
    """The 365 drawings redrawn from the reference garden."""
    ids = tuple(item['id'] for item in manifest()['assets'])
    if manifest()['count'] != 365 or len(ids) != 365 or len(set(ids)) != 365:
        raise RuntimeError('年度花园素材库不完整')
    return ids


@lru_cache(maxsize=1)
def pool() -> tuple[str, ...]:
    """Every drawing a year can grow: the reference set plus original additions."""
    ids = library()+tuple(item['id'] for item in manifest().get('additions', ()))
    if len(set(ids)) != len(ids):
        raise RuntimeError('年度花园素材库不完整')
    return ids


@lru_cache(maxsize=1024)
def asset_mask(asset_id: str) -> Image.Image:
    if '~' in asset_id:
        return hand_mask(asset_id)[0]
    if asset_id != 'leap-day' and asset_id not in pool():
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


def subject_of(asset_id: str) -> str:
    asset_id = asset_id.split('~', 1)[0]
    return asset_id if asset_id == 'leap-day' else asset_id.split('-', 1)[1]


def season_months(subject: str, southern: bool) -> tuple[int, ...]:
    months = SEASONS.get(subject, ())
    return tuple((month+5) % 12 + 1 for month in months) if southern else months


def seasonal_order(order, rng, southern: bool) -> list[str]:
    """Give seasonal drawings a day in their months, spread apart, and fill the
    remaining days with the other drawings in their shuffled order."""
    days = [None]*len(order)
    for asset_id in order:
        months = season_months(subject_of(asset_id), southern)
        if not months:
            continue
        free = [day for day, month in enumerate(MONTH_OF_DAY) if month in months and days[day] is None]
        same = [day for day, other in enumerate(days) if other and subject_of(other) == subject_of(asset_id)]
        distance = {day: min((abs(day-other) for other in same), default=len(order)) for day in free}
        # Prefer a week between repeats; settle for the widest gap when crowded.
        spacing = min(7, max(distance.values()))
        days[rng.choice([day for day in free if distance[day] >= spacing])] = asset_id
    rest = iter(asset_id for asset_id in order if not SEASONS.get(subject_of(asset_id)))
    return [asset_id or next(rest) for asset_id in days]


def annual_selection(rng) -> list[str]:
    """Choose the 365 drawings of one year by subject quota and rarity."""
    groups = {}
    for asset_id in pool():
        groups.setdefault(subject_of(asset_id), []).append(asset_id)
    chosen = [rng.choice(groups[subject]) for subject in RARE if rng.random() < .5]
    for subject, ids in groups.items():
        if subject not in RARE:
            chosen += rng.sample(ids, QUOTAS.get(subject, len(ids)))
    spare = [asset_id for subject in FILLERS for asset_id in groups[subject] if asset_id not in chosen]
    return chosen+rng.sample(spare, 365-len(chosen))


@lru_cache(maxsize=128)
def order_for_year(year: int, seed: str, southern: bool = False) -> tuple[str, ...]:
    digest = hashlib.sha256(f'annual-garden:v2:{year}:{seed}'.encode()).digest()
    rng = random.Random(int.from_bytes(digest,'big'))
    order = annual_selection(rng)
    rng.shuffle(order)
    order = seasonal_order(order, rng, southern)
    if calendar.isleap(year):
        order.insert(59,'leap-day')
    return tuple(order)


CANOPY_SUBJECTS = frozenset(('tree','pine','palm','bush','fern','seaweed','bamboo','vine','rosemary','twig',
    'foxtail','blossom'))
ACCENT_SUBJECTS = frozenset(('apple','pumpkin','fig','onion','acorn','cherry','banana','grapes','raspberry',
    'mushroom','ladybug','bee','butterfly','snail','fish','frog','mouse','hedgehog','tortoise','worm',
    'bird','cow','rainbow','house','camp','log','stones','honeycomb','watermelon',
    'tomato','peapod','persimmon','gourd','dragonfly','rabbit','squirrel','cat','ant','mole','scarecrow',
    'birdhouse','flowerpot','wheelbarrow','beehive','pinwheel','boots','maple'))
SMALL_SUBJECTS = frozenset(('sprout','clover','bell','droop','tulip','shamrock','luckyclover','snowflake'))


# Height range in rows and width cap for each size role.
ROLES = {'canopy': ((1.23, 1.43), 88), 'accent': ((.87, 1.05), 72),
         'small': ((.96, 1.17), 70), 'flower': ((1.08, 1.30), 82)}


def role_of(subject: str) -> str:
    if subject in CANOPY_SUBJECTS:
        return 'canopy'
    if subject in ACCENT_SUBJECTS:
        return 'accent'
    if subject in SMALL_SUBJECTS:
        return 'small'
    return 'flower'


def plant_size(subject: str, rng, row_height: float):
    """Size by visual mass: tall foliage, smaller round accents, mixed flowers."""
    role = role_of(subject)
    (low, high), cap = ROLES[role]
    return rng.uniform(low, high)*row_height, cap, role


# A drawing grown for one day: the library drawing it stands in for, plus the
# seed of its own hand. The library drawing is the fallback when no hand passes.
HAND_ATTEMPTS = 12
# Bump when a drawer, the hand frame or the fit test changes: the day's drawing
# changes with it, so the cached hands of the old revision are discarded.
HANDS_REVISION = 1
# Set by the server to its data directory. Without it hands are drawn in memory.
HANDS_CACHE: Path | None = None
# Built and standing things lean very little; plants and creatures lean more.
UPRIGHT_SUBJECTS = frozenset(('house', 'well', 'signpost', 'gate', 'camp', 'log', 'stump', 'stones', 'wateringcan',
    'spade', 'rake', 'scarecrow', 'birdhouse', 'flowerpot', 'wheelbarrow', 'beehive', 'boots', 'honeycomb'))
ROW_HEIGHT = (GRID[3]-GRID[1])/15


def hand_key(year: int, seed: str, asset_id: str) -> str:
    if asset_id == 'leap-day':
        return asset_id
    token = hashlib.sha256(f'garden-hand:v1:{year}:{seed}:{asset_id}'.encode()).hexdigest()[:16]
    return f'{asset_id}~{year}-{token}'


def configure_hands_cache(path) -> None:
    global HANDS_CACHE
    HANDS_CACHE = Path(path)


def hand_file(key: str) -> Path | None:
    if HANDS_CACHE is None:
        return None
    return HANDS_CACHE / f'r{HANDS_REVISION}' / f"{key.split('~', 1)[1]}.png"


@lru_cache(maxsize=1)
def addition_designs() -> dict[str, int]:
    """Which of its two designs (A or B) each original addition uses."""
    return {item['id']: 'AB'.index(item['variant']) for item in manifest().get('additions', ())}


def ink_metrics(mask: Image.Image, subject: str) -> tuple[float, float, float]:
    """Darkness as the board shows it: the blurred peak and the mean ink at the
    subject's typical size, plus the drawing's width-to-height ratio."""
    (low, high), cap = ROLES[role_of(subject)]
    crop = mask.crop(mask.getbbox())
    height = (low+high)/2*ROW_HEIGHT
    width = height*crop.width/crop.height
    if width > cap:
        height, width = height*cap/width, cap
    small = crop.resize((max(1, round(width)), max(1, round(height))), Image.Resampling.LANCZOS)
    padded = Image.new('L', (small.width+24, small.height+24), 0)
    padded.paste(small, (12, 12))
    peak = padded.filter(ImageFilter.GaussianBlur(6)).getextrema()[1]
    return peak, ImageStat.Stat(small).mean[0], crop.width/crop.height


@lru_cache(maxsize=256)
def subject_band(subject: str):
    """What the library's own drawings of this subject span, with a little room.
    Where the library holds near-copies, keep at least a modest band around
    their mean so a genuinely new hand can still pass."""
    values = [ink_metrics(asset_mask(asset_id), subject) for asset_id in pool() if subject_of(asset_id) == subject]
    band = []
    for column, room, floor in zip(zip(*values), (.06, .12, .12), (.10, .15, .15)):
        mean = sum(column)/len(column)
        band.append((min(min(column)*(1-room), mean*(1-floor)), max(max(column)*(1+room), mean*(1+floor))))
    return tuple(band)


def hand_fits(mask: Image.Image, subject: str) -> bool:
    box = mask.getbbox()
    if not box or box[0] < 2 or box[1] < 2 or box[2] > mask.width-2 or box[3] > mask.height-2:
        return False
    return all(low <= value <= high for value, (low, high) in zip(ink_metrics(mask, subject), subject_band(subject)))


def hand_mask(key: str) -> tuple[Image.Image, int | None]:
    """The day's own drawing and the attempt that passed: -1 for the library
    fallback, None when it came from the cache."""
    path = hand_file(key)
    if path is not None and path.is_file():
        try:
            with Image.open(path) as cached:
                if cached.mode == 'L' and cached.size == (200, 240):
                    return cached.copy(), None
        except OSError:
            pass  # A damaged file is drawn again and replaced.
    mask, attempt = draw_hand_mask(key)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f'{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp')
        mask.save(temporary, 'PNG')
        os.replace(temporary, path)
    return mask, attempt


def draw_hand_mask(key: str) -> tuple[Image.Image, int]:
    asset_id, token = key.split('~', 1)
    subject = subject_of(asset_id)
    tilt = 2 if subject in UPRIGHT_SUBJECTS else 4 if role_of(subject) == 'accent' else 7
    design = addition_designs().get(asset_id)
    for attempt in range(HAND_ATTEMPTS):
        digest = hashlib.sha256(f'{token}:{attempt}'.encode()).digest()
        rng = random.Random(int.from_bytes(digest, 'big'))
        mask = garden_drawings.draw_hand(subject, rng, tilt, design).mask()
        if hand_fits(mask, subject):
            return mask, attempt
    return asset_mask(asset_id), -1


def warm_hands(year: int, seed: str, budget: int = 40) -> bool:
    """Draw up to budget of a year's missing hands into the cache, so a render
    never has to draw the whole year while a device waits. True when complete.
    The hemisphere only reorders the year, so both share the same hands."""
    if HANDS_CACHE is None:
        return True
    for asset_id in order_for_year(year, seed):
        key = hand_key(year, seed, asset_id)
        path = hand_file(key)
        if path is None or path.is_file():
            continue
        if budget <= 0:
            return False
        hand_mask(key)
        budget -= 1
    return True


def prune_hands(keep_from_year: int) -> None:
    """Remove hands of an older revision or of years before keep_from_year."""
    if HANDS_CACHE is None or not HANDS_CACHE.is_dir():
        return
    current = f'r{HANDS_REVISION}'
    for folder in HANDS_CACHE.iterdir():
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            year = path.name.split('-', 1)[0]
            if folder.name != current or not year.isdigit() or int(year) < keep_from_year:
                path.unlink(missing_ok=True)
        if folder.name != current:
            try:
                folder.rmdir()
            except OSError:
                pass


@lru_cache(maxsize=16384)
def silhouette_rows(asset_id: str, width: int, height: int):
    """Protect the whole drawing, including white interiors and open branches.

    Fill the span between the outermost ink pixels on each scanline. Unlike a
    bounding rectangle this retains the narrower stem and concave sides, while
    preventing another plant from entering a flower, rainbow or bamboo clump.
    Include antialiasing and the future seed.
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


def row_counts(days: int, year: int, seed: str) -> list[int]:
    """Spread the year over equally full rows so the finished garden fills the
    page: 365 days become ten rows of 24 and five of 25. Each garden and year
    picks its own longer rows, so they form no pattern."""
    rows=math.ceil(days/COLUMNS)
    base,extra=divmod(days,rows)
    rng=random.Random(hashlib.sha256(f'rows:v1:{year}:{seed}'.encode()).digest())
    longer=set(rng.sample(range(rows),extra))
    return [base+(row in longer) for row in range(rows)]


@lru_cache(maxsize=32)
def planned_slots(year: int, seed: str, southern: bool = False):
    """Compose the whole year once; daily growth never moves existing plants.

    Unequal widths drive horizontal positions. Small groups sit closer together
    with wider pockets between them, and their baselines rise and fall.
    Silhouette-aware placement forbids overlaps, including white interiors.
    """
    order = tuple(hand_key(year, seed, asset_id) for asset_id in order_for_year(year, seed, southern))
    left,top,right,bottom = GRID
    counts=row_counts(len(order),year,seed)
    sy=(bottom-top)/len(counts)
    rng=random.Random(hashlib.sha256(f'positions:v3:{year}:{seed}'.encode()).digest())
    occupied=[0]*SIZE[1]
    anchors=[]
    for row,count in enumerate(counts):
        start=sum(counts[:row])
        row_order=order[start:start+count]
        plants=[]; gaps=[]; group_remaining=0; phase=rng.uniform(0,math.tau)
        for column,asset_id in enumerate(row_order):
            bounds=asset_mask(asset_id).getbbox()
            subject=subject_of(asset_id)
            height,cap,role=plant_size(subject,rng,sy)
            width=height*(bounds[2]-bounds[0])/(bounds[3]-bounds[1])
            if width>cap:height*=cap/width;width=cap
            plants.append({'index':start+column,'row':row,'asset_id':asset_id,'bounds':bounds,
                           'width':width,'height':height,'role':role})
            if column:
                # Short, irregular clusters, with pockets that do not form
                # continuous vertical channels through the garden.
                gaps.append(rng.uniform(13,21) if group_remaining==0 else rng.uniform(2,5))
            if group_remaining==0:group_remaining=rng.randint(3,5)
            group_remaining-=1
        margins=rng.uniform(OUTLINE_GAP+1,12)
        available=right-left-margins*2
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


def garden_slots(year: int, seed: str, southern: bool = False):
    # Do not expose the cached dictionaries for mutation by callers.
    return (dict(slot) for slot in planned_slots(year,seed,southern))


def paste_drawing(image, asset_id, bounds, x, y, w, h):
    mask=asset_mask(asset_id).crop(bounds).resize((w,h),Image.Resampling.LANCZOS)
    image.paste(INK,(x,y,x+w,y+h),mask)


def draw_today(image, draw, asset_id):
    """Feature the drawing that grew today at header scale, with its name."""
    bounds=asset_mask(asset_id).getbbox()
    width,height=bounds[2]-bounds[0],bounds[3]-bounds[1]
    scale=min(TODAY_HEIGHT/height,TODAY_WIDTH/width)
    w,h=round(width*scale),round(height*scale)
    x,y=TODAY_RIGHT-w,TODAY_BOTTOM-h
    paste_drawing(image,asset_id,bounds,x,y,w,h)
    hand_text(draw,(x-24,46),'今日',28,'rt',ink=SECONDARY_INK)
    hand_text(draw,(x-24,84),SUBJECT_NAMES[subject_of(asset_id)],40,'rt')


def draw_annual_garden(now, seed: str, *, full: bool = False, southern: bool = False) -> Image.Image:
    ordinal,total=day_counts(now)
    image=Image.new('L',SIZE,PAPER)
    draw=ImageDraw.Draw(image)
    slots=list(garden_slots(now.year,seed,southern))
    hand_text(draw,(54,40),f'{now.month}月{now.day}日 · 周{WEEKDAYS[now.weekday()]}',48)
    hand_text(draw,(58,100),f'{now.year} · 第 {ordinal} 天 · 还剩 {total-ordinal} 天 · 已过 {ordinal/total*100:.1f}%',
              30,ink=SECONDARY_INK)
    draw_today(image,draw,slots[ordinal-1]['asset_id'])

    grown=total if full else ordinal
    # Each future seed has space reserved by the annual plan.
    for slot in slots[grown:]:
        cx,cy=slot['seed_x'],slot['seed_y']
        draw.ellipse((cx-2,cy-2,cx+2,cy+2),fill=SEED_INK)
    for slot in slots[:grown]:
        paste_drawing(image,slot['asset_id'],slot['bounds'],slot['x'],slot['y'],slot['width'],slot['height'])
    return image
