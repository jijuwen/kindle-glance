"""Kindle-native hourly weather layout inspired by TRMNL recipe 35788.

No TRMNL source, bitmap, font, or icon asset is embedded. Canvas: 1648 x 1236.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.display_context import preferences, temperature_unit, clock
from PIL import Image, ImageDraw

from app.ink_palette import (INK_PRIMARY, INK_SECONDARY, INK_TERTIARY,
                             PAPER_WHITE, PROGRESS_FUTURE, SURFACE_LIGHT)
from app.weather_overview import icon_name, icon_tile, parse_time


SIZE = (1648, 1236)
WEEKDAYS = "一二三四五六日"


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def hourly_slots(weather, now, count=5):
    """Return fixed whole-hour slots, retaining gaps and crossing midnight."""
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    lookup = {}
    for item in weather.get("hourly", []):
        stamp = parse_time(item.get("time"), now)
        if stamp:
            lookup[stamp] = item
    result = []
    for index in range(count):
        stamp = start + timedelta(hours=index)
        result.append({**lookup.get(stamp, {}), "stamp": stamp})
    return result


def wind_direction(value):
    if not numeric(value):
        return "风向--"
    names = ("北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风")
    return names[round(value / 45) % 8]


def smooth_separator_path(samples_per_segment=36):
    """Return a stable, gently imperfect Catmull-Rom stroke centerline."""
    knots = ((64, 479), (310, 486), (555, 501), (810, 504),
             (1065, 508), (1330, 516), (1584, 520))
    padded = (knots[0],) + knots + (knots[-1],)
    result = []
    for segment in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[segment - 1:segment + 3]
        for step in range(samples_per_segment):
            t = step / samples_per_segment
            t2, t3 = t * t, t * t * t
            x = .5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                      + (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2
                      + (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3)
            y = .5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                      + (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2
                      + (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3)
            progress = (segment - 1 + t) / (len(knots) - 1)
            # Coherent sub-pixel drift gives the line a drawn rather than plotted character.
            y += 1.15 * math.sin(progress * math.tau * 2.1 + .35)
            y += .45 * math.sin(progress * math.tau * 5.2 + 1.1)
            result.append((x, y))
    result.append(knots[-1])
    return result


class HourlyCanvas:
    """Two-times supersampled grayscale canvas for crisp E Ink output."""

    scale = 2

    def __init__(self, font):
        self.font = font
        self.image = Image.new("L", (SIZE[0] * self.scale, SIZE[1] * self.scale), PAPER_WHITE)
        self.draw = ImageDraw.Draw(self.image)

    def text(self, x, y, value, size, bold=False, fill=INK_PRIMARY, align="left", limit=None):
        value = str(value)
        while True:
            face = self.font(size * self.scale, bold)
            box = self.draw.textbbox((0, 0), value, font=face)
            width = (box[2] - box[0]) / self.scale
            if not limit or width <= limit or size <= 18:
                break
            size -= 1
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        self.draw.text(
            (round(x * self.scale) - box[0], round(y * self.scale) - box[1]),
            value,
            font=face,
            fill=fill,
        )

    def line(self, points, fill=INK_PRIMARY, width=3):
        self.draw.line(tuple(round(value * self.scale) for point in points for value in point),
                       fill=fill, width=width * self.scale, joint="curve")

    def handdrawn_separator(self):
        """Draw one smooth, deterministic stroke with subtly varying pressure."""
        path = smooth_separator_path()
        upper, lower = [], []
        last = len(path) - 1
        for index, (x, y) in enumerate(path):
            before = path[max(0, index - 1)]
            after = path[min(last, index + 1)]
            dx, dy = after[0] - before[0], after[1] - before[1]
            length = math.hypot(dx, dy) or 1
            nx, ny = -dy / length, dx / length
            progress = index / last
            half = 2.7 + .42 * math.sin(progress * math.tau * 1.35 + .4)
            half += .18 * math.sin(progress * math.tau * 4.4)
            upper.append(((x + nx * half) * self.scale, (y + ny * half) * self.scale))
            lower.append(((x - nx * half) * self.scale, (y - ny * half) * self.scale))
        polygon = [(round(x), round(y)) for x, y in upper + list(reversed(lower))]
        self.draw.polygon(polygon, fill=INK_SECONDARY)
        for x, y in (path[0], path[-1]):
            radius = 2.7 * self.scale
            cx, cy = x * self.scale, y * self.scale
            self.draw.ellipse((round(cx-radius), round(cy-radius), round(cx+radius), round(cy+radius)),
                              fill=INK_SECONDARY)

    def capsule(self, box, radius, fill):
        self.draw.rounded_rectangle(
            tuple(round(value * self.scale) for value in box),
            radius=round(radius * self.scale),
            fill=fill,
        )

    def icon(self, code, is_day, x, y, width, height):
        tile = icon_tile(icon_name(code, is_day), width * self.scale, height * self.scale)
        left = round((x + (width - tile.width / self.scale) / 2) * self.scale)
        top = round((y + (height - tile.height / self.scale) / 2) * self.scale)
        self.image.paste(INK_PRIMARY, (left, top), tile)

    def finish(self):
        return self.image.resize(SIZE, Image.Resampling.LANCZOS)


def value_with_unit(value, unit):
    return f"{round(value)}{unit}" if numeric(value) else "--"


def slot_time(stamp, now):
    prefix = "明日 " if stamp.date() > now.date() else ""
    return prefix + (clock(stamp) if preferences.get().get("hour_format") == "12" else f"{stamp.hour:02d}时")


def draw_hourly_weather(weather, now, font, city=""):
    canvas = HourlyCanvas(font)

    canvas.text(305, 51, f"{now.month}月{now.day}日  周{WEEKDAYS[now.weekday()]}", 39, True, align="center")
    canvas.icon(weather.get("code"), weather.get("is_day") is not False, 86, 142, 180, 160)
    canvas.text(310, 128, value_with_unit(weather.get("temperature"), temperature_unit()), 162, limit=430)
    canvas.text(310, 330, weather.get("label") or "天气暂不可用", 34, True, limit=350)
    observed = parse_time(weather.get("observed_at"), now)
    if observed:
        label = "缓存" if weather.get("_stale") else "数据"
        stamp = clock(observed, "%H:%M") if observed.date() == now.date() else clock(observed, "%m月%d日 %H:%M")
        canvas.text(310, 383, f"{label} {stamp}", 26, fill=INK_TERTIARY, limit=350)

    metrics = (
        ("体感", weather.get("apparent"), temperature_unit()),
        ("风速", weather.get("wind"), " km/h"),
        ("降雨", weather.get("rain_now"), "%"),
        ("阵风", weather.get("gust"), " km/h"),
    )
    for index, (label, value, unit) in enumerate(metrics):
        column, row = index % 2, index // 2
        x, y = 790 + column * 392, 80 + row * 183
        canvas.capsule((x, y, x + 12, y + 133), 6, PROGRESS_FUTURE)
        canvas.text(x + 36, y + 10, value_with_unit(value, unit), 48, True, limit=310)
        detail = wind_direction(weather.get("wind_direction")) if label == "风速" else label
        canvas.text(x + 36, y + 76, detail, 27, True, fill=INK_SECONDARY, limit=310)

    canvas.handdrawn_separator()

    slots = hourly_slots(weather, now)
    left, right = 64, 1584
    width = (right - left) / len(slots)
    for index, item in enumerate(slots):
        x = left + index * width
        center = x + width / 2
        if index:
            canvas.capsule((x - 6, 590, x + 6, 1077), 6, PROGRESS_FUTURE)
        canvas.text(center, 574, slot_time(item["stamp"], now), 31, True, align="center", limit=width - 34)
        canvas.icon(item.get("code"), item.get("is_day") is not False, center - 57, 649, 114, 94)
        canvas.text(center, 776, value_with_unit(item.get("temperature"), temperature_unit()), 56, True,
                    align="center", limit=width - 30)
        canvas.text(center, 856, f"体感 {value_with_unit(item.get('apparent'), '°')}", 28, True,
                    align="center", limit=width - 30)
        canvas.text(center, 925, f"降雨 {value_with_unit(item.get('rain'), '%')}", 28, True,
                    align="center", limit=width - 30)
        wind = value_with_unit(item.get("wind"), " km/h")
        canvas.text(center, 985, f"{wind_direction(item.get('wind_direction'))} {wind}", 27, True,
                    align="center", limit=width - 30)

    canvas.capsule((36, 1110, 1612, 1198), 44, SURFACE_LIGHT)
    canvas.text(82, 1135, "逐时天气", 31, True)
    canvas.text(1565, 1135, city, 29, True, fill=INK_SECONDARY, align="right", limit=470)
    return canvas.finish()
