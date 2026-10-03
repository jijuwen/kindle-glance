"""Versioned single-process settings. No browser or host-location defaults."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SettingsError(ValueError):
    pass


class Conflict(SettingsError):
    pass


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, OSError) as error:
        raise SettingsError(f"{path.name} 无法读取，请从备份修复；原文件未覆盖") from error


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def defaults():
    return {"schema_version": 1, "revision": 1, "setup_state": "uninitialized",
            "location": None, "timezone": "UTC", "external_base_url": "",
            "device_profile": "kpw11", "selected_pages": ["simple-calendar", "weather-glance", "year-progress"],
            "display_preferences": {"temperature_unit": "celsius", "week_start": 0,
                                    "hour_format": "24", "mask_email": False}}


def validate(value):
    value = copy.deepcopy(value)
    if value.get("schema_version") != 1 or type(value.get("revision")) is not int:
        raise SettingsError("设置版本不支持")
    if value.get("setup_state") not in ("uninitialized", "in_progress", "complete", "migration_review"):
        raise SettingsError("初始化状态无效")
    try:
        ZoneInfo(value["timezone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise SettingsError("请选择有效的 IANA 时区")
    location = value.get("location")
    if location is not None:
        if not isinstance(location, dict) or not isinstance(location.get("name"), str) or not 1 <= len(location["name"].strip()) <= 100:
            raise SettingsError("地点名称须为 1–100 个字符")
        for key, limit in (("latitude", 90), ("longitude", 180)):
            number = location.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or abs(number) > limit:
                raise SettingsError("经纬度超出有效范围")
        if len(str(location.get("id", ""))) > 120:
            raise SettingsError("地点标识过长")
        value["location"] = {"name": location["name"].strip(), "latitude": location["latitude"],
                             "longitude": location["longitude"], "id": str(location.get("id", "manual"))}
    base = value.get("external_base_url", "")
    if not isinstance(base, str) or len(base) > 500:
        raise SettingsError("服务地址无效")
    if base:
        try:
            parsed = urlsplit(base)
            parsed.port
        except ValueError as error:
            raise SettingsError("服务地址无效") from error
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise SettingsError("服务地址须为不含路径或密码的 HTTP / HTTPS 地址")
    value["external_base_url"] = base.rstrip("/")
    prefs = value.get("display_preferences", {})
    if not isinstance(prefs, dict) or prefs.get("temperature_unit") not in ("celsius", "fahrenheit") or type(prefs.get("week_start")) is not int or prefs.get("week_start") not in (0, 6) or prefs.get("hour_format") not in ("12", "24") or type(prefs.get("mask_email")) is not bool:
        raise SettingsError("显示偏好无效")
    if value.get("device_profile") != "kpw11":
        raise SettingsError("当前仅提供 KPW11 设备档案")
    if not isinstance(value.get("selected_pages"), list) or not value["selected_pages"] or len(value["selected_pages"]) > 10 or any(not isinstance(p, str) for p in value["selected_pages"]):
        raise SettingsError("请至少选择一种看板内容")
    return value


def load(directory: Path):
    path = directory / "settings.json"
    if path.exists():
        return validate(read_json(path))
    value = defaults()
    # Existing runtime state is evidence of an old installation. Environment
    # variables alone do not silently turn a fresh installation into Xiamen.
    old_files = [directory / name for name in ("playlist.json", "current.json", "pages.json") if (directory / name).exists()]
    if old_files:
        for old in old_files:
            read_json(old)  # damaged data is never treated as an empty install
        backup = directory / "migration-v1-backup"
        backup.mkdir(exist_ok=True)
        for old in old_files:
            if not (backup / old.name).exists():
                shutil.copy2(old, backup / old.name)
        value.update(location={"id": "legacy", "name": os.getenv("WEATHER_CITY", "厦门"),
                               "latitude": float(os.getenv("WEATHER_LATITUDE", "24.4798")),
                               "longitude": float(os.getenv("WEATHER_LONGITUDE", "118.0894"))},
                     timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
                     external_base_url=os.getenv("EXTERNAL_BASE_URL", ""),
                     setup_state="migration_review")
        value["migration"] = {"from": "pre-settings", "at": int(time.time()),
                              "message": "已保留原播放列表、令牌和时区；请确认地区与显示偏好。"}
        # Old UI showed full emails. Preserve that explicit behavior.
    atomic_json(path, validate(value))
    return copy.deepcopy(value)


def save(directory, candidate, revision):
    current = load(directory)
    if type(revision) is not int or revision != current["revision"]:
        raise Conflict("设置已在其他窗口更新，请重新载入后保存")
    updated = copy.deepcopy(current)
    for key in ("location", "timezone", "external_base_url", "device_profile", "display_preferences", "selected_pages", "setup_state"):
        if key in candidate:
            updated[key] = candidate[key]
    updated["revision"] += 1
    updated = validate(updated)
    atomic_json(directory / "settings.json", updated)
    return updated


def password_hash(password):
    if not isinstance(password, str) or len(password) < 6:
        raise SettingsError("管理员密码至少 6 个字符，不限制字符类型")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def password_matches(password, stored):
    if not isinstance(password, str):
        return False
    if not stored.startswith("scrypt$"):
        return hmac.compare_digest(password.encode(), stored.encode())
    _, salt, expected = stored.split("$")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def credentials(directory):
    path = directory / "credentials.json"
    return read_json(path) if path.exists() else {}


def secret(directory, name):
    saved = credentials(directory)
    # Rotated device tokens intentionally supersede the old environment value.
    return saved.get(name) or os.getenv(name, "").strip()


def generate_device_token(previous=None):
    """Six characters for Kindle entry; omit easily confused 0/O and 1/I."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        if token != previous:
            return token


def bootstrap(directory):
    value = credentials(directory)
    for name in ("DEVICE_TOKEN", "IMAGE_SIGNING_KEY", "ADMIN_SESSION_KEY"):
        old = os.getenv(name, "").strip()
        if old.startswith("replace-with-"):
            raise SettingsError(f"请移除 {name} 的占位值，或设置独立随机密钥")
        if name not in value:
            value[name] = old or (generate_device_token() if name == "DEVICE_TOKEN" else secrets.token_urlsafe(32))
    atomic_json(directory / "credentials.json", value)
    if not value.get("ADMIN_PASSWORD_HASH") and not os.getenv("ADMIN_PASSWORD") and not (directory / "setup-code.json").exists():
        renew_setup_code(directory)
    load(directory)


def renew_setup_code(directory):
    if credentials(directory).get("ADMIN_PASSWORD_HASH") or os.getenv("ADMIN_PASSWORD"):
        raise SettingsError("管理员已建立，不能重发初始化码")
    code = secrets.token_urlsafe(24)
    atomic_json(directory / "setup-code.json", {"code": code, "expires_at": int(time.time()) + 3600})
    return code


def establish_admin(directory, code, password):
    if credentials(directory).get("ADMIN_PASSWORD_HASH") or os.getenv("ADMIN_PASSWORD"):
        raise Conflict("管理员已建立，请登录")
    path = directory / "setup-code.json"
    saved = read_json(path)
    if not isinstance(code, str) or saved["expires_at"] < time.time() or not hmac.compare_digest(code, saved["code"]):
        raise SettingsError("初始化码无效或已过期，请在服务器本机重发")
    value = credentials(directory)
    value["ADMIN_PASSWORD_HASH"] = password_hash(password)
    atomic_json(directory / "credentials.json", value)
    path.unlink(missing_ok=True)


def local_timestamp(text, zone, fold=None):
    """Reject DST gaps; require explicit fold for repeated local minutes."""
    try:
        naive = datetime.fromisoformat(text)
        if naive.tzinfo is not None or not 2000 <= naive.year <= 2199:
            raise ValueError()
        tz = ZoneInfo(zone)
        candidates = {}
        for candidate_fold in (0, 1):
            local = naive.replace(tzinfo=tz, fold=candidate_fold)
            stamp = int(local.timestamp())
            if datetime.fromtimestamp(stamp, tz).replace(tzinfo=None) == naive:
                candidates[candidate_fold] = stamp
        if not candidates:
            raise SettingsError("该当地时间因夏令时跳变不存在")
        if len(set(candidates.values())) > 1 and fold not in (0, 1):
            raise SettingsError("该当地时间重复出现，请选择第一次或第二次")
        return candidates.get(fold, next(iter(candidates.values())))
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        if isinstance(error, SettingsError):
            raise
        raise SettingsError("当地日期时间或时区无效") from error
