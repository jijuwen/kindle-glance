package.path = "kindle-plugin/trmnl.koplugin/?.lua;" .. package.path
local now = 2000000
os.time = function() return now end
local logger = {info = function() end, warn = function() end, dbg = function() end}
package.loaded.logger = logger
package.loaded["ffi/rtc"] = {secondsFromNowToEpoch = function(_, seconds) return now + seconds end}
local WakeupMgr = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/wakeupmgr.lua")
local Runner = require("trmnl_rtc_refresh")
local checks = 0
local function check(value, message) assert(value, message); checks = checks + 1 end
local function fixture(options)
    options = options or {}
    local f = {fetches = 0, enables = 0, disables = 0, sleeps = 0, toggles = 0, wifi = false}
    f.store = {
        data = options.saved or {},
        readSetting = function(self, key) return self.data[key] end,
        saveSetting = function(self, key, value) self.data[key] = value end,
        flush = function() end,
    }
    f.mgr = WakeupMgr:new{rtc = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/kindle/mockrtc.lua")}
    f.device = {screen_saver_mode = false, wakeup_mgr = f.mgr, powerd = {}}
    f.device.powerd.getPowerdState = function() return f.device.screen_saver_mode and "screenSaver" or "active" end
    f.device.powerd.toggleSuspend = function()
        f.toggles = f.toggles + 1
        f.device.screen_saver_mode = false
        f.runner:onResume()
    end
    f.ui = {
        tasks = {},
        scheduleIn = function(self, delay, fn) self.tasks[fn] = now + delay end,
        unschedule = function(self, fn) self.tasks[fn] = nil end,
        suspend = function()
            f.sleeps = f.sleeps + 1
            f.device.screen_saver_mode = true
            f.runner:onSuspend()
        end,
    }
    f.network = {
        restoreWifiAsync = function() f.enables = f.enables + 1; f.wifi = true end,
        isWifiOn = function() return f.wifi end,
        isConnected = function() return options.connected ~= false and not f.connection_lost end,
        disableWifi = function()
            f.disables = f.disables + 1
            if not options.disable_fails then f.wifi = false end
        end,
    }
    f.share = {}
    f.runner = Runner:new{
        device = f.device, ui = f.ui, network = f.network, share = f.share,
        store = f.store, logger = logger, suspend_seconds = function() return 110 end,
        fetch = function(mark)
            f.fetches = f.fetches + 1
            if options.fetch then return options.fetch(f.fetches) end
            if options.exception then error("test fetch exception") end
            if options.fetch_error then return options.fetch_error, options.diagnostic end
            mark("metadata_at"); mark("downloaded_at"); mark("displayed_at")
            return true
        end,
    }
    function f.advance(target)
        while true do
            local first, at
            for fn, timestamp in pairs(f.ui.tasks) do
                if timestamp <= target and (not at or timestamp < at) then first, at = fn, timestamp end
            end
            if not first then break end
            f.ui.tasks[first] = nil
            now = at
            first()
        end
        now = target
    end
    function f.fire()
        local target = f.mgr._task_queue[1].epoch
        f.advance(target + 5)
        check(f.mgr:wakeupAction(90), "real WakeupMgr delivers alarm")
        f.advance(now)
    end
    return f
end

local f = fixture()
check(f.runner:arm(900), "arms one-shot update")
check(not f.runner:arm(900), "rejects duplicate start")
local other = function() end
f.mgr:addTask(1800, other)
f.fire()
f.advance(now + 10)
check(f.fetches == 0, "waits for ten continuous connected seconds before requesting")
f.advance(now + 10)
check(f.fetches == 1 and f.enables == 1, "one fetch and one radio enable")
check(f.disables == 1 and not f.wifi, "radio switched off after update")
check(f.sleeps == 2 and f.toggles == 1, "one explicit wake, initial and final sleep requests")
check(f.share.pause_auto_suspend == nil, "temporary autosuspend pause released")
check(f.runner.result.state == "checking_sleep", "waits for second RTC check")
check(f.mgr._task_queue[1].callback == f.runner.verify_alarm, "secondary alarm queued after first callback returned")
f.fire()
check(f.runner.result.state == "verified" and f.runner.result.outcome == "updated", "update and second alarm complete")
check(f.runner.result.observed_suspend_seconds == 110 and f.runner.result.verify_wifi_off, "records suspend span and radio status")
check(f.fetches == 1 and f.toggles == 1 and f.sleeps == 2, "verification callback has no network or power toggle side effect")
check(#f.mgr._task_queue == 1 and f.mgr._task_queue[1].callback == other, "other plugin's RTC task preserved")

f = fixture{connected = false}
f.runner:arm(900); f.fire(); f.advance(now + 60)
check(f.fetches == 0 and f.runner.result.outcome == "wifi_timeout", "unavailable AP times out without fetching")
check(not f.wifi and f.sleeps == 2, "timeout cleans radio and requests sleep")
f.fire()
check(f.runner.result.outcome == "wifi_timeout", "sleep verification does not hide network failure")

for _, options in ipairs({{exception = true}, {fetch_error = "render_failed"}}) do
    f = fixture(options)
    f.runner:arm(900); f.fire(); f.advance(now + 20)
    check(not f.wifi and f.share.pause_auto_suspend == nil and f.sleeps == 2, "fetch failure releases resources and sleeps")
    check(f.runner.result.outcome == (options.exception and "fetch_exception" or "render_failed"), "failure cause retained")
end

f = fixture{connected = false}
f.runner:arm(900); f.fire(); f.advance(now + 2)
f.runner:cancel("cancelled"); f.advance(now + 100)
check(f.fetches == 0 and not f.wifi and f.share.pause_auto_suspend == nil, "mid-connection cancellation prevents late fetch")
check(#f.mgr._task_queue == 0, "cancellation removes owned alarms")

f = fixture{disable_fails = true}
f.runner:arm(900); f.fire(); f.advance(now + 30)
check(f.runner.result.wifi_off_failed and f.disables == 3, "radio failure has bounded retries")
f.fire()
check(not f.runner.result.verify_wifi_off, "does not claim radio is off after disable failure")

f = fixture{saved = {result = {running = true, state = "connecting"}}}
check(f.runner.result.state == "interrupted" and not f.runner.active and #f.mgr._task_queue == 0, "restart never launches unattended work")

local D = require("trmnl_diagnostics")
f = fixture{fetch = function(attempt)
    if attempt < 3 then return "metadata_failed", D.transport("metadata", "Network is unreachable") end
    return true
end}
f.runner:arm(900); f.fire(); f.advance(now + 35)
check(f.fetches == 3 and f.runner.result.outcome == "updated", "transient API failures can recover on third attempt")
local attempts = f.runner.result.attempts
check(attempts[2].started_at - attempts[1].finished_at == 5 and attempts[3].started_at - attempts[2].finished_at == 10,
    "retry backoff is exactly five then ten seconds")
check(attempts[1].diagnostic.kind == "route" and not f.runner.result.last_error, "history keeps earlier failures but successful last attempt clears error")
check(not f.wifi and f.sleeps == 2, "recovered request still cleans up and sleeps")

f = fixture{fetch_error = "metadata_failed", diagnostic = D.transport("metadata", "Temporary failure in name resolution")}
f.runner:arm(900); f.fire(); f.advance(now + 80)
check(f.fetches == 3 and f.runner.result.last_error.kind == "dns", "persistent DNS failure stops at three attempts")
check(f.runner.result.state == "checking_sleep" and not f.wifi, "exhausted retries shut radio down and return to sleep")
f.fire()
check(f.runner.result.state == "verified" and f.runner.result.outcome == "metadata_failed", "sleep check preserves final transfer failure")

for _, item in ipairs({{"metadata_failed", D.http("metadata", 401)}, {"metadata_failed", D.http("metadata", 403)},
    {"metadata_failed", D.localError("metadata", "json", "invalid JSON")},
    {"metadata_failed", D.transport("metadata", "unknown library error")},
    {"download_failed", D.transport("image", "timeout")}}) do
    f = fixture{fetch_error = item[1], diagnostic = item[2]}
    f.runner:arm(900); f.fire(); f.advance(now + 60)
    check(f.fetches == 1 and not f.wifi, "nonretryable API errors and image errors never re-request metadata")
end

f = fixture{fetch_error = "metadata_failed", diagnostic = D.http("metadata", 503)}
f.runner:arm(900); f.fire(); f.advance(now + 12)
check(f.fetches == 1, "first request completes before retry backoff")
f.runner:cancel("cancelled"); f.advance(now + 80)
check(f.fetches == 1 and not f.wifi and f.share.pause_auto_suspend == nil, "cancellation during backoff cancels pending retry and releases pause")

f = fixture()
f.runner:arm(900); f.fire(); f.advance(now + 5)
f.connection_lost = true; f.advance(now + 2)
f.connection_lost = false; f.advance(now + 9)
check(f.fetches == 0, "brief link loss restarts stability countdown")
f.advance(now + 5)
check(f.fetches == 1, "stable link resumes one fetch after countdown")

check(D.transport("metadata", "timeout").retryable and D.http("metadata", 503).retryable, "known transient transport and gateway errors retry")
check(not D.http("metadata", 429).retryable and not D.http("metadata", 401).retryable, "rate limit and authentication errors do not blindly retry")
local clean = D.clean("failed https://example.invalid/image?signature=secret token a.b%+ 70:70:AA:D2:2A:3C\n", {"a.b%+"})
check(not clean:find("signature", 1, true) and not clean:find("a.b%+", 1, true) and not clean:find("70:70", 1, true), "diagnostics redact signed URL, literal token, and MAC")
check(#D.clean(string.rep("x", 400)) == 160, "diagnostic messages have bounded size")

-- Test the integrated transfer adapter: staged file replacement and timeout cleanup.
local plugin = dofile("kindle-plugin/tests/stage1.lua")
local realMetadata = plugin.fetchScreenMetadata
local socketutil = {block_timeout = 60, total_timeout = -1}
function socketutil:set_timeout(block, total) self.block_timeout = block; self.total_timeout = total end
package.loaded.socketutil = socketutil
package.loaded.datastorage.getDataDir = function() return "/fixture" end
plugin.fetchScreenMetadata = function() return {image_url = "https://example.invalid/test.png", filename = "test.png"} end
plugin.downloadImage = function() return true end
plugin.displayImage = function() return true end
local rename, remove = os.rename, os.remove
local removed = {}
os.rename = function() return true end
os.remove = function(path) removed[#removed + 1] = path; return true end
local stages = {}
check(plugin:performRtcFetch(function(key) stages[key] = true end) == true, "integrated transfer reports success")
check(stages.metadata_at and stages.downloaded_at and stages.displayed_at, "records all transfer steps")
check(plugin.last_image_path == "/fixture/trmnl-rtc-a.png" and plugin.last_image_filename == nil, "does not poison manual cache with fixed slot path")
plugin.downloadImage = function() return false end
check(plugin:performRtcFetch(function() end) == "download_failed", "failed download reported")
check(plugin.last_image_path == "/fixture/trmnl-rtc-a.png", "failed update preserves previous displayed file")
check(removed[#removed] == "/fixture/trmnl-rtc-b.png.part", "only incomplete owned file cleaned")
plugin.fetchScreenMetadata = function() error("test metadata exception") end
check(plugin:performRtcFetch(function() end) == "fetch_exception", "exception reported")
check(socketutil.block_timeout == 60 and socketutil.total_timeout == -1 and not plugin.rtc_network, "socket globals and silent flag restored after exception")
os.rename, os.remove = rename, remove

-- Exercise the actual metadata adapter, not just a mocked fetch, including the
-- previously missing second return value from LuaSocket's protected request.
local device = package.loaded.device
device.hasBattery = function() return false end
device.screen.getWidth = function() return 1236 end
device.screen.getHeight = function() return 1648 end
package.loaded.logger.err = function() end
local requested = 0
local response_code, transport_error = nil, "Network is unreachable"
local body = "{}"
local function request(args)
    requested = requested + 1
    if response_code then args.sink(body); return 1, response_code end
    return nil, transport_error
end
package.loaded["socket.url"] = {parse = function(value)
    local scheme, host = value:match("^(https?)://([^/]+)")
    return {scheme=scheme, host=host}
end}
package.loaded["socket.http"] = {request = request}
package.loaded["ssl.https"] = {request = request}
local function table_sink(t) return function(chunk) if chunk then t[#t + 1] = chunk end; return 1 end end
package.loaded.ltn12 = {sink = {table = table_sink}}
socketutil.table_sink = table_sink
package.loaded.json = {decode = function() return {image_url = "https://example.invalid/image.png"} end}
plugin.settings.api_key = "test-only-token"
plugin.settings.base_url = "http://example.invalid"
plugin.settings.mac_address = "test-mac"
plugin.fetchScreenMetadata = realMetadata
plugin.rtc_network = true
local value, diag = plugin:fetchScreenMetadata()
check(not value and diag.kind == "route" and diag.message == transport_error, "real adapter retains LuaSocket error instead of nil")
transport_error = "failed https://example.invalid/?token=test-only-token test-only-token"
value, diag = plugin:fetchScreenMetadata()
check(not diag.message:find("test-only-token", 1, true), "real adapter redacts configured API key")
response_code = 401
value, diag = plugin:fetchScreenMetadata()
check(not value and diag.http_status == 401 and not diag.retryable, "real adapter distinguishes authentication response")
response_code = 503
value, diag = plugin:fetchScreenMetadata()
check(not value and diag.http_status == 503 and diag.retryable, "real adapter identifies retryable gateway response")
response_code = 200
package.loaded.json.decode = function() error("invalid JSON body") end
value, diag = plugin:fetchScreenMetadata()
check(not value and diag.kind == "json" and not diag.message:find("invalid JSON body", 1, true), "JSON failure does not persist response or parser payload")
plugin.rtc_network = false
package.loaded["ui/widget/textviewer"] = {new = function(_, v) return v end}
plugin.rtc_refresh.result = {version = "2-r2", attempts = {{started_at = os.time(), finished_at = os.time(),
    outcome = "metadata_failed", diagnostic = D.transport("metadata", "Network is unreachable")}}}
plugin:showRtcNetworkDiagnostics()
check(package.loaded["ui/uimanager"].last_widget.text:find("Network is unreachable", 1, true), "scrollable diagnostics page includes exact safe error")
print("PASS: " .. checks .. " stage-2 checks + stage-1 regression checks")
