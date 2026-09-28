"""Native Pillow weather brief using the OFL Weather Icons font."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from app.display_context import preferences, temperature_unit, clock
from PIL import Image, ImageDraw, ImageFont

from app.ink_palette import (INK_PRIMARY, INK_RULE, INK_RULE_LIGHT,
                             INK_SECONDARY, INK_TERTIARY, PAPER_WHITE)

ASSETS = Path(__file__).with_name('assets') / 'weather-icons'
WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
SNOW = {71, 73, 75, 77, 85, 86}


def number(value):
    return round(value) if isinstance(value, (int, float)) and math.isfinite(value) else '--'


def normalize_weather(payload, labels):
    current, daily, hourly = (payload.get(key) or {} for key in ('current', 'daily', 'hourly'))
    def at(group, name, index):
        values = group.get(name) or []
        return values[index] if index < len(values) else None
    forecast = []
    for i, day in enumerate(daily.get('time') or []):
        code = at(daily, 'weather_code', i)
        forecast.append(dict(date=day, code=code, label=labels.get(code, '暂无预报'),
            high=number(at(daily, 'temperature_2m_max', i)), low=number(at(daily, 'temperature_2m_min', i)),
            rain=number(at(daily, 'precipitation_probability_max', i))))
    hours = []
    for i, stamp in enumerate(hourly.get('time') or []):
        code = at(hourly, 'weather_code', i)
        hours.append(dict(time=stamp, code=code, label=labels.get(code, '暂无预报'),
            temperature=number(at(hourly, 'temperature_2m', i)),
            apparent=number(at(hourly, 'apparent_temperature', i)),
            rain=number(at(hourly, 'precipitation_probability', i)),
            wind=number(at(hourly, 'wind_speed_10m', i)),
            wind_direction=number(at(hourly, 'wind_direction_10m', i)),
            gust=number(at(hourly, 'wind_gusts_10m', i)), is_day=at(hourly, 'is_day', i)))
    today = forecast[0] if forecast else {}
    current_hour = str(current.get('time') or '')[:13]
    matching_hour = next((item for item in hours if str(item.get('time') or '')[:13] == current_hour), {})
    return dict(temperature=number(current.get('temperature_2m')), apparent=number(current.get('apparent_temperature')),
        label=labels.get(current.get('weather_code'), '天气暂不可用'), code=current.get('weather_code'),
        is_day=current.get('is_day'), observed_at=current.get('time'),
        wind=number(current.get('wind_speed_10m')), wind_direction=number(current.get('wind_direction_10m')),
        gust=number(current.get('wind_gusts_10m')), rain_now=matching_hour.get('rain', '--'),
        high=today.get('high', '--'), low=today.get('low', '--'), rain=today.get('rain', '--'),
        forecast=forecast, hourly=hours)


def parse_time(value, now):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.replace(tzinfo=now.tzinfo) if stamp.tzinfo is None else stamp.astimezone(now.tzinfo)
    except (TypeError, ValueError):
        return None


def upcoming_hours(weather, now):
    result = []
    for item in weather.get('hourly', []):
        stamp = parse_time(item.get('time'), now)
        if stamp and now < stamp <= now + timedelta(hours=12):
            result.append(dict(item, stamp=stamp))
    return sorted(result, key=lambda item: item['stamp'])


def hour_slots(weather, now):
    """Keep six fixed two-hour slots; do not compress gaps or include past hours."""
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    lookup = {item['stamp']: item for item in upcoming_hours(weather, now)}
    return [lookup.get(stamp, {'stamp': stamp}) for stamp in (start+timedelta(hours=i*2) for i in range(6))]


def future_days(weather, now):
    lookup = {item.get('date'): item for item in weather.get('forecast', [])}
    return [(day, lookup.get(day.isoformat(), {})) for day in (now.date()+timedelta(days=i) for i in (1, 2, 3))]


def weather_summary(weather, now):
    hours = upcoming_hours(weather, now)
    if any(item.get('code') in {95, 96, 99} for item in hours):
        return '未来时段可能有雷雨', '外出留意天气变化'
    if any(item.get('code') in SNOW for item in hours):
        return '未来时段可能降雪', '注意保暖与路面情况'
    wet = [item for item in hours if item.get('code') in WET or
        (isinstance(item.get('rain'), (int, float)) and item['rain'] >= 50)]
    if wet:
        stamp = wet[0]['stamp']
        if stamp.date() > now.date():
            period = '明晨' if stamp.hour < 12 else '明天'
        else:
            period = '凌晨' if stamp.hour < 6 else '上午' if stamp.hour < 12 else '午后' if stamp.hour < 18 else '今晚'
        return f'{period}可能有雨', '外出建议带伞'
    if not hours or not any(isinstance(item.get('code'), int) for item in hours):
        return '逐时预报暂不可用', '请稍后查看更新'
    probabilities = [item.get('rain') for item in hours]
    if len(hours) >= 10 and all(isinstance(p, (int, float)) and p < 30 for p in probabilities):
        return '未来时段降雨概率低', '可参考下方逐时预报'
    return '留意接下来的天气', '可参考下方逐时预报'


def icon_name(code, is_day=True):
    if code == 0:
        return 'day-sunny' if is_day is not False else 'night-clear'
    if code in {1, 2}:
        return 'day-cloudy' if is_day is not False else 'night-alt-cloudy'
    if code == 3: return 'cloudy'
    if code in {45, 48}: return 'fog'
    if code in {51, 53, 55}: return 'sprinkle'
    if code in {56, 57, 66, 67}: return 'rain-mix'
    if code in {61, 63, 65}: return 'rain'
    if code in SNOW: return 'snow'
    if code in {80, 81, 82}: return 'showers'
    if code == 95: return 'thunderstorm'
    if code in {96, 99}: return 'hail'
    return 'na'


@lru_cache(maxsize=64)
def icon_tile(name, width, height):
    glyphs = json.loads((ASSETS / 'glyphs.json').read_text())
    glyph = chr(int(glyphs[name], 16))
    f = ImageFont.truetype(str(ASSETS / 'weathericons.ttf'), 800)
    box = f.getbbox(glyph)
    mask = Image.new('L', (box[2]-box[0]+8, box[3]-box[1]+8), 0)
    ImageDraw.Draw(mask).text((4-box[0], 4-box[1]), glyph, font=f, fill=255)
    mask.thumbnail((width, height), Image.Resampling.LANCZOS)
    return mask


def draw_overview(width, height, weather, now, font_factory, city=''):
    scale = 2
    im = Image.new('L', (1648*scale, 1236*scale), PAPER_WHITE)
    draw = ImageDraw.Draw(im)
    def text(x, y, value, size, bold=False, align='left', max_width=None, fill=INK_PRIMARY):
        value = str(value)
        f = font_factory(size*scale, bold)
        box = draw.textbbox((0, 0), value, font=f)
        while max_width and box[2]-box[0] > max_width*scale and size > 18:
            size -= 1
            f = font_factory(size*scale, bold)
            box = draw.textbbox((0, 0), value, font=f)
        length = (box[2]-box[0])/scale
        if align == 'center': x -= length/2
        if align == 'right': x -= length
        draw.text((round(x*scale)-box[0], round(y*scale)-box[1]), value, font=f, fill=fill)
    def line(x1, y1, x2, y2, stroke=2, fill=INK_RULE):
        draw.line((x1*scale, y1*scale, x2*scale, y2*scale), fill=fill, width=stroke*scale)
    def icon(item, x, y, w, h):
        day = item.get('is_day')
        name = icon_name(item.get('code'), None if day is None else bool(day))
        tile = icon_tile(name, w*scale, h*scale)
        im.paste(INK_PRIMARY, (round(x*scale+(w*scale-tile.width)/2),
                              round(y*scale+(h*scale-tile.height)/2)), tile)
    def degrees(value): return f'{value}°' if value != '--' else '--'
    def percent(value): return f'{value}%' if value != '--' else '--'

    text(80,64,f'{city}天气 · {temperature_unit()}',45,True,max_width=550)
    text(1568,79,f'{now.year} 年 {now.month} 月 {now.day} 日  星期{"一二三四五六日"[now.weekday()]}',
         29,align='right',max_width=850,fill=INK_SECONDARY)
    line(80,145,1568,145,3)
    icon(weather,90,238,294,252)
    text(452,213,degrees(weather.get('temperature','--')),276,max_width=490)
    text(466,508,weather.get('label','天气暂不可用'),43,True,max_width=210)
    text(712,517,f'体感 {degrees(weather.get("apparent","--"))}',33,max_width=255,fill=INK_SECONDARY)
    line(1000,245,1000,543,fill=INK_RULE_LIGHT)
    text(1052,247,'今日天气提示',28,fill=INK_SECONDARY)
    headline, advice = weather_summary(weather, now)
    text(1052,311,headline,48,True,max_width=516)
    text(1052,382,advice,35,max_width=516,fill=INK_SECONDARY)
    text(1052,468,f'最低 {degrees(weather.get("low","--"))}   最高 {degrees(weather.get("high","--"))}',32,max_width=516)
    observed = parse_time(weather.get('observed_at'), now)
    updated = f'{observed:%H:%M} 天气数据' if observed and observed.date()==now.date() else f'{observed:%m/%d %H:%M} 天气数据' if observed else '天气数据暂不可用'
    text(1052,523,updated,26,max_width=516,fill=INK_TERTIARY)

    line(80,610,1568,610)
    text(80,648,'接下来 12 小时',31,True)
    text(1568,655,'天气 / 气温 / 降雨概率',27,align='right',fill=INK_SECONDARY)
    for index, item in enumerate(hour_slots(weather,now)):
        cx = 177+index*258.8
        stamp = item['stamp']
        label = f'{stamp.hour:02d} 时' if stamp.date()==now.date() else f'明日 {stamp.hour:02d} 时'
        text(cx,715,label,29,align='center',fill=INK_SECONDARY)
        icon(item,cx-37,765,74,63)
        text(cx,854,degrees(item.get('temperature','--')),43,True,align='center')
        text(cx,913,percent(item.get('rain','--')),29,True,align='center',fill=INK_SECONDARY)

    line(80,980,1568,980)
    text(80,1013,'未来三天',30,True)
    for index,(day,item) in enumerate(future_days(weather,now)):
        x = 80+index*510
        if index: line(x-27,1073,x-27,1182,fill=INK_RULE_LIGHT)
        weekday = '一二三四五六日'[day.weekday()]
        day_text = f'明天 · 周{weekday}' if index==0 else f'后天 · 周{weekday}' if index==1 else f'周{weekday} · {day.month}/{day.day}'
        text(x,1083,day_text,32,True,max_width=275)
        icon(item,x+285,1070,49,49)
        text(x+351,1085,item.get('label','暂无'),30,max_width=115,fill=INK_SECONDARY)
        low, high = item.get('low','--'), item.get('high','--')
        text(x,1139,f'{low}–{high}°' if low!='--' and high!='--' else '--',44,max_width=260)
        text(x+280,1154,f'降雨 {percent(item.get("rain","--"))}',29,True,
             max_width=186,fill=INK_SECONDARY)
    return im.resize((width,height),Image.Resampling.LANCZOS)
