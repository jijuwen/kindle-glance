"""Monochrome AI account board. Wall-clock labels follow the configured board timezone."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from PIL import Image, ImageDraw

from app.display_context import preferences, clock
from app.ai_account_data import MAX_BYTES, validate_snapshot

REVISION = 'usage-notice-contrast-v3'
STALE_SECONDS = 1800
# E-ink text hierarchy: core, important, secondary, supporting.
# Antialiased glyph edges naturally contain intermediate gray values.
INK = 0
IMPORTANT_INK = 17
SECONDARY_INK = 34
SUPPORTING_INK = 51


def load_snapshot(path):
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('Snapshot too large')
        return validate_snapshot(json.loads(raw))
    except (OSError, ValueError, TypeError):
        return None


def snapshot_revision(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:20]


def account_time(timestamp, now, pattern='%m/%d %H:%M'):
    return clock(datetime.fromtimestamp(timestamp, now.tzinfo), pattern) if timestamp else '未知'


def reset_label(timestamp, now):
    if not timestamp:
        return '重置时间未知'
    prefix = '重置 ' if timestamp > now.timestamp() else '待刷新 · '
    return prefix + clock(datetime.fromtimestamp(timestamp, now.tzinfo), '%m/%d %H:%M')


def account_status(account, collected_at, now):
    if account['status'] == 'reauth_required':
        return '需要重新登录'
    if account['status'] == 'refresh_error':
        return '额度刷新失败'
    observed = account['updated_at']
    if not observed or min(observed, collected_at) < now.timestamp() - STALE_SECONDS:
        return '数据已过期'
    if observed > now.timestamp() + 300 or collected_at > now.timestamp() + 300:
        return '数据时间异常'
    if any(w['reset_at'] and w['reset_at'] <= now.timestamp() for w in account['windows']):
        return '已到重置时间 · 待刷新'
    return ''


def draw_ai_accounts(snapshot, now, font):
    scale = 2
    image = Image.new('L', (1648 * scale, 1236 * scale), 255)
    draw = ImageDraw.Draw(image)
    fonts = {}

    def face(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            fonts[key] = font(round(size * scale), bold)
        return fonts[key]

    def width(value, size, bold=False):
        return draw.textlength(str(value), font=face(size, bold)) / scale

    def write(x, y, value, size=28, bold=False, fill=INK, right=False):
        if right:
            x -= width(value, size, bold)
        draw.text((round(x * scale), round(y * scale)), str(value),
                  font=face(size, bold), fill=fill, anchor='lt')

    def fit(value, size, available, bold=False):
        while width(value, size, bold) > available and size > 8:
            size -= 1
        return size

    def wrap(value, available, size):
        lines, line = [], ''
        for char in value:
            if line and width(line + char, size) > available:
                lines.append(line)
                line = ''
            line += char
        return lines + [line]

    def line(y, shade):
        draw.line((144, y * scale, 3152, y * scale), fill=shade, width=scale)

    def finish():
        return image.resize((1648, 1236), Image.Resampling.LANCZOS)

    def local_time(timestamp):
        pattern = '%H:%M' if timestamp and datetime.fromtimestamp(timestamp, now.tzinfo).date() == now.date() else '%m/%d %H:%M'
        return account_time(timestamp, now, pattern)

    write(72, 46, '用量提示', 58, True)
    weekday = '一二三四五六日'[now.weekday()]
    write(1576, 49, clock(now, '%m月%d日') + ' · 周' + weekday, 28, right=True)
    write(1576, 90, '画面生成 ' + clock(now, '%H:%M') + ' · ' + str(now.tzinfo), 24, fill=SUPPORTING_INK, right=True)
    line(138, 150)
    if not snapshot:
        write(72, 240, '等待账号数据同步', 44, True)
        return finish()

    # Keep accounts in source order and paginate additional quota windows.
    rows = [(a, a['windows'][i:i + 2]) for a in snapshot['accounts']
            for i in range(0, max(1, len(a['windows'])), 2)]
    # Official accounts retain their four fixed slots, including gaps after unlink.
    if all(a['id'] in {f'codex-slot-{i}' for i in range(1, 5)} for a in snapshot['accounts']):
        by_id = {a['id']: a for a in snapshot['accounts']}
        rows = [(by_id.get(f'codex-slot-{i}'), by_id[f'codex-slot-{i}']['windows'][:2]
                 if f'codex-slot-{i}' in by_id else []) for i in range(1, 5)]
    pages = max(1, math.ceil(len(rows) / 4))
    page = (int(now.timestamp()) // 900) % pages
    rows = rows[page * 4:(page + 1) * 4]
    for row, (account, windows) in enumerate(rows):
        if account is None:
            continue
        top = 172 + row * 251
        plan_size = fit(account['plan'], 24, 250, True)
        plan_width = width(account['plan'], plan_size, True)
        name_width = 1504 - plan_width - 26
        name_size = 34
        display_name = account['name']
        if preferences.get().get('mask_email') and '@' in display_name:
            display_name = display_name[:1] + '***@' + display_name.split('@')[-1]
        names = wrap(display_name, name_width, name_size)
        while len(names) > 1 and name_size > 24:
            name_size -= 1
            names = wrap(display_name, name_width, name_size)
        while len(names) > 2 and name_size > 8:
            name_size -= 1
            names = wrap(display_name, name_width, name_size)
        for i, name in enumerate(names):
            write(72, top + i * (name_size + 3), name, name_size)
        plan_x = 72 + max(width(name, name_size) for name in names) + 26
        write(plan_x, top + 5, account['plan'], plan_size, True, fill=SUPPORTING_INK)
        shift = 18 if len(names) > 1 else 0
        for index, window in enumerate(windows):
            x, end = 72 + index * 552, 552 + index * 552
            pct = window['remaining_percent']
            if pct is None:
                write(end, top + 49 + shift, '未知', 43, fill=IMPORTANT_INK, right=True)
                value_width = width('未知', 43)
            else:
                value = f'{pct:g}'
                percent_width = width('%', 34)
                number_size = fit(value, 72, 205 - percent_width, True)
                value_width = width(value, number_size, True) + percent_width + 5
                write(end, top + 46 + shift, '%', 34, fill=INK, right=True)
                write(end - percent_width - 5, top + 34 + shift, value, number_size, True, right=True)
            label = window['label'].replace('周额度', '周') if window['label'].startswith('GPT reserve ') else window['label']
            if not label.endswith('剩余'):
                label += '剩余'
            label_size = fit(label, 27, 480 - value_width - 20)
            write(x, top + 68 + shift, label, label_size, fill=SECONDARY_INK)
            box = (x * scale, (top + 121 + shift) * scale, end * scale, (top + 133 + shift) * scale)
            draw.rounded_rectangle(box, radius=3 * scale, fill=222)
            if pct is not None and pct > 0:
                draw.rounded_rectangle((box[0], box[1], (x + max(1, 480 * pct / 100)) * scale, box[3]), radius=3 * scale, fill=INK)
            reset = window['reset_at']
            if not reset:
                label = '重置时间未知'
            elif reset <= now.timestamp():
                label = local_time(reset) + ' 已到 · 待刷新'
            else:
                label = local_time(reset) + ' 重置' + (' · 已用尽' if pct == 0 else '')
            write(x, top + 151 + shift, label, fit(label, 26, 480), fill=IMPORTANT_INK)
        if not windows:
            write(72, top + 90, '暂无额度数据', 32)
        expiry = account['expires_at']
        write(1226, top + 61, '订阅剩余', 25, fill=SUPPORTING_INK)
        if expiry and expiry > now.timestamp():
            days = math.ceil((expiry - now.timestamp()) / 86400)
            value = str(days)
            write(1226, top + 102, value, 44, True)
            write(1226 + width(value, 44, True) + 9, top + 117, '天', 25, fill=SECONDARY_INK)
        else:
            write(1226, top + 107, '已到期' if expiry else '未知', 34, fill=IMPORTANT_INK)
        if expiry:
            write(1226, top + 160, local_time(expiry) + ' 到期', 24, fill=SECONDARY_INK)
        status = account_status(account, snapshot['collected_at'], now)
        footer = '额度更新 ' + local_time(account['updated_at'])
        if status:
            footer += ' · ' + status
        write(72, top + 204, footer, fit(footer, 23, 1070), fill=SUPPORTING_INK)
        if account['reset_credits']:
            write(1226, top + 204, f"可用重置券 {account['reset_credits']}", 23, fill=SECONDARY_INK)
        if any(next_account is not None for next_account, _ in rows[row + 1:]):
            line(top + 237, 205)
    if pages > 1:
        write(1576, 1203, f'{page + 1}/{pages}', 21, fill=SUPPORTING_INK, right=True)
    return finish()
