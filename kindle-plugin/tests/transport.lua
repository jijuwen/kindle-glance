package.path = "kindle-plugin/trmnl.koplugin/?.lua;" .. package.path
local T = require("trmnl_transport")
local checks = 0
local function check(value, message) assert(value, message); checks = checks + 1 end
local function cert(names, ips) return {extensions=function() return {["2.5.29.17"]={dNSName=names,iPAddress=ips}} end} end
check(T.matchesHost(cert({"board.example.com"}), "board.example.com"), "exact SAN")
check(T.matchesHost(cert({"*.example.com"}), "board.example.com"), "whole left-label wildcard")
check(not T.matchesHost(cert({"*.example.com"}), "a.b.example.com"), "no multi-label wildcard")
check(not T.matchesHost(cert({"*.com"}), "example.com"), "no public suffix wildcard")
check(not T.matchesHost(cert({"board.example.com\0.attacker.test"}), "board.example.com"), "no NUL truncation")
check(not T.matchesHost(cert({"wrong.example.com"}), "board.example.com"), "wrong name refused")
check(not T.matchesHost(cert({"127.0.0.1"}), "127.0.0.1"), "IP must use IP SAN")
check(T.matchesHost(cert({}, {"127.0.0.1"}), "127.0.0.1"), "IP SAN match")
package.loaded["socket.url"]={parse=function(value) return {scheme=value:match("^(%a+)"),host="board.example.com"} end}
local active_cert = cert({"board.example.com"})
local sent, closed = false, false
package.loaded["ssl.https"]={tcp=function(params)
    check(params.verify=="peer" and params.cafile=="fixture-ca", "peer verification and explicit CA")
    return function() return {connect=function() return 1 end,
        getpeercertificate=function() return active_cert end,close=function() closed=true end} end
end}
package.loaded["socket.http"]={request=function(req)
    check(req.redirect==false, "redirects disabled")
    local conn=req.create()
    local ok,err=conn:connect("board.example.com",443)
    if not ok then return nil,err end
    sent=true
    return 1,200
end}
T.caFile=function() return "fixture-ca" end
local ok,status=T.request({url="https://board.example.com/api/display"})
check(ok==1 and status==200 and sent,"valid peer sends request")
sent=false;active_cert=cert({"attacker.test"})
ok,status=T.request({url="https://board.example.com/api/display"})
check(not ok and status=="TLS hostname mismatch" and closed and not sent,"bad hostname closed before HTTP headers")
T.caFile=function() return nil end
ok,status=T.request({url="https://board.example.com/api/display"})
check(not ok and status:find("CA bundle"),"missing trust fails closed")
print("PASS: "..checks.." TLS transport checks")
