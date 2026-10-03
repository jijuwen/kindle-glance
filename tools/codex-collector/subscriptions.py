"""Read subscription metadata with existing CLI credentials; never refresh tokens here."""
from __future__ import annotations

import base64
from datetime import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

INTERVAL = 3600
MAX_BYTES = 1048576
AUTH_CLAIM = "https://api.openai.com/auth"
SUBSCRIPTIONS = "/backend-api/subscriptions"
ACCOUNTS = "/backend-api/accounts/check/v4-2023-04-27"


class SubscriptionError(Exception):
    """Only fixed, safe error codes may leave the HTTP client."""


def plan_name(raw):
    code = str(raw or "").strip().lower()
    aliases = {
        "prolite": "PRO 5X", "pro-lite": "PRO 5X", "pro-5x": "PRO 5X",
        "codex-pro-5x": "PRO 5X", "pro-100": "PRO 5X", "chatgptprolite": "PRO 5X",
        "pro": "PRO 20X", "pro-20x": "PRO 20X", "codex-pro-20x": "PRO 20X",
        "pro-200": "PRO 20X", "chatgptpro": "PRO 20X",
        "promax": "PRO MAX", "pro-max": "PRO MAX", "pro-500": "PRO MAX", "chatgptpromax": "PRO MAX",
        "plus": "PLUS", "chatgptplusplan": "PLUS", "free": "FREE", "go": "GO",
        "team": "TEAM", "business": "BUSINESS", "enterprise": "ENTERPRISE", "edu": "EDU",
    }
    return aliases.get(code, code.upper() if re.fullmatch(r"[a-z0-9_-]{1,60}", code) else "未知")


def plan_code(raw):
    return raw.lower() if isinstance(raw, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", raw) else None


def timestamp(value):
    if value is None:
        return None
    if type(value) is int:
        result = value
    elif isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo is None or date.utcoffset() is None:
                raise ValueError()
            result = int(date.timestamp())
        except (ValueError, OverflowError):
            raise SubscriptionError("format") from None
    else:
        raise SubscriptionError("format")
    if not 946684800 <= result <= 7258118400:
        raise SubscriptionError("format")
    return result


def flag(value):
    if value is not None and type(value) is not bool:
        raise SubscriptionError("format")
    return value


def empty():
    return dict(plan_code=None, cycle_ends_at=None, entitlement_ends_at=None, active=None,
                will_renew=None, is_delinquent=None, updated_at=None, source="none", status="unknown")


def jwt_claims(token):
    try:
        if not isinstance(token, str) or len(token) > 65536:
            return {}
        part = token.split(".")[1]
        result = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return result if isinstance(result, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def credentials(home):
    try:
        data = json.loads((home / "auth.json").read_text())
        tokens = data.get("tokens") or {}
        token = tokens.get("access_token")
        auth = jwt_claims(token).get(AUTH_CLAIM) or {}
        account_id = tokens.get("account_id") or auth.get("chatgpt_account_id")
        if not isinstance(token, str) or not token or not isinstance(account_id, str) or not account_id:
            raise ValueError()
        if any(ord(c) < 32 for c in token + account_id):
            raise ValueError()
        # A persisted selected workspace must agree with the token, when it names one.
        if auth.get("chatgpt_account_id") and auth["chatgpt_account_id"] != account_id:
            raise SubscriptionError("identity")
        return tokens, token, account_id
    except (OSError, ValueError, TypeError, AttributeError):
        raise SubscriptionError("credentials") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(token, path, query):
    req = urllib.request.Request("https://chatgpt.com" + path + "?" + urllib.parse.urlencode(query),
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 "User-Agent": "KindleGlance/1.0", "Referer": "https://chatgpt.com/",
                 "x-openai-target-path": path, "x-openai-target-route": path})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=12) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SubscriptionError("format")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise SubscriptionError("format")
            return result
    except urllib.error.HTTPError as error:
        code = {401: "unauthorized", 403: "forbidden", 429: "rate_limit"}.get(error.code, "http")
        error.close()
        raise SubscriptionError(code) from None
    except (OSError, urllib.error.URLError):
        raise SubscriptionError("network") from None
    except (ValueError, TypeError):
        raise SubscriptionError("format") from None


def selected_entitlement(payload, account_id):
    records = payload.get("accounts")
    if not isinstance(records, dict):
        raise SubscriptionError("format")
    matches = []
    for key, record in records.items():
        if not isinstance(record, dict):
            continue
        node = record.get("account") or {}
        actual = node.get("account_id") or node.get("id") or node.get("chatgpt_account_id")
        if account_id in (key, actual):
            # Never choose another organization's paid plan as a fallback.
            if actual and actual != account_id:
                raise SubscriptionError("identity")
            entitlement = record.get("entitlement")
            if isinstance(entitlement, dict):
                matches.append(entitlement)
    if not matches:
        raise SubscriptionError("identity")
    if any(item != matches[0] for item in matches[1:]):
        raise SubscriptionError("identity")
    return matches[0]


def fetch(home, observed):
    _, token, account_id = credentials(home)
    primary, entitlement, errors = None, None, []
    try:
        primary = request(token, SUBSCRIPTIONS, {"account_id": account_id})
        # Validate before treating a JSON 200 as usable subscription metadata.
        if "plan_type" not in primary or "is_active" not in primary:
            raise SubscriptionError("format")
        result = dict(plan_code=plan_code(primary["plan_type"]),
                      cycle_ends_at=timestamp(primary.get("active_until")), entitlement_ends_at=None,
                      active=flag(primary["is_active"]), will_renew=flag(primary.get("will_renew")),
                      is_delinquent=flag(primary.get("is_delinquent")),
                      updated_at=observed, source="subscriptions", status="ok")
        if not result["plan_code"] or result["active"] is None:
            raise SubscriptionError("format")
    except SubscriptionError as error:
        primary = None
        errors.append(error)
    try:
        entitlement = selected_entitlement(request(token, ACCOUNTS, {"timezone_offset_min": 0}), account_id)
        if not primary:
            result = dict(plan_code=plan_code(entitlement.get("subscription_plan")),
                          cycle_ends_at=timestamp(entitlement.get("renews_at")), entitlement_ends_at=None,
                          active=flag(entitlement.get("has_active_subscription")), will_renew=None,
                          is_delinquent=flag(entitlement.get("is_delinquent")),
                          updated_at=observed, source="account_check", status="ok")
            if not result["plan_code"] or result["active"] is None:
                raise SubscriptionError("format")
        # Entitlement expiry is a distinct timestamp, not a billing-cycle replacement.
        result["entitlement_ends_at"] = timestamp(entitlement.get("expires_at"))
    except SubscriptionError as error:
        entitlement = None
        errors.append(error)
    if not primary and not entitlement:
        raise errors[0]
    return result


def token_cache(home):
    """Old ID-token claims are explicitly cached evidence, never a new observation."""
    try:
        tokens, _, account_id = credentials(home)
        claims = jwt_claims(tokens.get("id_token"))
        auth = claims.get(AUTH_CLAIM) or {}
        if auth.get("chatgpt_account_id") != account_id:
            return None
        result = empty()
        result.update(plan_code=plan_code(auth.get("chatgpt_plan_type")),
                      cycle_ends_at=timestamp(auth.get("chatgpt_subscription_active_until")),
                      updated_at=timestamp(auth.get("chatgpt_subscription_last_checked") or claims.get("iat")),
                      source="id_token", status="cached")
        return result if result["plan_code"] or result["cycle_ends_at"] else None
    except (SubscriptionError, AttributeError):
        return None


def error_message(error):
    return {"unauthorized": "订阅查询暂未通过认证，等待自动重试", "forbidden": "订阅查询暂受限制，等待自动重试",
            "rate_limit": "订阅查询频率受限，已延长重试间隔", "network": "订阅连接暂不可用，等待自动重试",
            "identity": "订阅账号未能确认，已保留上次数据"}.get(str(error), "订阅查询未成功，等待自动重试")
