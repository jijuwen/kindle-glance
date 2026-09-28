-- Reuse the tested transfer/cleanup state machine; replace its one-shot sleep check.
local Base = require("trmnl_rtc_refresh")
local Loop = setmetatable({}, {__index = Base})
Loop.__index = Loop

function Loop:new(options)
    local self = Base.new(self, options)
    setmetatable(self, Loop)
    self.history = self.store:readSetting("history") or {}
    return self
end

function Loop:_save()
    pcall(function() self.store:saveSetting("history", self.history or {}) end)
    Base._save(self)
end

function Loop:mark(key, value)
    Base.mark(self, key, value)
    self.logger.info("TRMNL LOOP:", "cycle", self.result.cycle or 0, key, self.result[key])
end

Loop.intervals = {60, 300, 900, 1800, 3600, 43200, 86400}
function Loop:start(interval, strategy)
    interval = interval or 900
    local valid = false
    for _, seconds in ipairs(Loop.intervals) do if interval == seconds then valid = true end end
    local mode = (interval == 60 or strategy == "awake") and "awake" or "sleep"
    if not valid or self.active or (mode == "sleep" and not self.device.wakeup_mgr) or self.device.screen_saver_mode then return false end
    local wifi_ok, initial_wifi = pcall(function() return self.network:isWifiOn() end)
    if not wifi_ok then return false, "无法读取无线状态。" end
    if mode == "awake" then
        if not self.power_guard then return false, "设备缺少常驻电源管理接口。" end
        local ok, reason = self.power_guard:acquire()
        if not ok then return false, reason end
    end
    self.interval, self.mode = interval, mode
    self.initial_wifi_on = initial_wifi
    self.active = true
    self.history = {}
    self.recorded_cycle = nil
    self.result = {version = "1.0.2", mode = mode, state = "connecting", running = true, consecutive_failures = 0,
        cycle = 1, interval = interval, started_at = self.now(), target_at = self.now(), attempts = {}, attempt_count = 0}
    self.previous_pause = self.share.pause_auto_suspend
    self.share.pause_auto_suspend = true
    self.owns_pause = true
    self.connected_since = nil
    self:mark("loop_started_at")
    -- Let the start menu close before connecting and drawing the initial image.
    self:_later(2, function() self:_connect() end)
    return true
end

function Loop:_recordCycle()
    if self.recorded_cycle == self.result.cycle then return end
    local snapshot = {}
    for k, v in pairs(self.result) do snapshot[k] = v end
    snapshot.running = false
    self.history[#self.history + 1] = snapshot
    while #self.history > 48 do table.remove(self.history, 1) end
    self.recorded_cycle = self.result.cycle
    self.logger.info("TRMNL LOOP:", "cycle_end", self.result.cycle, self.result.outcome or "interrupted")
end

function Loop:_nextSleep()
    local target = self.result.next_target_at or (self.result.target_at + self.interval)
    -- Skip missed slots: do not burst-refresh or set an alarm before hardware can sleep.
    while target < self.now() + 120 do target = target + self.interval end
    self.result.next_target_at = target
    self.result.state = "armed"
    self.device.wakeup_mgr:removeTasks(nil, self.alarm)
    local ok = pcall(function() self.device.wakeup_mgr:addTask(target - self.now(), self.alarm) end)
    self:_releasePause()
    if not ok then self:cancel("alarm_failed"); return end
    self:mark("next_target_at", target)
    self:mark("sleep_requested_at")
    if not self.device.screen_saver_mode then self.ui:suspend() end
end

function Loop:_resleep()
    self:_nextSleep()
end

function Loop:_connect()
    local ok, connected = pcall(function() return self.network:isWifiOn() and self.network:isConnected() end)
    if self.mode == "awake" and self.result.cycle > 1 and ok and connected then
        self.result.state = "fetching"
        self:mark("wifi_connected_at")
        self:_attemptFetch()
    else
        Base._connect(self)
    end
end

function Loop:_finish(outcome)
    if not self.active or self.result.state == "closing_wifi" or self.result.state == "waiting" then return end
    if outcome == true then
        self.result.last_success_at = self.now()
        self.result.consecutive_failures = 0
    else
        self.result.consecutive_failures = (self.result.consecutive_failures or 0) + 1
    end
    if self.mode ~= "awake" then return Base._finish(self, outcome) end
    self.result.outcome = outcome == true and "updated" or (outcome or "fetch_failed")
    self:mark("fetch_finished_at")
    self:_recordCycle()
    self.result.state = "waiting"
    local target = self.result.target_at + self.interval
    while target <= self.now() do target = target + self.interval end
    self:mark("next_target_at", target)
    self:_later(target - self.now(), function()
        if self.result.state ~= "waiting" then return end
        self:_newRound("connecting")
        self:_connect()
    end)
end

function Loop:_newRound(state)
    local previous = self.result
    self.result = {version = "1.0.2", mode = self.mode, running = true, state = state, cycle = previous.cycle + 1,
        interval = self.interval, started_at = previous.started_at, target_at = previous.next_target_at,
        attempts = {}, attempt_count = 0, last_success_at = previous.last_success_at,
        consecutive_failures = previous.consecutive_failures or 0}
    self.connected_since = nil
end

function Loop:refreshNow()
    if not self.active or self.device.screen_saver_mode or
        (self.result.state ~= "waiting" and self.result.state ~= "user_awake") then return false end
    for fn in pairs(self.tasks) do self.ui:unschedule(fn) end
    self.tasks = {}
    self.device.wakeup_mgr:removeTasks(nil, self.alarm)
    self.result.next_target_at = self.now()
    self:_newRound("connecting")
    if not self.owns_pause then
        self.previous_pause = self.share.pause_auto_suspend
        self.share.pause_auto_suspend = true
        self.owns_pause = true
    end
    self:mark("manual_refresh_at")
    self:_later(0, function() self:_connect() end)
    return true
end

function Loop:onSuspend()
    if not self.active then return end
    if self.mode == "awake" then self:cancel("manual_sleep"); return end
    if self.result.state == "armed" then
        self:mark("return_screensaver_at")
        self:_recordCycle()
        self:_save()
    elseif self.result.state == "user_awake" then
        self:_nextSleep()
        if self.active then self:mark("return_screensaver_at") end
    else
        -- External sleep during a transfer cancels pending work safely.
        self:cancel("suspended_during_fetch")
    end
end

function Loop:_alarm()
    if not self.active or self.result.state ~= "armed" then return end
    local ok, seconds = pcall(self.suspend_seconds)
    if ok then self.logger.info("TRMNL LOOP:", "previous_suspend_seconds", seconds) end
    self:_newRound("armed")
    self.result.previous_suspend_seconds = ok and seconds or nil
    Base._alarm(self) -- Its work is deferred until WakeupMgr has removed this entry.
end

function Loop:onResume()
    if not self.active then return false end
    if self.result.state == "waking" then return Base.onResume(self) end
    -- A manual wake gives the user time to tap out. It must not launch a fetch.
    for fn in pairs(self.tasks) do self.ui:unschedule(fn) end
    self.tasks = {}
    self.device.wakeup_mgr:removeTasks(nil, self.alarm)
    self.result.state = "user_awake"
    self:mark("manual_wake_at")
    self:_later(30, function()
        if self.result.state == "user_awake" then self:_nextSleep() end
    end)
    return true
end

function Loop:cancel(reason)
    if not self.active then return end
    Base.cancel(self, reason)
    if self.power_guard and not self.power_guard:release() then
        self.result.power_restore_failed = true
        self.logger.warn("Kindle board: power recovery required")
    end
    if self.initial_wifi_on then pcall(function() self.network:restoreWifiAsync() end) end
    self:_recordCycle()
    self:_save()
    self.logger.info("TRMNL LOOP:", "stopped", reason or "cancelled")
    if self.on_stopped then self.on_stopped() end
end

return Loop
