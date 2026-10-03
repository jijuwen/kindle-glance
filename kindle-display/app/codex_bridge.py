"""Authenticated admin-only bridge. OAuth credentials remain in the collector."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from fastapi import HTTPException


def collector_request(path, body=None):
    base = os.getenv("CODEX_COLLECTOR_URL", "http://codex-usage-collector:8091")
    try:
        secret = Path(os.getenv("CODEX_COLLECTOR_SECRET_FILE", "/run/secrets/codex-bridge")).read_text().strip()
        request = urllib.request.Request(base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"})
        # An internal request must never inherit the outbound proxy.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 400:
            raise HTTPException(400, detail=json.load(error).get("detail", "请求无效"))
        raise HTTPException(503, detail="账号采集服务暂不可用，请稍后重试")
    except (OSError, ValueError):
        raise HTTPException(503, detail="账号采集服务暂不可用，请稍后重试")


def install_routes(app, require_admin, require_csrf, board_settings):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/admin/api/codex/accounts")
    def codex_accounts(request: Request):
        require_admin(request)
        if not os.getenv("CODEX_COLLECTOR_URL"):
            return JSONResponse({"installed": False, "enabled": False, "slots": []}, headers={"Cache-Control": "no-store"})
        return JSONResponse({**collector_request("/state"), "installed": True}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/codex/enable")
    def codex_enable(request: Request):
        require_csrf(request)
        return JSONResponse(collector_request("/enable", {}), headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/codex/accounts/{slot}/{action}")
    async def codex_action(slot: int, action: str, request: Request):
        require_csrf(request)
        if slot not in range(1, 5) or action not in {"login", "cancel", "confirm", "sync", "unlink"}:
            raise HTTPException(404, detail="操作不存在")
        raw = await request.body()
        if len(raw) > 4096:
            raise HTTPException(413, detail="请求过大")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(400, detail="请求格式无效")
        if not isinstance(body, dict):
            raise HTTPException(400, detail="请求格式无效")
        import asyncio
        result = await asyncio.to_thread(collector_request, f"/slots/{slot}/{action}", body)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
