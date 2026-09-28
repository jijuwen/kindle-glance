-- Persist only bounded, sanitized transport diagnostics; never response bodies.
local D = {}

function D.clean(value, secrets)
    local text = tostring(value or "unknown error")
    for _, secret in ipairs(secrets or {}) do
        if type(secret) == "string" and secret ~= "" then
            text = text:gsub(secret:gsub("(%W)", "%%%1"), "[redacted]")
        end
    end
    text = text:gsub("https?://[^%s]+", "[url]")
        :gsub("%x%x:%x%x:%x%x:%x%x:%x%x:%x%x", "[mac]")
        :gsub("[%c]", " ")
    return text:sub(1, 160)
end

function D.transport(phase, err, secrets)
    local message = D.clean(err, secrets)
    local lower = message:lower()
    local kind = "transport"
    if lower:find("name resolution", 1, true) or lower:find("host not found", 1, true)
        or lower:find("name or service not known", 1, true) or lower:find("getaddrinfo", 1, true) then
        kind = "dns"
    elseif lower:find("timeout", 1, true) or lower:find("timed out", 1, true) then kind = "timeout"
    elseif lower:find("unreachable", 1, true) or lower:find("no route", 1, true) then kind = "route"
    elseif lower:find("refused", 1, true) then kind = "refused"
    elseif lower == "closed" or lower:find("connection reset", 1, true) then kind = "closed"
    elseif lower:find("too large", 1, true) then kind = "size_limit"
    elseif lower:find("ssl", 1, true) or lower:find("tls", 1, true)
        or lower:find("certificate", 1, true) or lower == "wantread" then kind = "tls"
    end
    return {phase = phase, kind = kind, message = message,
        retryable = kind == "dns" or kind == "timeout" or kind == "route" or kind == "refused" or kind == "closed"}
end

function D.http(phase, status)
    local code = tonumber(status)
    return {phase = phase, kind = "http", http_status = code,
        message = "HTTP " .. tostring(code or "unknown"),
        retryable = code == 408 or code == 502 or code == 503 or code == 504}
end

function D.localError(phase, kind, message)
    return {phase = phase, kind = kind, message = message, retryable = false}
end

function D.label(diag)
    if not diag then return "—" end
    if diag.kind == "http" then return diag.message end
    local labels = {dns = "DNS 解析失败", timeout = "请求超时", route = "网络路由不可达",
        refused = "连接被拒绝", closed = "连接中断", tls = "TLS 错误", size_limit = "响应过大",
        transport = "传输错误", json = "响应不是有效 JSON", image_url = "图片地址无效",
        file = "图片文件操作失败", render = "图片绘制失败", exception = "程序异常", auth = "缺少令牌"}
    return labels[diag.kind] or diag.kind
end

return D
