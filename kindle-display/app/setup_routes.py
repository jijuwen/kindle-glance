"""First-run and daily settings endpoints, with shared existing admin sessions."""
import asyncio
import copy
import json
import secrets
import time
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import settings, locations as place_search


async def body(request):
    raw = await request.body()
    if len(raw) > 16384:
        raise HTTPException(413, detail="请求过大")
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except ValueError:
        raise HTTPException(400, detail="请求格式无效")


def install(app, g):
    def state():
        result = g["board_settings"]()
        result["local_time"] = datetime.now(g["display_timezone"]()).isoformat(timespec="seconds")
        result["device"] = (g["read_state"]() or {}).get("last_device_request")
        result["collector_installed"] = bool(g["os"].getenv("CODEX_COLLECTOR_URL"))
        result["locked_fields"] = [key for key in g["os"].getenv("SETTINGS_LOCK_FIELDS", "").split(",") if key]
        result["page_types"] = [{"id": key, "title": item["title"]} for key, item in g["PAGE_DEFINITIONS"].items()
                                if key != "ai-accounts" or result["collector_installed"]]
        return result

    @app.exception_handler(settings.SettingsError)
    async def settings_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409 if isinstance(error, settings.Conflict) else 400)

    @app.get("/admin/settings")
    def settings_page(request: Request):
        session = request.cookies.get(g["ADMIN_SESSION_COOKIE"])
        if g["admin_password"]() and not g["valid_admin_session"](session):
            return RedirectResponse("/admin/login", status_code=303)
        csrf = g["csrf_token"](session) if session else ""
        from app.setup_ui import shell
        return HTMLResponse(shell(csrf, bool(g["admin_password"]())), headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/setup/claim")
    async def claim(request: Request):
        g["check_login_rate"](request)
        data = await body(request)
        with g["STATE_LOCK"]:
            settings.establish_admin(g["DATA_DIR"], data.get("code"), data.get("password"))
            current = g["board_settings"]()
            phase = "migration_review" if current["setup_state"] == "migration_review" else "in_progress"
            settings.save(g["DATA_DIR"], {"setup_state": phase}, current["revision"])
            session = g["make_admin_session"]()
        response = JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})
        response.set_cookie(g["ADMIN_SESSION_COOKIE"], session, httponly=True, samesite="strict", path="/",
                            secure=request.url.scheme == "https" or g["os"].getenv("ADMIN_COOKIE_SECURE") == "1",
                            max_age=g["ADMIN_SESSION_SECONDS"])
        return response

    @app.get("/admin/api/settings")
    def get_settings(request: Request):
        g["require_admin"](request)
        return JSONResponse(state(), headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/settings")
    async def save_settings(request: Request):
        g["require_csrf"](request)
        data = await body(request)
        selected = data.get("selected_pages", [])
        if not isinstance(selected, list) or any(not isinstance(page, str) or page not in g["PAGE_DEFINITIONS"] for page in selected):
            raise HTTPException(400, detail="看板内容不存在")
        if "setup_state" in data:
            raise HTTPException(400, detail="请通过完成步骤结束设置")
        locked = set(g["os"].getenv("SETTINGS_LOCK_FIELDS", "").split(",")) - {""}
        with g["STATE_LOCK"]:
            current = g["board_settings"]()
            for key in locked:
                if key in data and data[key] != current.get(key):
                    raise HTTPException(403, detail=f"{key} 已由部署配置锁定")
            settings.save(g["DATA_DIR"], data, data.get("revision"))
        return JSONResponse(state(), headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/setup/finish")
    async def finish(request: Request):
        g["require_csrf"](request)
        data = await body(request)
        with g["STATE_LOCK"]:
            current = g["board_settings"]()
            if type(data.get("revision")) is not int or data["revision"] != current["revision"]:
                raise settings.Conflict("设置已更新，请重新载入")
            if not current["location"]:
                raise HTTPException(400, detail="请先确认地区与时区")
            if current["setup_state"] in {"uninitialized", "in_progress"}:
                # Do not replace an existing migrated user's playlist.
                playlist = {"version": g["PLAYLIST_VERSION"], "revision": 1, "smart_skip": True,
                            "items": [g["default_playlist_item"](page, i) for i, page in enumerate(current["selected_pages"])]}
                g["write_playlist_state"](playlist)
            settings.save(g["DATA_DIR"], {"setup_state": "complete"}, data.get("revision"))
        return {"status": "ok"}

    @app.get("/admin/api/device/token")
    def device_token(request: Request):
        g["require_admin"](request)
        return JSONResponse({"token": g["required_env"]("DEVICE_TOKEN")}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/device/rotate")
    async def rotate(request: Request):
        g["require_csrf"](request)
        with g["STATE_LOCK"]:
            saved = settings.credentials(g["DATA_DIR"])
            saved["DEVICE_TOKEN"] = secrets.token_urlsafe(32)
            settings.atomic_json(g["DATA_DIR"] / "credentials.json", saved)
        return JSONResponse({"token": saved["DEVICE_TOKEN"]}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/password")
    async def change_password(request: Request):
        g["require_csrf"](request)
        g["check_login_rate"](request)
        data = await body(request)
        with g["STATE_LOCK"]:
            if not settings.password_matches(data.get("current"), g["admin_password"]()):
                raise HTTPException(403, detail="当前密码不正确")
            saved = settings.credentials(g["DATA_DIR"])
            saved["ADMIN_PASSWORD_HASH"] = settings.password_hash(data.get("password"))
            settings.atomic_json(g["DATA_DIR"] / "credentials.json", saved)
        return {"status": "ok", "login_required": True}

    @app.get("/admin/api/settings/export")
    def export(request: Request):
        g["require_admin"](request)
        result = copy.deepcopy(g["board_settings"]())
        result.pop("migration", None)
        # A sharable export excludes even location / host identifiers by default.
        result.update(location=None, timezone="UTC", external_base_url="", setup_state="uninitialized", revision=1)
        return JSONResponse(result, headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="kindleglance-preferences.json"'})

    @app.get("/admin/api/diagnostics")
    def diagnostics(request: Request):
        g["require_admin"](request)
        return JSONResponse({"version": "0.2.0-rc.1", "device_profile": "kpw11",
                             "setup_state": g["board_settings"]()["setup_state"],
                             "has_device_fetch": bool((g["read_state"]() or {}).get("last_device_request")),
                             "collector_installed": bool(g["os"].getenv("CODEX_COLLECTOR_URL"))},
                            headers={"Cache-Control": "no-store"})

    search_cache = {}
    search_times = {}

    @app.get("/admin/api/locations")
    async def locations(request: Request, q: str = ""):
        g["require_admin"](request)
        q = place_search.normalize(q)
        if not 2 <= len(q) <= 100:
            raise HTTPException(400, detail="请输入 2–100 个字符")
        now = time.monotonic()
        address = request.client.host if request.client else "local"
        with g["STATE_LOCK"]:
            if now - search_times.get(address, -100) < 1:
                raise HTTPException(429, detail="请稍后再搜索")
            if len(search_times) > 1024:
                search_times.clear()
            search_times[address] = now
            cached = search_cache.get(q)
            if cached and now - cached[0] < 3600:
                return cached[1]
        try:
            found = await asyncio.to_thread(place_search.search, q)
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, detail="城市搜索暂不可用，请手动输入地点与坐标")
        with g["STATE_LOCK"]:
            if len(search_cache) >= 128:
                search_cache.clear()
            if not found['partial']:
                search_cache[q] = (now, found)
        return found
