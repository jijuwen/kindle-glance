"""Original Kindle-native layouts inspired by Simple Calendar / Weather Glance.

No TRMNL template source or preview bitmap is embedded. Canvas: 1648 x 1236.
"""
from __future__ import annotations

import calendar
import math
from datetime import datetime, timedelta

from app.display_context import preferences, temperature_unit, clock
from PIL import Image, ImageDraw
from app.ink_palette import (INK_MUTED, INK_PRIMARY, INK_SECONDARY,
                             INK_TERTIARY, PAPER_WHITE, SURFACE_LIGHT)
from app.weather_overview import icon_name, icon_tile, parse_time, number

SIZE = (1648, 1236)
WEEKDAYS = '一二三四五六日'


class Canvas:
    def __init__(self, font):
        self.image = Image.new('L', SIZE, PAPER_WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.font = font

    def text(self, x, y, value, size, bold=False, fill=INK_PRIMARY, align='center', limit=None):
        value = str(value)
        while True:
            face = self.font(size, bold)
            box = self.draw.textbbox((0, 0), value, font=face)
            width = box[2] - box[0]
            if not limit or width <= limit or size <= 18:
                break
            size -= 1
        left = x - (width / 2 if align == 'center' else width if align == 'right' else 0)
        self.draw.text((round(left)-box[0], round(y)-box[1]), value, font=face, fill=fill)

    def capsule(self, box, radius, fill):
        x1, y1, x2, y2 = map(round, box)
        size = (max(1, x2-x1), max(1, y2-y1))
        scale = 3
        mask = Image.new('L', (size[0]*scale, size[1]*scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width-1, mask.height-1), radius=radius*scale, fill=255)
        mask = mask.resize(size, Image.Resampling.LANCZOS)
        self.image.paste(fill, (x1, y1, x2, y2), mask)

    def icon(self, code, x, y, width=66, height=66, is_day=True):
        tile = icon_tile(icon_name(code, is_day), width, height)
        self.image.paste(INK_PRIMARY, (round(x-tile.width/2), round(y+(height-tile.height)/2)), tile)

    def footer(self, title, right):
        self.capsule((36, 1120, 1612, 1198), radius=39, fill=SURFACE_LIGHT)
        self.text(82, 1142, title, 31, True, align='left')
        self.text(1565, 1142, right, 28, True, fill=INK_SECONDARY, align='right', limit=510)


def month_grid(now):
    return calendar.Calendar(firstweekday=preferences.get().get("week_start", 6)).monthdayscalendar(now.year, now.month)


def draw_calendar(now, font):
    canvas = Canvas(font)
    rows = month_grid(now)
    left, column = 148, 1352 / 7
    for col, label in enumerate('日一二三四五六' if preferences.get().get('week_start', 6) == 6 else WEEKDAYS):
        canvas.text(left+column*(col+.5), 101, label, 32, True,
                    fill=INK_TERTIARY if col == 0 else INK_SECONDARY)
    # Five- and six-week months use the same content area, without shrinking text.
    row_height = min(176, 858 / len(rows))
    top = 207 + (858 - row_height * len(rows)) / 2
    for row, days in enumerate(rows):
        for col, day in enumerate(days):
            if not day:
                continue
            x, y = left+column*(col+.5), top+row_height*(row+.5)
            selected = day == now.day
            if selected:
                canvas.draw.rounded_rectangle((round(x-72),round(y-66),round(x+72),round(y+66)),
                                              radius=38, fill=INK_PRIMARY)
            canvas.text(x, y-44, day, 100, True,
                        fill=PAPER_WHITE if selected else INK_MUTED if col == 0 else INK_PRIMARY)
    canvas.footer('月历', f'{now.year}年{now.month}月')
    return canvas.image


def seven_days(weather, now):
    lookup = {day.get('date'): day for day in weather.get('forecast', [])}
    return [(date, lookup.get(date.isoformat(), {}))
            for date in (now.date()+timedelta(days=i) for i in range(7))]


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def temperature_extent(days, current):
    values = [item.get(key) for _, item in days for key in ('low','high') if numeric(item.get(key))]
    if numeric(current):
        values.append(current)
    if not values:
        return 0, 10
    low, high = min(values), max(values)
    padding = max(2, (high-low)*.12)
    return low-padding, high+padding


def weather_gray(code):
    """Four solid 16-step-compatible grays; darker groups denote rougher weather."""
    if code in {65,75,82,86,95,96,99}:
        return 153
    if code in {51,53,55,56,57,61,63,66,67,71,73,77,80,81,85}:
        return 187
    if code in {0,1}:
        return 238
    return 221


def draw_weather_glance(weather, now, font, city=''):
    canvas = Canvas(font)
    days = seven_days(weather, now)
    current = weather.get('temperature')
    minimum, maximum = temperature_extent(days, current)
    def position(value):
        return 940 - (value-minimum)/(maximum-minimum)*560
    cy = min(840, max(440, position(current))) if numeric(current) else 630
    value = f'{number(current)}{temperature_unit()}' if numeric(current) else '--'
    canvas.text(215, cy-72, value, 148, limit=322)
    canvas.text(215, cy+100, '当前温度', 32, True, fill=INK_SECONDARY)
    observed = parse_time(weather.get('observed_at'), now)
    if observed:
        stamp = clock(observed, '%H:%M') if observed.date()==now.date() else clock(observed, '%m月%d日 %H:%M')
        caption = ('缓存 ' if weather.get('_stale') or observed.date()!=now.date() else '数据 ') + stamp
    else:
        caption = '暂无天气数据'
    canvas.text(215, cy+155, caption, 26, fill=INK_TERTIARY, limit=320)
    canvas.draw.line((381, round(cy+12), 426, round(cy+12)), fill=INK_PRIMARY, width=3)
    canvas.draw.polygon(((426,round(cy+12)),(416,round(cy+5)),(416,round(cy+19))), fill=INK_PRIMARY)
    start, column = 460, 1128/7
    for index, (day, forecast) in enumerate(days):
        x = start+column*(index+.5)
        canvas.text(x, 113, '今天' if index==0 else '周'+WEEKDAYS[day.weekday()], 34, True)
        canvas.text(x, 168, f'{day.month}/{day.day}', 30, fill=INK_SECONDARY)
        high, low = forecast.get('high'), forecast.get('low')
        if not numeric(high) or not numeric(low) or high < low:
            canvas.text(x, 580, '--', 43, True, fill=INK_TERTIARY)
            canvas.text(x, 643, '暂无', 26, fill=INK_TERTIARY)
            continue
        upper, lower = position(high), position(low)
        lower = max(lower, upper+106)
        top, bottom = upper-98, lower+53
        code = forecast.get('code')
        canvas.capsule((x-60, top, x+60, bottom), radius=60, fill=weather_gray(code))
        canvas.icon(code, x, top+24, 65, 58)
        canvas.text(x, upper+1, number(high), 43, True)
        canvas.text(x, lower+1, number(low), 39, True)
    canvas.footer('天气', city)
    return canvas.image
