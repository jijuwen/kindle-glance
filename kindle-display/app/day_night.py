"""Native gray world clock: geographic night mask with a thin smoked-glass rim.

Original rendering, no Apple/TRMNL artwork. Natural Earth land is public domain.
Solar model: NOAA General Solar Position Calculations (approximate, not navigation).
"""
from __future__ import annotations

import calendar
import json
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from app.display_context import preferences, temperature_unit, clock
from PIL import Image, ImageChops, ImageDraw

from app.hourly_weather import HourlyCanvas
from app.ink_palette import INK_PRIMARY, INK_SECONDARY, PAPER_WHITE

SIZE = (1648, 1236)
MAP_LEFT, MAP_TOP, MAP_WIDTH = 60, 120, 1528
NORTH, SOUTH = 83, -60
SPACING = 19
RENDER_REVISION = "paper-hierarchy-3"
NIGHT_DOT = 34


def miller(latitude):
    return 1.25 * math.log(math.tan(math.pi / 4 + .4 * math.radians(latitude)))


MAP_SCALE = MAP_WIDTH / math.tau
MAP_HEIGHT = round((miller(NORTH) - miller(SOUTH)) * MAP_SCALE)


def project(longitude, latitude):
    return ((longitude + 180) / 360 * MAP_WIDTH,
            (miller(NORTH) - miller(latitude)) * MAP_SCALE)


def unproject(x, y):
    latitude = math.degrees((math.atan(math.exp((miller(NORTH) - y / MAP_SCALE) / 1.25))
                             - math.pi / 4) / .4)
    return x / MAP_WIDTH * 360 - 180, latitude


def solar_parameters(now):
    """Return declination radians and equation of time minutes, independent of TZ."""
    if now.tzinfo is None:
        raise ValueError("An aware timestamp is required")
    utc = now.astimezone(timezone.utc)
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = math.tau / (366 if calendar.isleap(utc.year) else 365) * (
        utc.timetuple().tm_yday - 1 + (hour - 12) / 24)
    eq = 229.18 * (.000075 + .001868 * math.cos(gamma) - .032077 * math.sin(gamma)
                  - .014615 * math.cos(2 * gamma) - .040849 * math.sin(2 * gamma))
    dec = (.006918 - .399912 * math.cos(gamma) + .070257 * math.sin(gamma)
           - .006758 * math.cos(2 * gamma) + .000907 * math.sin(2 * gamma)
           - .002697 * math.cos(3 * gamma) + .00148 * math.sin(3 * gamma))
    return dec, eq


def sun_position(now):
    dec, eq = solar_parameters(now)
    utc = now.astimezone(timezone.utc)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    longitude = ((720 - minutes - eq) / 4 + 180) % 360 - 180
    return math.degrees(dec), longitude


def solar_dot(latitude, longitude, solar_latitude, solar_longitude):
    lat, dec = math.radians(latitude), math.radians(solar_latitude)
    return (math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec)
            * math.cos(math.radians(longitude - solar_longitude)))


def sun_times(now, latitude, longitude):
    """Approximate local-date sunrise/sunset; explicitly represent polar days."""
    local_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    lat = math.radians(max(-89.999, min(89.999, latitude)))

    def crossing(stamp):
        dec, eq = solar_parameters(stamp)
        cosine = (math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(dec))
                  - math.tan(lat) * math.tan(dec))
        return cosine, eq

    cosine, eq = crossing(local_noon)
    if cosine < -1:
        return {"rise": None, "set": None, "minutes": 1440, "polar": "极昼"}
    if cosine > 1:
        return {"rise": None, "set": None, "minutes": 0, "polar": "极夜"}
    angle = math.degrees(math.acos(cosine))
    transit = (midnight + timedelta(minutes=720 - 4 * longitude - eq)).astimezone(now.tzinfo)
    midnight += timedelta(days=(now.date() - transit.date()).days)
    events = []
    for sign in (-1, 1):
        stamp = midnight + timedelta(minutes=720 - 4 * longitude - eq + sign * 4 * angle)
        for _ in range(2):
            c, e = crossing(stamp)
            a = math.degrees(math.acos(max(-1, min(1, c))))
            stamp = midnight + timedelta(minutes=720 - 4 * longitude - e + sign * 4 * a)
        events.append(stamp.astimezone(now.tzinfo))
    return {"rise": events[0], "set": events[1],
            "minutes": round((events[1] - events[0]).total_seconds() / 60), "polar": None}


@lru_cache(maxsize=1)
def land_points():
    """Sample a regular screen grid through real land polygons (including holes)."""
    data = json.loads((Path(__file__).parent / "assets/natural-earth/ne_110m_land.geojson").read_text())
    mask = Image.new("L", (MAP_WIDTH + 1, MAP_HEIGHT + 1))
    draw = ImageDraw.Draw(mask)
    for feature in data["features"]:
        geom = feature["geometry"]
        polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for polygon in polygons:
            for index, ring in enumerate(polygon):
                points = [project(lon, max(-89.99, min(89.99, lat))) for lon, lat in ring]
                draw.polygon(points, fill=255 if index == 0 else 0)
    return tuple((x, y, *unproject(x, y))
                 for y in range(SPACING // 2, MAP_HEIGHT, SPACING)
                 for x in range(SPACING // 2, MAP_WIDTH, SPACING)
                 if mask.getpixel((x, y)) > 127)


def smoothstep(low, high, value):
    t = max(0., min(1., (value - low) / (high - low)))
    return t * t * (3 - 2 * t)


def glass_fields(solar_latitude, solar_longitude):
    """Signed screen-distance rim; no longitude polyline or dateline join seams.

    Computing the implicit terminator also handles equinox and polar crossings.
    The material edge fades at the map's open crop, never drawing a card border.
    """
    width, height = MAP_WIDTH, MAP_HEIGHT
    background, highlights = bytearray(width * height), bytearray(width * height)
    dec = math.radians(solar_latitude)
    sd, cd = math.sin(dec), math.cos(dec)
    angles = [math.radians(unproject(x, 0)[0] - solar_longitude) for x in range(width)]
    cosines, sines = [math.cos(a) for a in angles], [math.sin(a) for a in angles]
    for y in range(height):
        lat = math.radians(unproject(0, y)[1])
        sl, cl = math.sin(lat), math.cos(lat)
        dlat_dy = -math.cos(.8 * lat) / MAP_SCALE
        vertical_fade = smoothstep(0, 40, min(y, height - 1 - y))
        for x in range(width):
            q = sl * sd + cl * cd * cosines[x]
            dx = -cl * cd * sines[x] / MAP_SCALE
            dy = (cl * sd - sl * cd * cosines[x]) * dlat_dy
            gradient = max(.00001, math.hypot(dx, dy))
            distance = q / gradient
            night = 1 - smoothstep(-5, 5, distance)
            # Keep the night sheet light enough for the land pattern to lead, while
            # retaining a narrow dark contact edge and a white inner highlight.
            shade = 6 * math.exp(-((distance + 7) / 6) ** 2) if abs(distance) < 35 else 0
            index = y * width + x
            cut = 60 * math.exp(-((distance - 1.7) / 1.35) ** 2) if abs(distance) < 26 else 0
            background[index] = round(PAPER_WHITE - 51 * night - shade - cut)
            if abs(distance) < 26:
                lighting = .52 + .48 * max(0, (-dx * .45 - dy * .89) / gradient)
                fade = vertical_fade * smoothstep(0, 25, min(x, width - 1 - x))
                # White highlight sits inside the gray sheet, not on white paper.
                highlights[index] = round(.85 * math.exp(-((distance + 2.2) / 1.65) ** 2)
                                          * (.78 + .22 * lighting) * fade * 255)
    return (Image.frombytes("L", (width, height), bytes(background)),
            Image.frombytes("L", (width, height), bytes(highlights)))


def draw_day_night(now, font, latitude=24.4798, longitude=118.0894, city=""):
    ground = PAPER_WHITE
    solar_lat, solar_lon = sun_position(now)
    background, highlights = glass_fields(solar_lat, solar_lon)
    scale = 2
    world = background.resize((MAP_WIDTH * scale, MAP_HEIGHT * scale), Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(world)
    radius = 4.9 * scale
    for x, y, lon, lat in land_points():
        q = solar_dot(lat, lon, solar_lat, solar_lon)
        brightness = round(NIGHT_DOT - NIGHT_DOT * smoothstep(-.035, .035, q))
        cx, cy = x * scale, y * scale
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=brightness)
    rim = highlights.resize(world.size, Image.Resampling.BICUBIC)
    world = Image.composite(Image.new("L", world.size, PAPER_WHITE), world, rim)
    # Feather only the open map crop into the canvas; no visible rectangle.
    fade = Image.new("L", (MAP_WIDTH, MAP_HEIGHT))
    fd = ImageDraw.Draw(fade)
    for y in range(MAP_HEIGHT):
        fd.line((0, y, MAP_WIDTH, y), fill=round(255 * smoothstep(0, 32, min(y, MAP_HEIGHT - 1 - y))))
    horizontal = Image.new("L", fade.size)
    hd = ImageDraw.Draw(horizontal)
    for x in range(MAP_WIDTH):
        hd.line((x, 0, x, MAP_HEIGHT), fill=round(255 * smoothstep(0, 24, min(x, MAP_WIDTH - 1 - x))))
    fade = ImageChops.multiply(fade, horizontal)

    canvas = HourlyCanvas(font)
    canvas.image.paste(ground, (0, 0, SIZE[0] * scale, SIZE[1] * scale))
    canvas.image.paste(world, (MAP_LEFT * scale, MAP_TOP * scale),
                       fade.resize(world.size, Image.Resampling.BICUBIC))
    if SOUTH <= latitude <= NORTH and -180 <= longitude <= 180:
        x, y = project(longitude, latitude)
        x, y = (x + MAP_LEFT) * scale, (y + MAP_TOP) * scale
        # A generous white halo keeps the location legible over both materials.
        canvas.draw.ellipse((x - 20, y - 20, x + 20, y + 20),
                            fill=ground, outline=INK_PRIMARY, width=4)
        canvas.draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=INK_PRIMARY)

    # Two aligned rows form one calm information band.  White space—not a rule or
    # legend—separates it from the self-explanatory world field.
    canvas.text(72, 1000, f"{now.month}月{now.day}日", 72, fill=INK_PRIMARY)
    canvas.text(77, 1108, f"{now.year}  ·  周{'一二三四五六日'[now.weekday()]}",
                30, fill=INK_SECONDARY)

    times = sun_times(now, latitude, longitude)
    if times["polar"]:
        detail = f"{times['polar']}  ·  {'太阳不落' if times['polar'] == '极昼' else '太阳不升'}"
    else:
        # Round to the nearest minute rather than silently truncating seconds.
        rise = clock(times["rise"] + timedelta(seconds=30))
        setting = clock(times["set"] + timedelta(seconds=30))
        detail = f"日出 {rise}   ·   日落 {setting}"
    primary = f"{city}  ·  {detail}"
    canvas.text(1570, 1028, primary, 34, fill=INK_PRIMARY, align="right", limit=840)
    minutes = times["minutes"]
    utc_offset = clock(now, "%z")
    secondary = (f"昼长 {minutes // 60}小时{minutes % 60:02d}分"
                 f"  ·  更新 {clock(now)}  ·  UTC{utc_offset[:3]}:{utc_offset[3:]}")
    canvas.text(1570, 1109, secondary, 28, fill=INK_SECONDARY,
                align="right", limit=840)
    return canvas.finish()
