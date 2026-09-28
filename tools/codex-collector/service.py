"""Four private Codex logins, serial quota collection, credential-free snapshots."""
from __future__ import annotations

import copy
from datetime import datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
from urllib.parse import urlsplit
import uuid
from zoneinfo import ZoneInfo

from rpc import CodexRPC, RpcError

STATE = Path(os.getenv("COLLECTOR_STATE_DIR", "/state"))
PUBLIC = Path(os.getenv("COLLECTOR_PUBLIC_DIR", "/public"))
SECRET_FILE = Path(os.getenv("COLLECTOR_SECRET_FILE", "/run/secrets/codex-bridge"))
INTERVAL = 900
LOCK = threading.RLock()
WORK = threading.Lock()
SLOTS = {i: threading.Lock() for i in range(1, 5)}
LOGINS = {}
MODEL = {}


def now():
    return int(time.time())


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize():
    global MODEL
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PUBLIC.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STATE / "state.json"
    MODEL = json.loads(path.read_text()) if path.exists() else {
        "version": 1, "enabled": False,
        "slots": [{"slot": i, "bound": False, "email": None, "plan": None,
                   "last_success": None, "last_attempt": None, "next_attempt": 0,
                   "failures": 0, "error": None, "state": "unbound",
                   "expires_at": None, "plan_label": "", "snapshot": None} for i in range(1, 5)],
    }
    for slot in MODEL["slots"]:
        if slot["bound"] and slot["state"] != "reauth_required":
            slot["next_attempt"] = 0
    # Unconfirmed login stages are disposable; they are never active credentials.
    for path in STATE.glob("pending-*"):
        if path.is_dir():
            shutil.rmtree(path)
    persist()


def persist():
    atomic_json(STATE / "state.json", MODEL)


def slot_at(number):
    if number not in SLOTS:
        raise ValueError("账号位置无效")
    return MODEL["slots"][number - 1]


def public_state():
    with LOCK:
        result = {"enabled": MODEL["enabled"], "interval_seconds": INTERVAL, "slots": []}
        for value in MODEL["slots"]:
            slot = {k: copy.deepcopy(v) for k, v in value.items() if k not in ("snapshot", "failures", "next_attempt")}
            snapshot = value.get("snapshot")
            slot["windows"] = snapshot.get("windows", []) if snapshot else []
            slot["reset_credits"] = snapshot.get("reset_credits") if snapshot else None
            session = LOGINS.get(value["slot"])
            slot["login"] = copy.deepcopy(session["public"]) if session else None
            result["slots"].append(slot)
        return result


def publish():
    # Called under LOCK. Never overwrite the legacy Windows snapshot.
    if not MODEL["enabled"]:
        return
    accounts = []
    for slot in MODEL["slots"]:
        if not slot["bound"]:
            continue
        account = copy.deepcopy(slot["snapshot"]) if slot["snapshot"] else {
            "id": f'codex-slot-{slot["slot"]}', "name": slot["email"], "plan": slot["plan"] or "未知",
            "updated_at": None, "expires_at": None, "reset_credits": None, "status": "unknown", "windows": [],
        }
        account["plan"] = slot["plan_label"] or account["plan"]
        account["expires_at"] = slot["expires_at"]
        if slot["state"] == "reauth_required":
            account["status"] = "reauth_required"
        elif slot["state"] == "error":
            account["status"] = "refresh_error"
        accounts.append(account)
    atomic_json(PUBLIC / "ai-accounts.json", {"schema_version": 1, "collected_at": now(), "accounts": accounts})


def identity(account):
    if not isinstance(account, dict) or account.get("type") != "chatgpt" or not account.get("email"):
        raise ValueError("未能确认账号邮箱，请使用有邮箱的 ChatGPT 账号登录")
    return account["email"].strip().casefold()


def normalize(number, account, quotas, timestamp):
    email = identity(account)
    buckets = quotas.get("rateLimitsByLimitId") or {}
    bucket = buckets.get("codex")
    if not bucket:
        fallback = quotas.get("rateLimits")
        if fallback and fallback.get("limitId") in (None, "codex"):
            bucket = fallback
    if not bucket:
        raise ValueError("官方未返回 Codex 额度，稍后重试")
    windows = []
    for key in ("primary", "secondary"):
        window = bucket.get(key)
        if not window:
            continue
        duration = window.get("windowDurationMins")
        label = "周额度" if duration == 10080 else f"{duration // 60}小时" if isinstance(duration, int) and duration > 0 and duration % 60 == 0 else f"{duration}分钟" if duration else ("主额度" if key == "primary" else "次额度")
        used = window.get("usedPercent")
        if used is not None and (type(used) not in (float, int) or not math.isfinite(used) or not 0 <= used <= 100):
            raise ValueError("额度格式异常，已保留上次有效数据")
        reset = window.get("resetsAt")
        if reset is not None and (type(reset) is not int or not 946684800 <= reset <= 7258118400):
            raise ValueError("重置时间异常，已保留上次有效数据")
        windows.append({"label": label, "remaining_percent": round(100 - used, 2) if used is not None else None, "reset_at": reset})
    if not windows:
        raise ValueError("官方未返回额度窗口，已保留上次有效数据")
    credits = quotas.get("rateLimitResetCredits")
    count = credits.get("availableCount") if isinstance(credits, dict) else None
    if type(count) is not int or count < 0:
        count = None
    return {"id": f"codex-slot-{number}", "name": email,
            "plan": str(bucket.get("planType") or account.get("planType") or "未知").upper(),
            "updated_at": timestamp, "expires_at": None, "reset_credits": count,
            "status": "ok", "windows": windows}


def safe_error(error):
    # Never forward raw OAuth errors, tokens, URLs, or process output to a browser/log.
    message = str(error).lower()
    if any(s in message for s in ("401", "unauthorized", "refresh_token", "reauth", "not logged", "not authenticated")):
        return "reauth_required", "登录已失效，请重新授权"
    if any(s in message for s in ("429", "too many", "rate limit")):
        return "error", "查询受到限制，已延长重试间隔"
    if "device" in message and any(s in message for s in ("disabled", "enable", "not allowed")):
        return "error", "请在 ChatGPT 安全设置中开启设备码登录后重试"
    if any(s in message for s in ("timeout", "connection", "connect", "dns", "proxy", "network")):
        return "error", "连接超时或代理暂不可用，稍后重试"
    if isinstance(error, ValueError):
        return "error", str(error)
    return "error", "官方请求未成功，请稍后重试；必要时检查账号登录设置"


def sync_slot(number):
    if not SLOTS[number].acquire(blocking=False):
        return
    rpc = None
    try:
        with WORK:
            with LOCK:
                slot = slot_at(number)
                if not slot["bound"]:
                    return
                slot["last_attempt"] = now()
                slot["state"] = "syncing"
                persist()
            rpc = CodexRPC(STATE / f"account-{number}")
            account = rpc.call("account/read", {"refreshToken": False}).get("account")
            if not account:
                raise RpcError("not logged in")
            if identity(account) != slot["email"].casefold():
                raise RpcError("reauth: identity mismatch")
            snapshot = normalize(number, account, rpc.call("account/rateLimits/read"), now())
            with LOCK:
                slot.update(snapshot=snapshot, plan=snapshot["plan"], last_success=snapshot["updated_at"],
                            state="ok", error=None, failures=0, next_attempt=now() + INTERVAL)
                persist()
                publish()
    except Exception as error:
        state, message = safe_error(error)
        with LOCK:
            slot = slot_at(number)
            slot["failures"] += 1
            delay = min(21600, INTERVAL * 2 ** min(slot["failures"], 4))
            slot.update(state=state, error=message, next_attempt=now() + delay)
            persist()
            publish()
    finally:
        if rpc:
            rpc.close()
        SLOTS[number].release()


def start_login(number):
    with LOCK:
        for existing in LOGINS.values():
            if existing["public"]["state"] in ("starting", "waiting", "ready"):
                raise ValueError("请先完成或取消当前授权，再添加其他账号")
        session = {"cancel": threading.Event(), "public": {"state": "starting", "expires_at": now() + 900},
                   "path": STATE / ("pending-" + uuid.uuid4().hex), "snapshot": None, "account": None}
        LOGINS[number] = session
    threading.Thread(target=login_worker, args=(number, session), daemon=True).start()


def login_worker(number, session):
    rpc = None
    try:
        # Limit heavyweight app-server processes even during interactive login.
        with WORK:
            if session["cancel"].is_set():
                return
            rpc = CodexRPC(session["path"])
            result = rpc.call("account/login/start", {"type": "chatgptDeviceCode"}, 60)
            target = urlsplit(result.get("verificationUrl", ""))
            if target.scheme != "https" or target.hostname not in ("auth.openai.com", "chatgpt.com"):
                raise ValueError("官方授权地址未通过校验")
            with LOCK:
                session["public"].update(state="waiting", verification_url=result["verificationUrl"], code=result["userCode"])
            while now() < session["public"]["expires_at"] and not session["cancel"].is_set():
                completed = rpc.login_completed(result["loginId"], 1)
                if completed:
                    if not completed.get("success"):
                        raise RpcError(completed.get("error") or "login failed")
                    account = rpc.call("account/read", {"refreshToken": False}).get("account")
                    email = identity(account)
                    with LOCK:
                        if any(s["bound"] and s["slot"] != number and s["email"].casefold() == email for s in MODEL["slots"]):
                            raise ValueError("这个账号已绑定其他栏位，请换一个账号登录")
                        previous = slot_at(number)
                        if previous["bound"] and previous["email"].casefold() != email:
                            raise ValueError("重新授权的账号与原账号不同；如需更换，请先解除绑定")
                    quota_error = None
                    try:
                        snapshot = normalize(number, account, rpc.call("account/rateLimits/read"), now())
                    except Exception as error:
                        snapshot = None
                        quota_error = safe_error(error)[1]
                    # Finish token persistence before exposing the confirmation button.
                    rpc.close()
                    rpc = None
                    with LOCK:
                        if session["cancel"].is_set():
                            return
                        session.update(account=account, snapshot=snapshot)
                        session["public"] = {"state": "ready", "email": email,
                                             "plan": str(account.get("planType") or "未知").upper(),
                                             "windows": snapshot["windows"] if snapshot else [],
                                             "error": quota_error, "expires_at": now() + 900}
                    return
            with LOCK:
                session["public"] = {"state": "cancelled" if session["cancel"].is_set() else "expired"}
    except Exception as error:
        with LOCK:
            session["public"] = {"state": "cancelled"} if session["cancel"].is_set() else {"state": "error", "error": safe_error(error)[1]}
    finally:
        if rpc:
            rpc.close()
        # A ready stage must remain available for explicit identity confirmation.
        if session["public"]["state"] != "ready" or session["cancel"].is_set():
            shutil.rmtree(session["path"], ignore_errors=True)


def confirm_login(number):
    with SLOTS[number], LOCK:
        session = LOGINS.get(number)
        if not session or session["public"]["state"] != "ready" or session["public"]["expires_at"] < now():
            raise ValueError("授权已过期，请重新开始")
        email = identity(session["account"])
        if any(s["bound"] and s["slot"] != number and s["email"].casefold() == email for s in MODEL["slots"]):
            raise ValueError("这个账号已绑定其他栏位")
        target = STATE / f"account-{number}"
        # Replace only the token file; retained backups must never keep live tokens.
        target.mkdir(mode=0o700, exist_ok=True)
        os.replace(session["path"] / "auth.json", target / "auth.json")
        os.chmod(target / "auth.json", 0o600)
        slot = slot_at(number)
        slot.update(bound=True, email=email, plan=session["public"]["plan"], error=session["public"].get("error"),
                    state="ok" if session["snapshot"] else "error", failures=0, next_attempt=now() + (INTERVAL if session["snapshot"] else 60),
                    snapshot=session["snapshot"], last_success=session["snapshot"]["updated_at"] if session["snapshot"] else None,
                    last_attempt=now())
        shutil.rmtree(session["path"], ignore_errors=True)
        del LOGINS[number]
        persist()
        publish()


def action(number, name, body):
    with LOCK:
        slot_at(number)
    if name == "login":
        start_login(number)
    elif name == "confirm":
        confirm_login(number)
    elif name == "cancel":
        with LOCK:
            session = LOGINS.get(number)
            if session:
                session["cancel"].set()
                if session["public"]["state"] == "ready":
                    shutil.rmtree(session["path"], ignore_errors=True)
                    session["public"] = {"state": "cancelled"}
    elif name == "sync":
        with LOCK:
            slot = slot_at(number)
            if not slot["bound"]:
                raise ValueError("请先授权账号")
            if slot["state"] == "reauth_required":
                raise ValueError("请先重新授权")
            if slot["last_attempt"] and now() - slot["last_attempt"] < 60:
                raise ValueError("刚刚查询过，请稍后再试")
            if slot["failures"] and slot["next_attempt"] > now():
                raise ValueError("正在等待重试，请勿连续刷新")
            slot["next_attempt"] = 0
            persist()
    elif name == "metadata":
        label = body.get("plan_label", "")
        expiry = body.get("expires_at")
        if not isinstance(label, str) or len(label) > 40 or any(ord(c) < 32 for c in label):
            raise ValueError("套餐备注最多 40 个字符")
        if expiry is not None and (type(expiry) is not int or not 946684800 <= expiry <= 7258118400):
            raise ValueError("订阅到期时间无效")
        with LOCK:
            slot = slot_at(number)
            slot.update(plan_label=label.strip(), expires_at=expiry)
            persist()
            publish()
    elif name == "unlink":
        with SLOTS[number], LOCK:
            session = LOGINS.get(number)
            if session:
                session["cancel"].set()
                if session["public"]["state"] == "ready":
                    shutil.rmtree(session["path"], ignore_errors=True)
                # A worker still acquiring a device code must unwind before another starts.
                if session["public"]["state"] not in ("starting", "waiting"):
                    session["public"] = {"state": "cancelled"}
            shutil.rmtree(STATE / f"account-{number}", ignore_errors=True)
            slot = slot_at(number)
            slot.update(bound=False, email=None, plan=None, state="unbound", snapshot=None, error=None,
                        last_success=None, last_attempt=None, failures=0, next_attempt=0, expires_at=None, plan_label="")
            persist()
            publish()
    else:
        raise ValueError("不支持的操作")


def scheduler():
    while True:
        try:
            with LOCK:
                due = [s["slot"] for s in MODEL["slots"] if s["bound"] and s["state"] != "reauth_required" and s["next_attempt"] <= now()]
                for session in LOGINS.values():
                    if session["public"]["state"] == "ready" and session["public"]["expires_at"] < now():
                        shutil.rmtree(session["path"], ignore_errors=True)
                        session["public"] = {"state": "expired"}
            for number in due:
                sync_slot(number)
        except Exception:
            print("collector scheduler error; retrying", flush=True)
        time.sleep(3)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        token = SECRET_FILE.read_text().strip()
        return bool(token) and hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if not self.authorized():
            return self.respond(401, {"detail": "unauthorized"})
        if self.path != "/state":
            return self.respond(404, {"detail": "not found"})
        self.respond(200, public_state())

    def do_POST(self):
        if not self.authorized():
            return self.respond(401, {"detail": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4096:
                return self.respond(413, {"detail": "request too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("请求格式无效")
            if self.path == "/enable":
                with LOCK:
                    if not any(s["bound"] and s["last_success"] for s in MODEL["slots"]):
                        raise ValueError("请先授权至少一个账号并成功查询额度")
                    MODEL["enabled"] = True
                    persist()
                    publish()
            else:
                match = re.fullmatch(r"/slots/([1-4])/(login|confirm|cancel|sync|metadata|unlink)", self.path)
                if not match:
                    return self.respond(404, {"detail": "not found"})
                action(int(match[1]), match[2], body)
            self.respond(200, public_state())
        except (ValueError, TypeError):
            import sys
            self.respond(400, {"detail": str(sys.exception()) if isinstance(sys.exception(), ValueError) else "请求格式无效"})
        except Exception:
            self.respond(503, {"detail": "采集服务暂不可用，请稍后重试"})


if __name__ == "__main__":
    os.umask(0o077)
    initialize()
    threading.Thread(target=scheduler, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
