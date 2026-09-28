"""A small, read-only TRMNL-compatible display service for KOReader."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import html
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.admin_ui import admin_shell
from app import settings as persistent
from app.display_context import preferences
from app.codex_bridge import install_routes as install_codex_routes
from app.ai_accounts import draw_ai_accounts, load_snapshot as load_ai_snapshot, snapshot_revision as ai_snapshot_revision, REVISION as AI_REVISION
from app.day_night import draw_day_night, RENDER_REVISION as DAY_NIGHT_REVISION
from app.hourly_weather import draw_hourly_weather
from app.kindle_classics import draw_calendar, draw_time_scales, draw_weather_glance, draw_year_progress
from app.shan_shui import apply_render_mode, render_original, scene_seed
from app.weather_overview import draw_overview, normalize_weather

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("kindle-display")

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = DATA_DIR / "current.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"
FONT_PATH = os.getenv("FONT_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
FONT_BOLD_PATH = os.getenv("FONT_BOLD_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
MAX_IMAGES = 3
MAX_EVENTS = 80
MAX_PAGE_IMAGES = 12
ADMIN_SESSION_COOKIE = "kindle_dashboard_session"
ADMIN_SESSION_SECONDS = 8 * 60 * 60
PAGES_STATE_PATH = DATA_DIR / "pages.json"
PLAYLIST_PATH = DATA_DIR / "playlist.json"
SHAN_SHUI_STATE_PATH = DATA_DIR / "shan-shui.json"
TRANSPORT_SIZE = (1236, 1648)
STATIC_DIR = Path(__file__).with_name("static")
PLAYLIST_VERSION = 4

# The renderer loop, the device endpoint and the admin actions all run in
# separate worker threads and every state file is read-modify-write.  STATE_LOCK
# serialises those short mutations; RENDER_LOCKS serialise the expensive part
# (a page render can launch Chromium) with one lock per page, so two callers
# never render the same page twice and a slow render never blocks an unrelated
# one.  A render always takes its page lock *before* STATE_LOCK, never the
# reverse, so the two can not deadlock.
STATE_LOCK = threading.RLock()
RENDER_LOCKS: dict[str, threading.Lock] = {}
# Transport encoding and its garbage collection share one short critical
# section. Native page rendering (including Chromium) stays outside it.
TRANSPORT_LOCK = threading.RLock()


def render_lock(page_id: str) -> threading.Lock:
    with STATE_LOCK:
        return RENDER_LOCKS.setdefault(page_id, threading.Lock())


# Parsing the same few kilobytes of JSON dozens of times per admin page load was
# most of the cost of rendering it.  Cache the parsed value against the file's
# (mtime, size) so an unchanged file is never re-read, and hand every caller its
# own copy because callers mutate what they get back.
_JSON_CACHE: dict[Path, tuple[tuple[int, int], Any]] = {}


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def cached_json(path: Path) -> Any | None:
    """Return a parsed state file, reusing the last parse while it is unchanged."""
    with STATE_LOCK:
        key = _stat_key(path)
        if key is None:
            _JSON_CACHE.pop(path, None)
            return None
        entry = _JSON_CACHE.get(path)
        if entry is not None and entry[0] == key:
            return copy.deepcopy(entry[1])
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _JSON_CACHE.pop(path, None)
            return None
        _JSON_CACHE[path] = (key, value)
        return copy.deepcopy(value)


def invalidate_json(path: Path) -> None:
    """Drop a cached parse after a write.

    Writers invalidate rather than seed the cache: what a writer holds in memory
    is not always what reading the file back would produce, and writes are rare
    enough that paying for one re-read is worth never serving a stale parse.
    """
    with STATE_LOCK:
        _JSON_CACHE.pop(path, None)


# Stage 2 deliberately uses a small fixed registry instead of a generic page
# builder.  It makes each page independently renderable and inspectable while
# preserving the stable /api/display contract used by the Kindle plugin.
PAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "simple-calendar": {"title": "简约月历", "orientation": "landscape", "size": (1648, 1236), "render_interval": 86400},
    "weather-glance": {"title": "天气一览", "orientation": "landscape", "size": (1648, 1236)},
    "hourly-weather": {"title": "逐时天气", "orientation": "landscape", "size": (1648, 1236)},
    "day-night": {"title": "世界昼夜", "orientation": "landscape", "size": (1648, 1236), "render_interval": 900},
    "year-progress": {"title": "年度进度", "orientation": "landscape", "size": (1648, 1236), "render_interval": 86400},
    "time-scales": {"title": "时间刻度", "orientation": "landscape", "size": (1648, 1236)},
    "daily-overview": {"title": "每日概览", "orientation": "landscape", "size": (1648, 1236)},
    "shan-shui": {
        "title": "山水长卷", "orientation": "landscape", "size": (1648, 1236),
        "render_interval": 6 * 60 * 60,
    },
    "ai-accounts": {"title": "用量提示", "orientation": "landscape", "size": (1648, 1236), "render_interval": 300},
}


def default_playlist_item(page_id: str, index: int = 0) -> dict[str, Any]:
    definition = PAGE_DEFINITIONS[page_id]
    return {
        "id": f"item-{page_id}-{index + 1}",
        "page_id": page_id,
        "name": definition["title"],
        "enabled": True,
        "duration_slots": 1,
        "rotation": 90 if definition["orientation"] == "landscape" else 0,
        "schedule": {"days": [1, 2, 3, 4, 5, 6, 7], "start": "00:00", "end": "24:00"},
        "smart_skip": True,
        "config": {"render_mode": "original_gray"} if page_id == "shan-shui" else {},
    }


def default_playlist() -> dict[str, Any]:
    return {
        "version": PLAYLIST_VERSION,
        "revision": 1,
        "smart_skip": True,
        "items": [default_playlist_item(page_id, index) for index, page_id in enumerate(PAGE_DEFINITIONS) if page_id != "ai-accounts" or os.getenv("CODEX_COLLECTOR_URL")],
    }


def board_settings():
    with STATE_LOCK:
        return persistent.load(DATA_DIR)


def required_env(name: str) -> str:
    value = persistent.secret(DATA_DIR, name)
    if not value or value.startswith("replace-with-"):
        raise RuntimeError(f"{name} must be initialized")
    return value


def config() -> dict[str, Any]:
    saved = board_settings()
    location = saved["location"] or {}
    return {
        "device_token": required_env("DEVICE_TOKEN"),
        "image_key": required_env("IMAGE_SIGNING_KEY"),
        "external_base_url": saved["external_base_url"],
        "allowed_device_id": os.getenv("ALLOWED_DEVICE_ID", "").strip().upper(),
        "latitude": location.get("latitude"), "longitude": location.get("longitude"),
        "city": location.get("name", ""), "timezone": saved["timezone"],
        "revision": saved["revision"], "display_preferences": saved["display_preferences"],
        "setup_state": saved["setup_state"],
        "render_interval": max(300, int(os.getenv("RENDER_INTERVAL_SECONDS", "1800"))),
        "refresh_seconds": max(900, int(os.getenv("KINDLE_REFRESH_SECONDS", "3600"))),
    }


def display_timezone(name: str | None = None) -> ZoneInfo:
    return ZoneInfo(name or board_settings()["timezone"])


def admin_password() -> str | None:
    return persistent.credentials(DATA_DIR).get("ADMIN_PASSWORD_HASH") or os.getenv("ADMIN_PASSWORD", "").strip() or None


def admin_session_key() -> str:
    key = persistent.secret(DATA_DIR, "ADMIN_SESSION_KEY") or (admin_password() or "")
    # Password changes invalidate sessions even when the independent key remains.
    return hashlib.sha256((key + ":" + (admin_password() or "")).encode()).hexdigest()


def make_admin_session() -> str:
    expires = int(time.time()) + ADMIN_SESSION_SECONDS
    nonce = os.urandom(16).hex()
    payload = f"{expires}.{nonce}"
    signature = hmac.new(admin_session_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_admin_session(value: str | None) -> bool:
    if not value or not admin_password():
        return False
    try:
        expires_text, nonce, supplied_signature = value.split(".", 2)
        expires = int(expires_text)
    except (TypeError, ValueError):
        return False
    if expires < time.time():
        return False
    payload = f"{expires}.{nonce}"
    expected_signature = hmac.new(admin_session_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied_signature, expected_signature)


def csrf_token(session: str) -> str:
    return hmac.new(admin_session_key().encode("utf-8"), f"csrf:{session}".encode("utf-8"), hashlib.sha256).hexdigest()


def require_admin(request: Request) -> str:
    if not admin_password():
        raise HTTPException(status_code=503, detail="dashboard is not configured")
    session = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not valid_admin_session(session):
        raise HTTPException(status_code=401, detail="login required")
    return session


def require_csrf(request: Request) -> None:
    session = require_admin(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(supplied, csrf_token(session)):
        raise HTTPException(status_code=403, detail="invalid request token")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if Path(FONT_BOLD_PATH).exists() and bold:
        path = FONT_BOLD_PATH
    elif Path(FONT_PATH).exists():
        path = FONT_PATH
    else:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # The production image installs Noto CJK.  Falling back keeps local
        # tests and emergency renders available on stripped-down hosts.
        return ImageFont.load_default(size=size)


WEATHER_LABELS = {
    0: "晴朗", 1: "大致晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "阵雨", 82: "强阵雨",
    95: "雷暴", 96: "雷暴冰雹", 99: "强雷暴",
}


def fetch_weather(settings: dict[str, Any]) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "latitude": settings["latitude"],
        "longitude": settings["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": settings["timezone"],
        "hourly": "temperature_2m,apparent_temperature,weather_code,precipitation_probability,wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day",
        "forecast_days": 7,
        "temperature_unit": settings.get("display_preferences", {}).get("temperature_unit", "celsius"),
    })
    request = urllib.request.Request(
        f"https://api.open-meteo.com/v1/forecast?{params}",
        headers={"User-Agent": "kindle-display/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as reply:
        payload = json.loads(reply.read().decode("utf-8"))
    return normalize_weather(payload, WEATHER_LABELS)


def get_weather(settings: dict[str, Any]) -> dict[str, Any]:
    """Share a 15-minute data cache between all weather layouts."""
    key = [settings["latitude"], settings["longitude"], settings["timezone"], settings.get("display_preferences", {}).get("temperature_unit", "celsius")]
    path = DATA_DIR / "weather-cache.json"
    cached = {}
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
        if candidate.get("key") == key and isinstance(candidate.get("weather"), dict):
            cached = candidate
    except (OSError, ValueError, AttributeError):
        pass
    age = time.time() - cached.get("fetched_at", 0)
    if cached and 0 <= age < 900:
        return {**cached["weather"], "_fetched_at": cached["fetched_at"]}
    try:
        weather = fetch_weather(settings)
        if weather.get("temperature") == "--" or not weather.get("forecast"):
            raise ValueError("Weather response is incomplete")
        fetched = int(time.time())
        with STATE_LOCK:
            persistent.atomic_json(path, {"key": key, "weather": weather, "fetched_at": fetched})
        return {**weather, "_fetched_at": fetched}
    except Exception:
        if cached:
            LOG.warning("Weather source unavailable; retaining last successful data")
            return {**cached["weather"], "_fetched_at": cached["fetched_at"], "_stale": True}
        raise


def fallback_weather() -> dict[str, Any]:
    placeholder = {"date": "", "label": "暂不可用", "high": "--", "low": "--", "rain": "--"}
    return {
        "temperature": "--", "apparent": "--", "label": "天气暂不可用",
        "wind": "--", "wind_direction": "--", "gust": "--", "rain_now": "--",
        "high": "--", "low": "--", "rain": "--", "forecast": [placeholder] * 3, "hourly": [],
    }










def draw_daily_overview_page(width: int, height: int, weather: dict[str, Any], now: datetime) -> Image.Image:
    return draw_overview(width, height, weather, now, font, config()["city"])


def read_pages_state() -> dict[str, Any]:
    state = cached_json(PAGES_STATE_PATH)
    return state if isinstance(state, dict) else {"pages": {}}


def write_pages_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        temporary = PAGES_STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(PAGES_STATE_PATH)
        invalidate_json(PAGES_STATE_PATH)


# Unlike the other state files, reading the playlist also migrates and
# normalizes it.  Caching the *normalized* result against the file's identity
# lets a hit skip those two passes as well as the read.  Only this reader fills
# the cache, and only after any repair write has settled, so what is cached is
# always the normalization of the file that is currently on disk.
_PLAYLIST_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def read_playlist_state() -> dict[str, Any]:
    with STATE_LOCK:
        key = _stat_key(PLAYLIST_PATH)
        entry = _PLAYLIST_CACHE.get("normalized")
        if key is not None and entry is not None and entry[0] == key:
            return copy.deepcopy(entry[1])
        try:
            state = json.loads(PLAYLIST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = default_playlist()
            write_playlist_state(state)
            normalized = normalize_playlist(state)
        else:
            normalized = normalize_playlist(migrate_playlist(state))
            if normalized != state:
                write_playlist_state(normalized)
        settled = _stat_key(PLAYLIST_PATH)
        if settled is not None:
            _PLAYLIST_CACHE["normalized"] = (settled, copy.deepcopy(normalized))
        return copy.deepcopy(normalized)


def write_playlist_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        temporary = PLAYLIST_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(PLAYLIST_PATH)
        _PLAYLIST_CACHE.pop("normalized", None)


def migrate_playlist(candidate: Any) -> dict[str, Any]:
    """Upgrade legacy playlists while preserving user order and item settings."""
    if isinstance(candidate, dict) and candidate.get("version") == PLAYLIST_VERSION:
        return candidate
    if isinstance(candidate, dict) and candidate.get("version") in (2, 3):
        migrated = copy.deepcopy(candidate)
        items = migrated.get("items", [])
        if not isinstance(items, list):
            items = []
        if candidate.get("version") == 2 and not any(isinstance(item, dict) and item.get("page_id") == "hourly-weather" for item in items):
            items.append(default_playlist_item("hourly-weather", len(items)))
        if not any(isinstance(item, dict) and item.get("page_id") == "day-night" for item in items):
            items.append(default_playlist_item("day-night", len(items)))
        migrated["items"] = items
        migrated["version"] = PLAYLIST_VERSION
        try:
            migrated["revision"] = max(1, int(migrated.get("revision", 1))) + 1
        except (TypeError, ValueError):
            migrated["revision"] = 2
        return migrated
    migrated = default_playlist()
    legacy = candidate.get("playlists", {}) if isinstance(candidate, dict) else {}
    if not isinstance(legacy, dict) or not legacy:
        return migrated
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile in ("portrait", "landscape"):
        playlist = legacy.get(profile, {})
        if not isinstance(playlist, dict):
            continue
        enabled = playlist.get("enabled", {})
        for page_id in playlist.get("page_ids", []):
            if page_id not in PAGE_DEFINITIONS or page_id in seen:
                continue
            item = default_playlist_item(page_id, len(items))
            item["enabled"] = bool(enabled.get(page_id, True))
            items.append(item)
            seen.add(page_id)
    for page_id in PAGE_DEFINITIONS:
        if page_id not in seen:
            items.append(default_playlist_item(page_id, len(items)))
    migrated["items"] = items
    migrated["migrated_from"] = 1
    return migrated


def normalize_clock(value: Any, fallback: str) -> str:
    text = str(value or fallback)
    if text == "24:00":
        return text
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except (TypeError, ValueError):
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return f"{hour:02d}:{minute:02d}"


def normalize_playlist_item(candidate: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    page_id = str(candidate.get("page_id", ""))
    if page_id not in PAGE_DEFINITIONS:
        return None
    base = default_playlist_item(page_id, index)
    raw_id = str(candidate.get("id", "")).strip()
    base["id"] = raw_id if raw_id else f"item-{uuid.uuid4().hex[:12]}"
    base["name"] = str(candidate.get("name") or PAGE_DEFINITIONS[page_id]["title"])[:80]
    base["enabled"] = bool(candidate.get("enabled", True))
    try:
        base["duration_slots"] = min(12, max(1, int(candidate.get("duration_slots", 1))))
    except (TypeError, ValueError):
        base["duration_slots"] = 1
    try:
        rotation = int(candidate.get("rotation", base["rotation"]))
    except (TypeError, ValueError):
        rotation = base["rotation"]
    base["rotation"] = rotation if rotation in {0, 90, 270} else base["rotation"]
    raw_schedule = candidate.get("schedule", {})
    schedule = raw_schedule if isinstance(raw_schedule, dict) else {}
    raw_days = schedule.get("days", base["schedule"]["days"])
    days = sorted({int(day) for day in raw_days if str(day).isdigit() and 1 <= int(day) <= 7})
    base["schedule"] = {
        "days": days or base["schedule"]["days"],
        "start": normalize_clock(schedule.get("start"), "00:00"),
        "end": normalize_clock(schedule.get("end"), "24:00"),
    }
    base["smart_skip"] = bool(candidate.get("smart_skip", True))
    raw_config = candidate.get("config", {}) if isinstance(candidate.get("config"), dict) else {}
    if page_id == "shan-shui":
        render_mode = str(raw_config.get("render_mode", "original_gray"))
        base["config"] = {"render_mode": render_mode if render_mode in {"original_gray", "kindle_gray"} else "original_gray"}
    elif page_id == "day-night":
        base["config"] = {key: value for key, value in raw_config.items() if key != "render_mode"}
    else:
        base["config"] = raw_config
    return base


def normalize_playlist(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return default_playlist()
    items: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(candidate.get("items", [])):
        item = normalize_playlist_item(raw, index)
        if not item:
            continue
        if item["id"] in ids:
            item["id"] = f"item-{uuid.uuid4().hex[:12]}"
        ids.add(item["id"])
        items.append(item)
    if not items:
        items = default_playlist()["items"]
    try:
        revision = max(1, int(candidate.get("revision", 1)))
    except (TypeError, ValueError):
        revision = 1
    return {
        "version": PLAYLIST_VERSION,
        "revision": revision,
        "smart_skip": bool(candidate.get("smart_skip", True)),
        "items": items,
    }


def save_unified_playlist(playlist: dict[str, Any], message: str = "播放列表已更新") -> dict[str, Any]:
    with STATE_LOCK:
        # Bumping the revision is a read-modify-write; two admin edits landing
        # together must not be handed the same number.
        normalized = normalize_playlist(playlist)
        normalized["revision"] = read_playlist_state().get("revision", 0) + 1
        write_playlist_state(normalized)
    record_event(
        "playlist_changed", message, revision=normalized["revision"],
        item_ids=[item["id"] for item in normalized["items"]],
    )
    return normalized


def minutes_since_midnight(value: str) -> int:
    if value == "24:00":
        return 24 * 60
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def schedule_active(item: dict[str, Any], current: datetime) -> bool:
    schedule = item["schedule"]
    minute = current.hour * 60 + current.minute
    start = minutes_since_midnight(schedule["start"])
    end = minutes_since_midnight(schedule["end"])
    if start == end:
        return current.isoweekday() in schedule["days"]
    if start < end:
        return current.isoweekday() in schedule["days"] and start <= minute < end
    if minute >= start:
        return current.isoweekday() in schedule["days"]
    previous_day = 7 if current.isoweekday() == 1 else current.isoweekday() - 1
    return previous_day in schedule["days"] and minute < end


def eligible_playlist_items(current: datetime, playlist: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source = playlist or read_playlist_state()
    eligible = [item for item in source["items"] if item["enabled"] and schedule_active(item, current)]
    if source.get("smart_skip"):
        pages = read_pages_state().get("pages", {})
        usable = [item for item in eligible if pages.get(item["page_id"], {}).get("filename") or not item.get("smart_skip")]
        if usable:
            eligible = usable
    if not eligible:
        eligible = [item for item in source["items"] if item["enabled"]]
    if not eligible:
        eligible = list(source["items"])
    return eligible


def select_playlist_item(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(display_timezone())
    playlist = read_playlist_state()
    eligible = eligible_playlist_items(current, playlist)
    if not eligible:
        raise RuntimeError("no pages configured")
    expanded = [item for item in eligible for _ in range(item["duration_slots"])]
    refresh_seconds = config()["refresh_seconds"]
    slot = int(current.timestamp()) // refresh_seconds
    item = expanded[slot % len(expanded)]
    return {
        "item": item,
        "item_id": item["id"],
        "page_id": item["page_id"],
        "slot": slot,
        "next_switch_at": (slot + 1) * refresh_seconds,
        "playlist": playlist,
    }


def playlist_timeline(now: datetime | None = None, hours: int = 24) -> list[dict[str, Any]]:
    current = now or datetime.now(display_timezone())
    refresh_seconds = config()["refresh_seconds"]
    start_slot = int(current.timestamp()) // refresh_seconds
    count = max(1, int(hours * 3600 / refresh_seconds))
    timeline: list[dict[str, Any]] = []
    for offset in range(count):
        point = datetime.fromtimestamp((start_slot + offset) * refresh_seconds, tz=display_timezone())
        selected = select_playlist_item(point)
        timeline.append({
            "at": int(point.timestamp()), "item_id": selected["item_id"],
            "page_id": selected["page_id"], "name": selected["item"]["name"],
        })
    return timeline


# Compatibility helpers retained for older local scripts and stage-3 tests.
def default_playlist_for_profile(profile: str) -> dict[str, Any]:
    items = [item for item in default_playlist()["items"] if PAGE_DEFINITIONS[item["page_id"]]["orientation"] == profile]
    page_ids = [item["page_id"] for item in items]
    return {"profile": profile, "mode": "cycle", "fixed_page_id": page_ids[0] if page_ids else None, "page_ids": page_ids, "enabled": {page_id: True for page_id in page_ids}}


def playlist_for_profile(profile: str) -> dict[str, Any]:
    items = [item for item in read_playlist_state()["items"] if PAGE_DEFINITIONS[item["page_id"]]["orientation"] == profile]
    page_ids = [item["page_id"] for item in items]
    return {"profile": profile, "mode": "cycle", "fixed_page_id": page_ids[0] if page_ids else None, "page_ids": page_ids, "enabled": {item["page_id"]: item["enabled"] for item in items}}


def select_playlist_page(profile: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    selected = select_playlist_item(now)
    return {**selected, "profile": profile or "unified"}


def display_profile(width: int, height: int) -> str:
    return "landscape" if width > height else "portrait"


def cleanup_page_images() -> None:
    images = sorted((path for path in DATA_DIR.glob("page-*.png") if not path.name.startswith("page-working-")),
                    key=lambda path: path.stat().st_mtime, reverse=True)
    pinned = {page.get("filename") for page in read_pages_state().get("pages", {}).values()}
    pinned.add((read_state() or {}).get("native_filename"))
    for old in images[MAX_PAGE_IMAGES:]:
        if old.name not in pinned:
            old.unlink(missing_ok=True)


def shan_shui_variant() -> int:
    try:
        payload = cached_json(SHAN_SHUI_STATE_PATH)
        return max(0, int((payload or {}).get("variant", 0)))
    except (AttributeError, TypeError, ValueError):
        return 0


def bump_shan_shui_variant() -> int:
    with STATE_LOCK:
        payload = {"variant": shan_shui_variant() + 1}
        temporary = SHAN_SHUI_STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(SHAN_SHUI_STATE_PATH)
        invalidate_json(SHAN_SHUI_STATE_PATH)
        return payload["variant"]


def current_shan_shui_seed(now: datetime | None = None) -> str:
    current = now or datetime.now(display_timezone())
    return scene_seed(current, shan_shui_variant())


def current_ai_snapshot():
    official = Path(os.getenv("CODEX_SNAPSHOT_PATH", "/app/codex-data/ai-accounts.json"))
    return load_ai_snapshot(official if official.exists() else DATA_DIR / "ai-accounts.json")


def page_needs_render(page_id: str, page: dict[str, Any], now: datetime | None = None) -> bool:
    if page.get("config_revision") != board_settings()["revision"]:
        return True
    if not page.get("filename") or not (DATA_DIR / page["filename"]).is_file():
        return True
    if page_id == "day-night" and page.get("render_revision") != DAY_NIGHT_REVISION:
        return True
    if page_id == "ai-accounts":
        snapshot = current_ai_snapshot()
        if page.get("render_revision") != AI_REVISION or page.get("source_revision") != ai_snapshot_revision(snapshot):
            return True
    current = now or datetime.now(display_timezone())
    if page_id in {"simple-calendar", "year-progress"}:
        return datetime.fromtimestamp(page.get("rendered_at", 0), tz=current.tzinfo).date() != current.date()
    if page_id == "shan-shui" and page.get("scene_seed") != current_shan_shui_seed(current):
        return True
    interval = int(PAGE_DEFINITIONS[page_id].get("render_interval", config()["render_interval"]))
    return int(time.time()) - int(page.get("rendered_at", 0)) >= interval


def render_page(page_id: str) -> dict[str, Any]:
    """Render one registered page without changing the Kindle's active screen."""
    if page_id not in PAGE_DEFINITIONS:
        raise ValueError(f"unknown page: {page_id}")
    with render_lock(page_id):
        return _render_page_locked(page_id)


def render_page_if_stale(page_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Render only when the page is still stale once this caller holds the lock.

    Two callers can decide a page needs rendering at the same moment.  Checking
    again inside the lock means the second one reuses what the first produced
    instead of launching a second Chromium.
    """
    if page_id not in PAGE_DEFINITIONS:
        raise ValueError(f"unknown page: {page_id}")
    with render_lock(page_id):
        page = read_pages_state().get("pages", {}).get(page_id, {})
        if not page_needs_render(page_id, page, now):
            return page
        return _render_page_locked(page_id)


def _render_page_locked(page_id: str) -> dict[str, Any]:
    context = config()
    token = preferences.set(context["display_preferences"])
    try:
        return _render_page_impl(page_id, context)
    finally:
        preferences.reset(token)


def _render_page_impl(page_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    """The body of a render.  Callers must already hold this page's render lock."""
    definition = PAGE_DEFINITIONS[page_id]
    width, height = definition["size"]
    if settings["latitude"] is None:
        raise HTTPException(503, detail="请先完成地区设置")
    now = datetime.now(display_timezone(settings["timezone"]))
    weather: dict[str, Any] | None = None
    weather_status: dict[str, Any] | None = None
    if page_id in {"daily-overview", "weather-glance", "hourly-weather"}:
        try:
            weather = get_weather(settings)
            weather_status = {"ok": not weather.get("_stale", False), "checked_at": weather.get("_fetched_at", int(time.time()))}
        except Exception as error:
            LOG.warning("%s weather update failed: %s", page_id, error)
            weather = fallback_weather()
            weather_status = {"ok": False, "checked_at": int(time.time()), "error": str(error)[:180]}
    scene_key: str | None = None
    ai_snapshot = None
    if page_id == "ai-accounts":
        ai_snapshot = current_ai_snapshot()
        image = draw_ai_accounts(ai_snapshot, now, font)
    elif page_id == "simple-calendar":
        image = draw_calendar(now, font)
    elif page_id == "weather-glance":
        image = draw_weather_glance(weather or fallback_weather(), now, font, settings["city"])
    elif page_id == "hourly-weather":
        image = draw_hourly_weather(weather or fallback_weather(), now, font, settings["city"])
    elif page_id == "day-night":
        image = draw_day_night(now, font, settings["latitude"], settings["longitude"], settings["city"])
    elif page_id == "year-progress":
        image = draw_year_progress(now, font)
    elif page_id == "time-scales":
        image = draw_time_scales(now, font)
    elif page_id == "daily-overview":
        image = draw_overview(width, height, weather or fallback_weather(), now, font, settings["city"])
    else:
        scene_key = current_shan_shui_seed(now)
        image = render_original(width, height, scene_key)
    temporary = DATA_DIR / f"page-working-{page_id}.png"
    image.save(temporary, "PNG", optimize=True)
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()[:16]
    filename = f"page-{page_id}-{width}x{height}-{digest}.png"
    target = DATA_DIR / filename
    with STATE_LOCK:
        if board_settings()["revision"] != settings["revision"]:
            temporary.unlink(missing_ok=True)
            raise HTTPException(409, detail="配置已更新，请重新生成预览")
        if target.exists():
            temporary.unlink(missing_ok=True)
        else:
            temporary.replace(target)
        # Read-modify-write as one step: a concurrent render of a different page
        # must not drop this entry.
        pages_state = read_pages_state()
        pages_state.setdefault("pages", {})[page_id] = {
            "filename": filename, "width": width, "height": height, "rendered_at": int(time.time()),
            "weather_status": weather_status, "config_revision": settings["revision"],
            **({"scene_seed": scene_key} if scene_key else {}),
            **({"render_revision": DAY_NIGHT_REVISION} if page_id == "day-night" else {}),
            **({"render_revision": AI_REVISION, "source_revision": ai_snapshot_revision(ai_snapshot)} if page_id == "ai-accounts" else {}),
        }
        write_pages_state(pages_state)
        cleanup_page_images()
    record_event("page_render", f"页面已生成：{definition['title']}", page_id=page_id, filename=filename, width=width, height=height)
    return pages_state["pages"][page_id]


def playlist_item(item_id: str) -> dict[str, Any] | None:
    return next((item for item in read_playlist_state()["items"] if item["id"] == item_id), None)


def compose_playlist_item(item: dict[str, Any], force_render: bool = False) -> dict[str, Any]:
    """Normalize every native page to the Kindle's fixed portrait framebuffer.

    A landscape page is rendered natively, then rotated into a 1236x1648 file.
    KOReader therefore remains in its stable portrait mode; the person can turn
    the physical Kindle when a landscape item appears.
    """
    pages = read_pages_state().get("pages", {})
    page = pages.get(item["page_id"], {})
    if force_render:
        page = render_page(item["page_id"])
    elif not page.get("filename") or page_needs_render(item["page_id"], page):
        page = render_page_if_stale(item["page_id"])
    render_mode = str(item.get("config", {}).get("render_mode", "original_gray"))
    rotation = int(item.get("rotation", 0))
    safe_item_id = "".join(character for character in item["id"] if character.isalnum() or character in "-_")[:48]
    # The native filename already carries a digest of the page's pixels, so the
    # inputs below fully determine the transport image.  Naming the file after
    # them (instead of after its own bytes) lets an unchanged screen skip the
    # rotate/pad/encode work entirely rather than doing it and throwing it away.
    recipe = f"{page['filename']}|{rotation}|{render_mode if item['page_id'] == 'shan-shui' else ''}|{TRANSPORT_SIZE}"
    digest = hashlib.sha256(recipe.encode("utf-8")).hexdigest()[:16]
    filename = f"screen-{safe_item_id}-{digest}.png"
    target = DATA_DIR / filename
    with TRANSPORT_LOCK:
        # Check after acquiring the lock: another request may have published it.
        if not target.is_file():
            with STATE_LOCK:
                with Image.open(DATA_DIR / page["filename"]) as opened:
                    image = opened.convert("L")
            if item["page_id"] == "shan-shui":
                image = apply_render_mode(image, render_mode)
            if rotation == 90:
                image = image.transpose(Image.Transpose.ROTATE_270)
            elif rotation == 270:
                image = image.transpose(Image.Transpose.ROTATE_90)
            if image.size != TRANSPORT_SIZE:
                image = ImageOps.pad(image, TRANSPORT_SIZE, method=Image.Resampling.LANCZOS, color=255, centering=(0.5, 0.5))
            temporary = DATA_DIR / f"screen-working-{safe_item_id}.png"
            try:
                image.save(temporary, "PNG", optimize=True)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        cleanup_images(filename)
    return {
        "filename": filename,
        "width": TRANSPORT_SIZE[0],
        "height": TRANSPORT_SIZE[1],
        "rendered_at": page["rendered_at"],
        "weather_status": page.get("weather_status") or {},
        "config_revision": page.get("config_revision"),
        "native_filename": page["filename"],
        "native_width": page["width"],
        "native_height": page["height"],
        "rotation": rotation,
    }


def read_state() -> dict[str, Any] | None:
    state = cached_json(STATE_PATH)
    return state if isinstance(state, dict) else None


def write_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(STATE_PATH)
        invalidate_json(STATE_PATH)


def record_event(kind: str, message: str, **details: Any) -> None:
    """Keep a small, non-sensitive activity trail for the personal dashboard."""
    event = {"at": int(time.time()), "kind": kind, "message": message, "details": details}
    with STATE_LOCK:
        try:
            existing = EVENTS_PATH.read_text(encoding="utf-8").splitlines() if EVENTS_PATH.exists() else []
            existing.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            temporary = EVENTS_PATH.with_suffix(".tmp")
            temporary.write_text("\n".join(existing[-MAX_EVENTS:]) + "\n", encoding="utf-8")
            temporary.replace(EVENTS_PATH)
        except OSError as error:
            LOG.warning("could not record dashboard event: %s", error)


def recent_events(limit: int = 8) -> list[dict[str, Any]]:
    try:
        events = [json.loads(line) for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        return list(reversed(events[-limit:]))
    except (OSError, json.JSONDecodeError):
        return []


def update_state(**changes: Any) -> dict[str, Any]:
    with STATE_LOCK:
        state = read_state() or {}
        state.update(changes)
        write_state(state)
        return state


def cleanup_images(current: str) -> None:
    with TRANSPORT_LOCK:
        images = sorted((path for path in DATA_DIR.glob("screen-*.png") if not path.name.startswith("screen-working-")),
                        key=lambda path: path.stat().st_mtime, reverse=True)
        active = (read_state() or {}).get("filename")
        preserved = {current, active}
        for old in images[MAX_IMAGES:]:
            if old.name not in preserved:
                old.unlink(missing_ok=True)




def signed_url(filename: str, expires: int, key: str) -> str:
    message = f"{filename}:{expires}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def format_time(value: Any) -> str:
    if not value:
        return "尚无记录"
    try:
        return datetime.fromtimestamp(int(value), tz=display_timezone()).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "时间未知"


LOGIN_ATTEMPTS = {}


def check_login_rate(request):
    address = request.client.host if request.client else "local"
    now = time.monotonic()
    with STATE_LOCK:
        attempts = [t for t in LOGIN_ATTEMPTS.get(address, []) if now - t < 300]
        if len(attempts) >= 10:
            raise HTTPException(429, detail="尝试过于频繁，请五分钟后重试")
        if len(LOGIN_ATTEMPTS) > 1024:
            LOGIN_ATTEMPTS.clear()
        LOGIN_ATTEMPTS[address] = attempts + [now]


def login_page(message: str = "") -> HTMLResponse:
    notice = f'<p class="notice">{html.escape(message)}</p>' if message else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kindle 控制台</title><style>
:root {{ color-scheme: dark; font-family: "Noto Sans CJK SC", "Microsoft YaHei", system-ui, sans-serif; }}
* {{ box-sizing: border-box; }} body {{ margin: 0; min-height: 100vh; display:grid; place-items:center; background:#101312; color:#f4f6f1; }}
.card {{ width:min(92vw, 400px); padding:2.4rem; border:1px solid #343b37; border-radius:22px; background:#1a1f1c; box-shadow:0 24px 70px #0008; }}
.eyebrow {{ color:#91b9a2; font-size:.85rem; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ margin:.35rem 0 .5rem; font-size:2rem; }} p {{ color:#b9c0bc; line-height:1.6; }} label {{ display:block; margin:1.5rem 0 .5rem; font-size:.9rem; }} input {{ width:100%; padding:.85rem 1rem; border:1px solid #4a544d; border-radius:10px; background:#0f1211; color:#fff; font-size:1rem; }} button {{ width:100%; margin-top:1rem; padding:.85rem; border:0; border-radius:10px; background:#b5e8c9; color:#102216; font-size:1rem; font-weight:700; cursor:pointer; }} .notice {{ color:#ffb4a9; }} .hint {{ font-size:.82rem; }}
</style></head><body><main class="card"><div class="eyebrow">Kindle Display</div><h1>个人控制台</h1><p>查看当前画面和服务状态。</p>{notice}<form id="login-form"><label for="password">管理密码</label><input id="password" type="password" autocomplete="current-password" required autofocus><button type="submit">登录</button></form><p id="error" class="notice" role="alert"></p><p class="hint">此入口仅供管理员使用。</p></main><script>
document.getElementById('login-form').addEventListener('submit', async (event) => {{ event.preventDefault(); const response = await fetch('/admin/login', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{password:document.getElementById('password').value}})}}); if (response.ok) location.href='/admin'; else document.getElementById('error').textContent='密码不正确或服务暂不可用。'; }});
</script></body></html>"""
    )


def legacy_dashboard_page(session: str) -> HTMLResponse:
    state = read_state() or {}
    pages_state = read_pages_state().get("pages", {})
    weather_status = state.get("weather_status") or {}
    device = state.get("last_device_request") or {}
    filename = state.get("filename")
    preview = f'/admin/preview?v={html.escape(str(state.get("rendered_at", "")))}' if filename else ""
    weather_label = "正常" if weather_status.get("ok") else ("最近更新失败" if weather_status else "尚未检查")
    device_label = format_time(device.get("at"))
    events = recent_events()
    events_html = "".join(
        f'<li><span class="event-time">{format_time(event.get("at"))}</span><strong>{html.escape(str(event.get("message", "事件")))}</strong><span>{html.escape(str(event.get("details", dict()).get("filename", "")))}</span></li>'
        for event in events
    ) or '<li class="empty">尚无事件。首次 Kindle 拉图后会在此出现。</li>'
    weather_detail = html.escape(str(weather_status.get("error", "Open-Meteo 已成功返回数据。"))) if weather_status else "等待首次渲染。"
    page_cards = []
    for page_id, definition in PAGE_DEFINITIONS.items():
        page = pages_state.get(page_id, {})
        page_filename = page.get("filename")
        page_preview = f'/admin/pages/{page_id}/preview?v={html.escape(str(page.get("rendered_at", "")))}' if page_filename else ""
        status = f"上次生成 {format_time(page.get('rendered_at'))}" if page_filename else "尚未生成"
        page_cards.append(
            f'''<article class="page-card"><div class="page-preview {definition['orientation']}">{f'<img src="{page_preview}" alt="{html.escape(definition["title"])} 预览">' if page_preview else '<span>尚未生成预览</span>'}</div><div class="page-meta"><div><h4>{html.escape(definition['title'])}</h4><p>{'横屏 1648 × 1236' if definition['orientation'] == 'landscape' else '竖屏 1236 × 1648'}<br>{html.escape(status)}</p></div><button class="page-render" data-page="{page_id}">重新渲染</button></div></article>'''
        )
    page_cards_html = "".join(page_cards)
    playlist_sections = []
    for profile, profile_label in (("portrait", "竖屏播放列表"), ("landscape", "横屏播放列表")):
        selection = select_playlist_page(profile)
        playlist = selection["playlist"]
        current_title = PAGE_DEFINITIONS[selection["page_id"]]["title"]
        items = []
        for index, page_id in enumerate(playlist["page_ids"]):
            enabled = playlist["enabled"].get(page_id, False)
            title = html.escape(PAGE_DEFINITIONS[page_id]["title"])
            toggle = "停用" if enabled else "启用"
            items.append(
                f'''<li class="playlist-item"><strong>{title}</strong><span>{'已启用' if enabled else '已停用'}</span><div class="playlist-actions"><button class="playlist-action" data-profile="{profile}" data-action="toggle" data-page="{page_id}">{toggle}</button><button class="playlist-action" data-profile="{profile}" data-action="up" data-page="{page_id}" {'disabled' if index == 0 else ''}>↑</button><button class="playlist-action" data-profile="{profile}" data-action="down" data-page="{page_id}" {'disabled' if index == len(playlist['page_ids']) - 1 else ''}>↓</button><button class="playlist-action" data-profile="{profile}" data-action="fixed" data-page="{page_id}">固定此页</button></div></li>'''
            )
        mode_label = "固定模式" if playlist["mode"] == "fixed" else "循环模式"
        next_switch = format_time(selection["next_switch_at"])
        playlist_sections.append(
            f'''<article class="playlist-card"><h4>{profile_label}</h4><p>当前：<strong>{html.escape(current_title)}</strong> · {mode_label}<br>下次时间片：{next_switch}</p><div class="playlist-mode"><button class="playlist-action" data-profile="{profile}" data-action="mode" data-mode="cycle">循环模式</button><button class="playlist-action" data-profile="{profile}" data-action="mode" data-mode="fixed">固定模式</button></div><ul>{''.join(items)}</ul></article>'''
        )
    playlist_html = "".join(playlist_sections)
    response = HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kindle 个人控制台</title><style>
:root {{ color-scheme:dark; --ink:#edf2ee; --muted:#aab5ae; --line:#39453e; --surface:#1a201c; --surface2:#111613; --accent:#b5e8c9; --ok:#83d6a2; font-family:"Noto Sans CJK SC", "Microsoft YaHei", system-ui, sans-serif; }}
* {{ box-sizing:border-box; }} body {{ margin:0; min-width:320px; background:#101312; color:var(--ink); }} button {{ font:inherit; }}
header {{ max-width:1240px; margin:auto; padding:1.5rem 1.25rem; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #252d28; }}
.brand small {{ display:block; color:#8ea598; letter-spacing:.1em; text-transform:uppercase; }} .brand h1 {{ font-size:1.2rem; margin:.25rem 0 0; }}
.logout {{ padding:.55rem .85rem; color:var(--muted); border:1px solid var(--line); border-radius:9px; background:transparent; cursor:pointer; }}
main {{ max-width:1240px; margin:auto; padding:1.5rem 1.25rem 3rem; }} .intro {{ margin-bottom:1.4rem; }} h2 {{ margin:0; font-size:1.6rem; }} .intro p {{ color:var(--muted); margin:.45rem 0 0; }}
.layout {{ display:grid; grid-template-columns:minmax(280px, .9fr) minmax(360px, 1.1fr); gap:1.2rem; align-items:start; }} .panel {{ background:var(--surface); border:1px solid var(--line); border-radius:18px; padding:1.15rem; }}
.panel h3 {{ margin:0 0 1rem; font-size:1rem; }} .preview-wrap {{ background:#dfe4df; border-radius:11px; padding:.55rem; max-width:430px; margin:auto; }} .preview {{ display:block; width:100%; aspect-ratio:1236 / 1648; object-fit:contain; background:#fff; }} .no-preview {{ display:grid; place-items:center; aspect-ratio:1236 / 1648; color:#4a514d; background:#f9f9f9; text-align:center; padding:2rem; }}
.preview-caption {{ display:flex; justify-content:space-between; gap:1rem; color:var(--muted); font-size:.82rem; margin-top:.85rem; }} .action {{ margin-top:1rem; width:100%; padding:.78rem 1rem; background:var(--accent); color:#112419; border:0; border-radius:10px; font-weight:750; cursor:pointer; }} .action:disabled {{ opacity:.65; cursor:wait; }}
.metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.8rem; }} .metric {{ padding:1rem; background:var(--surface2); border:1px solid #2c3730; border-radius:12px; }} .metric span {{ display:block; color:var(--muted); font-size:.78rem; }} .metric strong {{ display:block; margin-top:.45rem; font-size:1rem; line-height:1.35; word-break:break-word; }} .ok {{ color:var(--ok); }} .warning {{ color:#ffc28a; }}
.wide {{ margin-top:1.2rem; }} ul {{ list-style:none; padding:0; margin:0; }} li {{ display:grid; grid-template-columns:10.5rem 1fr auto; gap:.75rem; align-items:center; padding:.8rem 0; border-top:1px solid #2c3730; font-size:.9rem; }} li:first-child {{ border-top:0; }} .event-time, li span:last-child {{ color:var(--muted); font-size:.78rem; }} .empty {{ display:block; color:var(--muted); }} .message {{ color:#ffb4a9; font-size:.85rem; margin:.8rem 0 0; min-height:1.2em; }}
.page-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1rem; }} .page-card {{ border:1px solid #2c3730; border-radius:13px; padding:.8rem; background:var(--surface2); }} .page-preview {{ display:grid; place-items:center; background:#dfe4df; border-radius:8px; overflow:hidden; color:#4a514d; }} .page-preview.portrait {{ aspect-ratio:1236 / 1648; max-width:250px; margin:auto; }} .page-preview.landscape {{ aspect-ratio:1648 / 1236; }} .page-preview img {{ display:block; width:100%; height:100%; object-fit:contain; background:#fff; }} .page-meta {{ display:flex; align-items:center; justify-content:space-between; gap:.8rem; padding:.75rem .1rem 0; }} .page-meta h4 {{ margin:0; font-size:1rem; }} .page-meta p {{ margin:.3rem 0 0; color:var(--muted); font-size:.78rem; line-height:1.45; }} .page-render {{ padding:.55rem .7rem; white-space:nowrap; color:#112419; border:0; border-radius:8px; background:var(--accent); font-weight:700; cursor:pointer; }}
.playlist-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1rem; }} .playlist-card {{ padding:1rem; border:1px solid #2c3730; border-radius:13px; background:var(--surface2); }} .playlist-card h4 {{ margin:0; }} .playlist-card p {{ color:var(--muted); font-size:.84rem; line-height:1.5; }} .playlist-mode,.playlist-actions {{ display:flex; flex-wrap:wrap; gap:.45rem; }} .playlist-action {{ padding:.42rem .58rem; border:1px solid #496052; border-radius:7px; background:#1b2820; color:var(--ink); cursor:pointer; }} .playlist-action:disabled {{ opacity:.35; cursor:not-allowed; }} .playlist-item {{ grid-template-columns:1fr auto; padding:.7rem 0; }} .playlist-item span {{ color:var(--muted); font-size:.78rem; }} .playlist-item .playlist-actions {{ grid-column:1 / -1; margin-top:.45rem; }}
@media (max-width:760px) {{ .layout,.page-grid,.playlist-grid {{ grid-template-columns:1fr; }} .metrics {{ grid-template-columns:1fr; }} li {{ grid-template-columns:1fr; gap:.2rem; }} .preview-wrap {{ max-width:360px; }} }}
</style></head><body><header><div class="brand"><small>Kindle Display</small><h1>个人控制台</h1></div><form action="/admin/logout" method="post"><button class="logout">退出登录</button></form></header>
<main><section class="intro"><h2>当前看板</h2><p>这里的预览就是 Kindle 下次拉取时会得到的画面。</p></section><div class="layout"><section class="panel"><h3>Kindle 预览</h3><div class="preview-wrap">{f'<img class="preview" src="{preview}" alt="当前 Kindle 看板预览">' if preview else '<div class="no-preview">尚未生成图片</div>'}</div><div class="preview-caption"><span>{html.escape(str(filename or "无图片"))}</span><span>{state.get("width", "—")} × {state.get("height", "—")}</span></div><button id="render" class="action">立即重新渲染</button><p id="message" class="message" role="status"></p></section>
<section class="panel"><h3>运行状态</h3><div class="metrics"><div class="metric"><span>最后成功渲染</span><strong>{format_time(state.get("rendered_at"))}</strong></div><div class="metric"><span>下次计划更新</span><strong>约每 {config()["render_interval"] // 60} 分钟</strong></div><div class="metric"><span>天气数据</span><strong class="{'ok' if weather_status.get('ok') else 'warning'}">{weather_label}</strong></div><div class="metric"><span>Kindle 最近取图</span><strong>{device_label}</strong></div><div class="metric"><span>Kindle 请求尺寸</span><strong>{html.escape(str(device.get("width", "尚无记录")))}{(' × ' + html.escape(str(device.get("height")))) if device.get("height") else ''}</strong></div><div class="metric"><span>当前刷新建议</span><strong>{config()["refresh_seconds"] // 60} 分钟</strong></div></div><p class="message">{weather_detail}</p></section></div>
<section class="panel wide"><h3>页面库</h3><p class="message">横屏每日概览已拥有独立播放列表；请先在 Kindle 上验证 KOReader 横屏显示，再把它用于日常轮换。</p><div class="page-grid">{page_cards_html}</div></section>
<section class="panel wide"><h3>播放列表</h3><p class="message">页面选择按刷新时间片计算。重复取图或网络重试不会跳页；横竖屏各自维护独立顺序。</p><div class="playlist-grid">{playlist_html}</div></section>
<section class="panel wide"><h3>最近事件</h3><ul>{events_html}</ul></section></main><script>
const button=document.getElementById('render'); button.addEventListener('click', async () => {{ button.disabled=true; button.textContent='正在生成…'; const message=document.getElementById('message'); try {{ const response=await fetch('/admin/api/actions/render', {{method:'POST', headers:{{'X-CSRF-Token':'{csrf_token(session)}'}}}}); if(!response.ok) throw new Error(); message.textContent='新画面已生成，正在刷新预览。'; setTimeout(()=>location.reload(),450); }} catch {{ message.textContent='重新渲染失败，请查看容器日志。'; button.disabled=false; button.textContent='立即重新渲染'; }} }});
document.querySelectorAll('.page-render').forEach((button) => {{ button.addEventListener('click', async () => {{ const original=button.textContent; button.disabled=true; button.textContent='生成中…'; try {{ const response=await fetch(`/admin/api/pages/${{button.dataset.page}}/render`, {{method:'POST', headers:{{'X-CSRF-Token':'{csrf_token(session)}'}}}}); if(!response.ok) throw new Error(); location.reload(); }} catch {{ button.disabled=false; button.textContent=original; }} }}); }});
document.querySelectorAll('.playlist-action').forEach((button) => {{ button.addEventListener('click', async () => {{ if(button.disabled) return; const profile=button.dataset.profile; const action=button.dataset.action; const page=button.dataset.page || ''; const mode=button.dataset.mode || ''; button.disabled=true; try {{ const response=await fetch(`/admin/api/playlists/${{profile}}/${{action}}?page_id=${{encodeURIComponent(page)}}&mode=${{encodeURIComponent(mode)}}`, {{method:'POST', headers:{{'X-CSRF-Token':'{csrf_token(session)}'}}}}); if(!response.ok) throw new Error(); location.reload(); }} catch {{ button.disabled=false; }} }}); }});
</script></body></html>"""
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def admin_item_view(item: dict[str, Any], current_item_id: str | None = None) -> dict[str, Any]:
    definition = PAGE_DEFINITIONS[item["page_id"]]
    page = read_pages_state().get("pages", {}).get(item["page_id"], {})
    return {
        **item,
        "page_title": definition["title"],
        "native_orientation": definition["orientation"],
        "orientation_label": "横屏页面" if definition["orientation"] == "landscape" else "竖屏页面",
        "rendered_at": page.get("rendered_at"),
        "preview_url": f"/admin/pages/{item['page_id']}/preview?v={page.get('rendered_at', '')}" if page.get("filename") else "",
        "display_preview_url": f"/admin/playlist/items/{item['id']}/preview?v={page.get('rendered_at', '')}",
        "is_current": item["id"] == current_item_id,
    }


def admin_bootstrap(view: str) -> dict[str, Any]:
    now = datetime.now(display_timezone())
    selection = select_playlist_item(now)
    playlist = selection["playlist"]
    views = [admin_item_view(item, selection["item_id"]) for item in playlist["items"]]
    view_by_id = {item["id"]: item for item in views}
    timeline = playlist_timeline(now)
    if view == "playlist":
        return {
            "playlist": playlist,
            "items": views,
            "timeline": timeline,
            "page_types": [
                {
                    "id": page_id,
                    "title": definition["title"],
                    "orientation_label": "横屏 1648 × 1236" if definition["orientation"] == "landscape" else "竖屏 1236 × 1648",
                }
                for page_id, definition in PAGE_DEFINITIONS.items()
            ],
        }
    state = read_state() or {}
    if state.get("config_revision") != board_settings()["revision"]:
        state = {"last_device_request": state.get("last_device_request")}
    device = state.get("last_device_request") or {}
    weather = state.get("weather_status") or {}
    current = dict(view_by_id.get(selection["item_id"], admin_item_view(selection["item"], selection["item_id"])))
    current.update({
        "preview_url": f"/admin/preview?v={state.get('rendered_at', '')}" if state.get("filename") else current.get("display_preview_url", ""),
        "display_preview_url": f"/admin/preview?v={state.get('rendered_at', '')}" if state.get("filename") else current.get("display_preview_url", ""),
        "rendered_at": state.get("rendered_at") or current.get("rendered_at"),
    })
    up_next: list[dict[str, Any]] = []
    for segment in timeline:
        item = dict(view_by_id[segment["item_id"]])
        item["at"] = segment["at"]
        up_next.append(item)
        if len(up_next) == 3:
            break
    hour = now.hour
    greeting = "夜深了" if hour < 5 else ("早上好" if hour < 11 else ("下午好" if hour < 18 else "晚上好"))
    return {
        "greeting": f"{greeting}，看板已就绪",
        "current": current,
        "up_next": up_next,
        "playlist_count": sum(1 for item in playlist["items"] if item["enabled"]),
        "metrics": {
            "service_ok": True,
            "refresh_minutes": config()["refresh_seconds"] // 60,
            "last_fetch": format_time(device.get("at")),
            "next_switch": format_time(selection["next_switch_at"]),
            "weather_ok": bool(weather.get("ok")),
            "smart_skip": playlist.get("smart_skip", True),
        },
        "events": [{"time": format_time(event.get("at")), "message": str(event.get("message", "事件"))} for event in recent_events(6)],
    }


def dashboard_page(session: str, view: str = "dashboard") -> HTMLResponse:
    title = "播放列表" if view == "playlist" else "仪表盘"
    response = HTMLResponse(admin_shell(view, title, {**admin_bootstrap(view), "settings": board_settings()}, csrf_token(session)))
    response.headers["Cache-Control"] = "no-store"
    return response


async def renderer_loop() -> None:
    while True:
        try:
            if board_settings()["setup_state"] not in {"complete", "migration_review"}:
                await asyncio.sleep(3)
                continue
            now = datetime.now(display_timezone())
            selection = select_playlist_item(now)
            page = read_pages_state().get("pages", {}).get(selection["page_id"], {})
            if page_needs_render(selection["page_id"], page, now):
                await asyncio.to_thread(render_page_if_stale, selection["page_id"], now)
        except Exception:
            LOG.exception("background render failed")
        await asyncio.sleep(config()["render_interval"])


def verify_configuration() -> None:
    with STATE_LOCK:
        persistent.bootstrap(DATA_DIR)


@asynccontextmanager
async def lifespan(_: FastAPI):
    verify_configuration()
    # The admin UI becomes available before weather or Chromium rendering.
    task = asyncio.create_task(renderer_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Kindle Display", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="admin-static")
install_codex_routes(app, require_admin, require_csrf, board_settings)
from app.setup_routes import install as install_setup_routes
install_setup_routes(app, globals())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    current = board_settings()
    configured = current["setup_state"] in {"complete", "migration_review"}
    return JSONResponse({"status": "ready" if configured else "setup_required"}, status_code=200 if configured else 503)


@app.get("/admin/login")
def admin_login(request: Request) -> Response:
    if not admin_password():
        return RedirectResponse("/admin/settings", status_code=303)
    if valid_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        return RedirectResponse("/admin", status_code=303)
    return login_page()


@app.post("/admin/login")
async def admin_login_submit(request: Request) -> JSONResponse:
    check_login_rate(request)
    password = admin_password()
    if not password:
        raise HTTPException(status_code=503, detail="dashboard is not configured")
    try:
        submitted = (await request.json()).get("password", "")
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid login request")
    if not persistent.password_matches(submitted, password):
        record_event("admin_login_failed", "控制台登录失败")
        raise HTTPException(status_code=401, detail="invalid password")
    session = make_admin_session()
    response = JSONResponse({"status": "ok"})
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        session,
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https" or os.getenv("ADMIN_COOKIE_SECURE") == "1",
        samesite="strict",
        path="/",
    )
    record_event("admin_login", "控制台已登录")
    return response


@app.post("/admin/logout")
def admin_logout() -> Response:
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return response


@app.get("/admin")
def admin_dashboard(request: Request) -> Response:
    if not admin_password():
        return RedirectResponse("/admin/settings", status_code=303)
    session = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not valid_admin_session(session):
        return RedirectResponse("/admin/login", status_code=303)
    if board_settings()["setup_state"] in {"uninitialized", "in_progress"}:
        return RedirectResponse("/admin/settings", status_code=303)
    return dashboard_page(session)


@app.get("/admin/playlist")
def admin_playlist(request: Request) -> Response:
    if not admin_password():
        return RedirectResponse("/admin/settings", status_code=303)
    session = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not valid_admin_session(session):
        return RedirectResponse("/admin/login", status_code=303)
    return dashboard_page(session, "playlist")


@app.get("/admin/preview")
def admin_preview(request: Request) -> FileResponse:
    require_admin(request)
    state = read_state()
    if not state:
        raise HTTPException(status_code=404, detail="no rendered image")
    if state.get("config_revision") != board_settings()["revision"]:
        state = compose_playlist_item(select_playlist_item()["item"])
    path = DATA_DIR / state.get("filename", "")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="rendered image is unavailable")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/admin/pages/{page_id}/preview")
def admin_page_preview(page_id: str, request: Request) -> FileResponse:
    require_admin(request)
    if page_id not in PAGE_DEFINITIONS:
        raise HTTPException(status_code=404, detail="unknown page")
    page = read_pages_state().get("pages", {}).get(page_id, {})
    page = render_page_if_stale(page_id)
    path = DATA_DIR / str(page.get("filename", ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="page preview is unavailable")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/admin/playlist/items/{item_id}/preview")
def admin_playlist_item_preview(item_id: str, request: Request) -> FileResponse:
    require_admin(request)
    item = playlist_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="unknown playlist item")
    rendered = compose_playlist_item(item)
    return FileResponse(DATA_DIR / rendered["filename"], media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/admin/api/actions/render")
def admin_render(request: Request) -> dict[str, Any]:
    require_csrf(request)
    try:
        selection = select_playlist_item()
        rendered = compose_playlist_item(selection["item"], force_render=True)
        previous = read_state() or {}
        state = {
            **rendered,
            "active_page_id": selection["page_id"],
            "active_item_id": selection["item_id"],
            "active_profile": "unified",
        }
        if previous.get("last_device_request"):
            state["last_device_request"] = previous["last_device_request"]
        with STATE_LOCK:
            if state.get("config_revision") != board_settings()["revision"]:
                raise HTTPException(409, detail="settings changed; retry render")
            write_state(state)
    except Exception as error:
        LOG.exception("manual dashboard render failed")
        record_event("render_failed", "手动重新渲染失败", error=str(error)[:180])
        raise HTTPException(status_code=500, detail="render failed")
    record_event("manual_render", "已从控制台手动重新渲染当前页面", item_id=selection["item_id"], page_id=selection["page_id"], filename=rendered["filename"])
    return {"status": "ok", "item_id": selection["item_id"], "page_id": selection["page_id"], "filename": rendered["filename"], "rendered_at": rendered["rendered_at"]}


@app.post("/admin/api/pages/{page_id}/render")
def admin_page_render(page_id: str, request: Request) -> dict[str, Any]:
    require_csrf(request)
    if page_id not in PAGE_DEFINITIONS:
        raise HTTPException(status_code=404, detail="unknown page")
    try:
        rendered = render_page(page_id)
    except Exception as error:
        LOG.exception("manual page render failed for %s", page_id)
        record_event("page_render_failed", "页面重新渲染失败", page_id=page_id, error=str(error)[:180])
        raise HTTPException(status_code=500, detail="page render failed")
    return {"status": "ok", "page_id": page_id, **rendered}


@app.post("/admin/api/playlists/{profile}/{action}")
def admin_playlist_action(
    profile: str,
    action: str,
    request: Request,
    page_id: str = "",
    mode: str = "",
) -> dict[str, Any]:
    """Backward-compatible stage-3 controls; the new UI uses item APIs below."""
    require_csrf(request)
    if profile not in {"portrait", "landscape"}:
        raise HTTPException(status_code=404, detail="unknown display profile")
    playlist = read_playlist_state()
    index = next((position for position, item in enumerate(playlist["items"]) if item["page_id"] == page_id), None)
    if action == "mode":
        return {"status": "ok", "playlist": playlist}
    if index is None:
        raise HTTPException(status_code=404, detail="page is not in this playlist")
    if action == "toggle":
        playlist["items"][index]["enabled"] = not playlist["items"][index]["enabled"]
    elif action in {"up", "down"}:
        destination = index - 1 if action == "up" else index + 1
        if 0 <= destination < len(playlist["items"]):
            playlist["items"][index], playlist["items"][destination] = playlist["items"][destination], playlist["items"][index]
    elif action == "fixed":
        selected = playlist["items"].pop(index)
        playlist["items"].insert(0, selected)
        selected["duration_slots"] = 12
    else:
        raise HTTPException(status_code=404, detail="unknown playlist action")
    return {"status": "ok", "playlist": save_unified_playlist(playlist)}


@app.post("/admin/api/playlist/settings")
async def admin_playlist_settings(request: Request) -> dict[str, Any]:
    require_csrf(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid settings")
    playlist = read_playlist_state()
    playlist["smart_skip"] = bool(payload.get("smart_skip", True))
    return {"status": "ok", "playlist": save_unified_playlist(playlist, "Smart Skip 设置已更新")}


@app.post("/admin/api/playlist/items")
async def admin_playlist_add_item(request: Request) -> dict[str, Any]:
    require_csrf(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid item")
    page_id = str(payload.get("page_id", ""))
    if page_id not in PAGE_DEFINITIONS:
        raise HTTPException(status_code=404, detail="unknown page")
    playlist = read_playlist_state()
    item = default_playlist_item(page_id, len(playlist["items"]))
    item["id"] = f"item-{uuid.uuid4().hex[:12]}"
    playlist["items"].append(item)
    saved = save_unified_playlist(playlist, f"已添加播放项目：{PAGE_DEFINITIONS[page_id]['title']}")
    return {"status": "ok", "item": saved["items"][-1], "playlist": saved}


@app.post("/admin/api/playlist/items/{item_id}")
async def admin_playlist_update_item(item_id: str, request: Request) -> dict[str, Any]:
    require_csrf(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid item settings")
    playlist = read_playlist_state()
    index = next((position for position, item in enumerate(playlist["items"]) if item["id"] == item_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="unknown playlist item")
    candidate = {**playlist["items"][index]}
    for key in ("name", "duration_slots", "rotation", "enabled", "smart_skip", "schedule", "config"):
        if key in payload:
            candidate[key] = payload[key]
    normalized = normalize_playlist_item(candidate, index)
    if not normalized:
        raise HTTPException(status_code=400, detail="invalid item settings")
    playlist["items"][index] = normalized
    saved = save_unified_playlist(playlist, f"已更新播放项目：{normalized['name']}")
    return {"status": "ok", "item": saved["items"][index], "playlist": saved}


@app.post("/admin/api/playlist/items/{item_id}/{action}")
def admin_playlist_item_action(item_id: str, action: str, request: Request) -> dict[str, Any]:
    require_csrf(request)
    playlist = read_playlist_state()
    index = next((position for position, item in enumerate(playlist["items"]) if item["id"] == item_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="unknown playlist item")
    item = playlist["items"][index]
    if action == "toggle":
        item["enabled"] = not item["enabled"]
    elif action == "duplicate":
        duplicate = json.loads(json.dumps(item))
        duplicate["id"] = f"item-{uuid.uuid4().hex[:12]}"
        duplicate["name"] = f"{item['name']} 副本"[:80]
        playlist["items"].insert(index + 1, duplicate)
    elif action == "delete":
        if len(playlist["items"]) <= 1:
            raise HTTPException(status_code=400, detail="播放列表至少需要保留一个项目")
        playlist["items"].pop(index)
    elif action == "render":
        rendered = compose_playlist_item(item, force_render=True)
        record_event("manual_render", f"已重新渲染：{item['name']}", item_id=item_id, filename=rendered["filename"])
        return {"status": "ok", "rendered": rendered}
    elif action == "new-scene":
        if item["page_id"] != "shan-shui":
            raise HTTPException(status_code=400, detail="此页面不支持换景")
        variant = bump_shan_shui_variant()
        render_page("shan-shui")
        rendered = compose_playlist_item(item)
        record_event("shan_shui_new_scene", "山水长卷已换景", item_id=item_id, variant=variant, filename=rendered["filename"])
        return {"status": "ok", "rendered": rendered}
    else:
        raise HTTPException(status_code=404, detail="unknown playlist action")
    saved = save_unified_playlist(playlist, f"播放项目操作：{action}")
    return {"status": "ok", "playlist": saved}


@app.post("/admin/api/playlist/reorder")
async def admin_playlist_reorder(request: Request) -> dict[str, Any]:
    require_csrf(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid order")
    item_ids = payload.get("item_ids", [])
    playlist = read_playlist_state()
    existing = {item["id"]: item for item in playlist["items"]}
    if not isinstance(item_ids, list) or len(item_ids) != len(existing) or set(item_ids) != set(existing):
        raise HTTPException(status_code=400, detail="播放顺序与当前列表不一致，请刷新后重试")
    playlist["items"] = [existing[item_id] for item_id in item_ids]
    return {"status": "ok", "playlist": save_unified_playlist(playlist, "播放顺序已更新")}


@app.get("/api/display")
def display(
    access_token: str | None = Header(default=None, alias="access-token"),
    device_id: str | None = Header(default=None, alias="ID"),
    png_width: int | None = Header(default=None, alias="png-width"),
    png_height: int | None = Header(default=None, alias="png-height"),
) -> dict[str, Any]:
    settings = config()
    if not access_token or not hmac.compare_digest(access_token, settings["device_token"]):
        raise HTTPException(status_code=401, detail="invalid access token")
    if settings["allowed_device_id"] and (device_id or "").upper() != settings["allowed_device_id"]:
        raise HTTPException(status_code=403, detail="device is not allowed")
    if settings["setup_state"] not in {"complete", "migration_review"}:
        raise HTTPException(503, detail="setup_required")
    width = min(max(png_width or 1236, 600), 2000)
    height = min(max(png_height or 1648, 800), 2600)
    selection = select_playlist_item()
    item = selection["item"]
    page_id = selection["page_id"]
    page = compose_playlist_item(item)
    requested_at = int(time.time())
    with STATE_LOCK:
        if page.get("config_revision") != board_settings()["revision"]:
            raise HTTPException(409, detail="settings changed; retry fetch")
        update_state(
            filename=page["filename"], width=page["width"], height=page["height"], rendered_at=page["rendered_at"],
            weather_status=page.get("weather_status") or {}, active_page_id=page_id, active_item_id=item["id"], active_profile="unified",
            rotation=item["rotation"], native_filename=page["native_filename"], config_revision=page.get("config_revision"),
            last_device_request={"at": requested_at, "width": width, "height": height, "item_id": item["id"], "page_id": page_id, "profile": "unified", "slot": selection["slot"]},
        )
    record_event(
        "device_fetch", "Kindle 已请求播放列表页面", item_id=item["id"], page_id=page_id, rotation=item["rotation"], profile="unified",
        slot=selection["slot"], width=width, height=height, filename=page["filename"],
    )
    if not settings["external_base_url"]:
        raise HTTPException(status_code=503, detail="EXTERNAL_BASE_URL is not configured")
    expires = int(time.time()) + 600
    signature = signed_url(page["filename"], expires, settings["image_key"])
    return {
        "image_url": f"{settings['external_base_url']}/api/images/{page['filename']}?expires={expires}&sig={signature}",
        "filename": page["filename"],
        "refresh_rate": settings["refresh_seconds"],
        "page_id": page_id,
        "playlist_item_id": item["id"],
        "rotation": item["rotation"],
    }


@app.get("/api/images/{filename}")
def image(filename: str, expires: int = Query(...), sig: str = Query(...)) -> FileResponse:
    if time.time() > expires:
        raise HTTPException(status_code=403, detail="expired image URL")
    if not hmac.compare_digest(sig, signed_url(filename, expires, config()["image_key"])):
        raise HTTPException(status_code=403, detail="invalid image signature")
    path = DATA_DIR / filename
    if not path.is_file() or not filename.startswith(("screen-", "page-")) or not filename.endswith(".png"):
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
