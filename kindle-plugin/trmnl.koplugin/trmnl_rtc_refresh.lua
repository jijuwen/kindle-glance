-- Stage 2: one RTC fetch, followed by a second, network-free RTC sleep check.
local Runner = {}
Runner.__index = Runner
local Diagnostics = require("trmnl_diagnostics")

function Runner:new(options)
    local self = setmetatable(options, Runner)
    self.now = self.now or os.time
    self.active = false
    self.tasks = {}
    self.result = self.store:readSetting("result") or {state = "idle"}
    if self.result.running then
        self.result.running = false
        self.result.state = "interrupted"
        self:_save()
    end
    self.alarm = function() self:_alarm() end
    self.verify_alarm = function() self:_verify() end
    return self
end

function Runner:_save()
    local ok = pcall(function()
        self.store:saveSetting("result", self.result)
        self.store:flush()
    end)
    if not ok then self.logger.warn("TRMNL RTC2: result storage failed") end
end

function Runner:mark(key, value)
    self.result[key] = value or self.now()
    self:_save()
    self.logger.info("TRMNL RTC2:", key, self.result[key])
end

function Runner:_later(delay, callback)
    local fn
    fn = function()
        self.tasks[fn] = nil
        if self.active then callback() end
    end
    self.tasks[fn] = true
    self.ui:scheduleIn(delay, fn)
end

function Runner:_state()
    local ok, state = pcall(function() return self.device.powerd:getPowerdState() end)
    return ok and state or "unknown"
end

function Runner:_releasePause()
    if self.owns_pause then
        self.share.pause_auto_suspend = self.previous_pause
        self.owns_pause = false
    end
end

function Runner:arm(delay)
    if self.active or not self.device.wakeup_mgr or type(delay) ~= "number" or delay < 120 then return false end
    self.active = true
    self.wifi_owned = false
    self.connected_since = nil
    self.result = {version = "2-r2", state = "armed", running = true, attempts = {}, attempt_count = 0,
        armed_at = self.now(), target_at = self.now() + delay}
    local ok = pcall(function() self.device.wakeup_mgr:addTask(delay, self.alarm) end)
    if not ok then self:cancel("alarm_failed"); return false end
    self:_save()
    self:_later(2, function()
        if not self.device.screen_saver_mode then self.ui:suspend() end
    end)
    return true
end

function Runner:_alarm()
    if not self.active or self.result.state ~= "armed" then return end
    self.result.state = "waking"
    self:mark("rtc_at")
    -- Do all subsequent work after WakeupMgr has removed this callback's entry.
    self:_later(0, function()
        local state = self:_state()
        if not self.device.screen_saver_mode or (state ~= "screenSaver" and state ~= "suspended") then
            self:cancel("user_resumed")
            return
        end
        self.previous_pause = self.share.pause_auto_suspend
        self.share.pause_auto_suspend = true
        self.owns_pause = true
        -- Deliberately exit screensaver once. Updating the ordinary image widget
        -- while a screensaver is covering it would not reliably update the display.
        local ok = pcall(function() self.device.powerd:toggleSuspend() end)
        if not ok then self:_finish("wake_failed"); return end
        self:_later(15, function()
            if self.result.state == "waking" then self:_finish("wake_timeout") end
        end)
    end)
end

function Runner:onResume()
    if not self.active then return false end
    if self.result.state == "waking" then
        self.result.state = "connecting"
        self:mark("screen_awake_at")
        self:_later(1, function() self:_connect() end)
    else
        -- Manual wake while waiting, or during the final sleep check, stops this test.
        self:cancel("user_resumed")
    end
    return true
end

function Runner:_connect()
    if self.result.state ~= "connecting" then return end
    self.wifi_owned = true
    self.connect_deadline = self.now() + 45
    -- Kindle's implementation enables the radio and lets the stock saved-network
    -- machinery reconnect. No settings changes, AP picker, or password dialog.
    local ok = pcall(function() self.network:restoreWifiAsync() end)
    if not ok then self:_finish("wifi_failed"); return end
    self:_pollConnection()
end

function Runner:_pollConnection()
    if self.result.state ~= "connecting" then return end
    local ok, connected = pcall(function()
        return self.network:isWifiOn() and self.network:isConnected()
    end)
    if ok and connected then
        if not self.connected_since then
            self.connected_since = self.now()
            self:mark("wifi_connected_at")
        end
        if self.now() - self.connected_since >= 10 then
            self.result.state = "fetching"
            self:mark("wifi_stable_at")
            self:_attemptFetch()
            return
        end
    else
        self.connected_since = nil
    end
    if self.now() >= self.connect_deadline then
        self:_finish("wifi_timeout")
    else
        self:_later(1, function() self:_pollConnection() end)
    end
end

function Runner:_attemptFetch()
    if not self.active or self.result.state ~= "fetching" then return end
    local number = self.result.attempt_count + 1
    self.result.attempt_count = number
    local attempt = {started_at = self.now()}
    self.result.attempts[number] = attempt
    self:_save()
    local worked, outcome, diagnostic = pcall(self.fetch, function(key) self:mark(key) end)
    if not worked then
        outcome = "fetch_exception"
        diagnostic = Diagnostics.localError("transfer", "exception", "Unhandled transfer exception")
    end
    -- Cancellation from a nested UI event must not schedule another attempt.
    if not self.active then return end
    attempt.finished_at = self.now()
    attempt.outcome = outcome == true and "updated" or (outcome or "fetch_failed")
    attempt.diagnostic = diagnostic
    self.result.last_error = diagnostic
    self:_save()
    self.logger.info("TRMNL RTC2:", "attempt", number, attempt.outcome)
    if diagnostic then
        self.logger.info("TRMNL RTC2:", diagnostic.phase, diagnostic.kind, diagnostic.http_status or "-", diagnostic.message)
    end
    -- Never re-fetch metadata because an image download/render failed: that could
    -- select a different server image. Only identified transient API errors retry.
    if outcome == "metadata_failed" and diagnostic and diagnostic.retryable and number < 3 then
        local delay = number * 5
        self:mark("retry_wait_seconds", delay)
        self:_later(delay, function() self:_attemptFetch() end)
    else
        self:_finish(outcome)
    end
end

function Runner:_finish(outcome)
    if not self.active or self.result.state == "closing_wifi" or self.result.state == "checking_sleep" then return end
    self.result.outcome = outcome == true and "updated" or (outcome or "fetch_failed")
    self.result.state = "closing_wifi"
    self:mark("fetch_finished_at")
    self.close_attempts = 0
    local ok = pcall(function() self.network:disableWifi(nil, false) end)
    if not ok then self.logger.warn("TRMNL RTC2: Wi-Fi disable request failed") end
    self:_later(3, function() self:_checkWifiOff() end)
end

function Runner:_checkWifiOff()
    if self.result.state ~= "closing_wifi" then return end
    local ok, on = pcall(function() return self.network:isWifiOn() end)
    if ok and on == false then
        self.wifi_owned = false
        self:mark("wifi_off_at")
        self:_resleep()
    elseif self.close_attempts < 2 then
        self.close_attempts = self.close_attempts + 1
        pcall(function() self.network:disableWifi(nil, false) end)
        self:_later(3, function() self:_checkWifiOff() end)
    else
        -- Still request sleep after a failed cleanup, but report radio state honestly.
        self:mark("wifi_off_failed", true)
        self:_resleep()
    end
end

function Runner:_resleep()
    self.result.state = "checking_sleep"
    self.result.verify_target_at = self.now() + 180
    local ok = pcall(function() self.device.wakeup_mgr:addTask(180, self.verify_alarm) end)
    self:_releasePause()
    if not ok then self:cancel("verify_alarm_failed"); return end
    self:mark("sleep_requested_at")
    if not self.device.screen_saver_mode then
        self.ui:suspend()
    end
    -- No force-toggle in screensaver mode. A new RTC callback 3 minutes later
    -- will provide another system wake event and the device's measured suspend span.
end

function Runner:onSuspend()
    if not self.active then return end
    if self.result.state == "armed" then
        self:mark("first_screensaver_at")
    elseif self.result.state == "checking_sleep" then
        self:mark("return_screensaver_at")
    else
        self:cancel("suspended_during_fetch")
    end
end

function Runner:_verify()
    if not self.active or self.result.state ~= "checking_sleep" then return end
    self:mark("verify_at")
    local ok, seconds = pcall(self.suspend_seconds)
    if ok and type(seconds) == "number" then self:mark("observed_suspend_seconds", math.floor(seconds)) end
    local radio_ok, radio_on = pcall(function() return self.network:isWifiOn() end)
    self.result.verify_wifi_off = radio_ok and radio_on == false or false
    self.result.state = "verified"
    self.result.running = false
    self.active = false
    self:_save()
    -- No queue mutation, network call, display update, or power-button toggle here.
end

function Runner:cancel(reason)
    if not self.active then return end
    self.active = false
    for fn in pairs(self.tasks) do self.ui:unschedule(fn) end
    self.tasks = {}
    self.device.wakeup_mgr:removeTasks(nil, self.alarm)
    self.device.wakeup_mgr:removeTasks(nil, self.verify_alarm)
    if self.wifi_owned then pcall(function() self.network:disableWifi(nil, false) end) end
    self.wifi_owned = false
    self:_releasePause()
    self.result.state = reason or "cancelled"
    self.result.running = false
    self:mark("ended_at")
end

return Runner
