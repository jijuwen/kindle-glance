-- TLS chain and hostname verification before any HTTP headers are sent.
-- LuaSec https.request does not verify hostname by itself on older releases.
local Transport = {}

function Transport.matchesHost(cert, host)
    if type(host) ~= "string" or host:find("%z") then return false end
    host = host:lower():gsub("%.$", "")
    local ok, extensions = pcall(function() return cert:extensions() end)
    if not ok or type(extensions) ~= "table" then return false end
    local san = extensions["2.5.29.17"] or {}
    local is_ip = host:match("^%d+%.%d+%.%d+%.%d+$") or host:find(":", 1, true)
    if is_ip then
        for _, value in ipairs(san.iPAddress or {}) do
            if value:lower() == host then return true end
        end
        return false
    end
    for _, value in ipairs(san.dNSName or {}) do
        local name = value:lower()
        if not name:find("%z") then
            if name == host then return true end
            -- Only a complete leftmost DNS label may be a wildcard.
            if name:sub(1, 2) == "*." and not name:sub(3):find("*", 1, true) then
                local suffix = name:sub(2)
                local first = host:sub(1, #host - #suffix)
                if #first > 0 and not first:find(".", 1, true) and host:sub(-#suffix) == suffix
                    and name:sub(3):find(".", 1, true) then return true end
            end
        end
    end
    -- No CN fallback: certificates must have Subject Alternative Names.
    return false
end

function Transport.caFile(custom)
    for _, path in ipairs({custom or "", "./data/ca-bundle.crt", "/mnt/us/koreader/data/ca-bundle.crt", "./common/turbo/ca-certificates.crt",
        "/mnt/us/koreader/common/turbo/ca-certificates.crt", "/etc/ssl/certs/ca-certificates.crt"}) do
        if path ~= "" then
            local file = io.open(path, "rb")
            if file then file:close(); return path end
        end
    end
end

function Transport.request(request, custom_ca)
    local http = require("socket.http")
    local url = require("socket.url").parse(request.url)
    if not url or not url.host or url.user or url.password or (url.scheme ~= "http" and url.scheme ~= "https") then
        return nil, "invalid server URL"
    end
    request.redirect = false -- no token forwarding or HTTPS downgrade
    if url.scheme == "http" then return http.request(request) end
    if http.PROXY or request.proxy then return nil, "TLS proxy is unsupported" end
    local ca = Transport.caFile(custom_ca)
    if not ca then return nil, "CA bundle unavailable; configure a trusted CA file" end
    local https = require("ssl.https")
    if not https.tcp then return nil, "LuaSec TLS transport unavailable" end
    request.verify = "peer"
    request.cafile = ca
    request.options = {"all", "no_sslv2", "no_sslv3", "no_tlsv1", "no_tlsv1_1"}
    request.mode = "client"
    local create = https.tcp(request)
    request.create = function()
        local connection = create()
        local connect = connection.connect
        connection.connect = function(self, host, port)
            local result, err = connect(self, host, port)
            if not result then return result, err end
            local cert = self:getpeercertificate()
            if not cert or not Transport.matchesHost(cert, url.host) then
                self:close()
                return nil, "TLS hostname mismatch"
            end
            return result
        end
        return connection
    end
    local ok, result, status, headers = pcall(http.request, request)
    if not ok then return nil, "TLS connection failed" end
    return result, status, headers
end

return Transport
