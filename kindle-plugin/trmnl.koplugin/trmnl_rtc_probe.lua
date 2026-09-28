-- Stage 1: one RTC wakeup, no network activity and no screen drawing.
-- Dependencies are injected so the same code can be tested off-device.
local Probe = {}
Probe.__index = Probe

function Probe:new(options)
    local self = setmetatable(options, Probe)
    self.now = self.now or os.time
    self.active = false
    self.result = self.store:readSetting("result") or { state = "idle" }
    -- RTC tasks live in this KOReader process; never recreate a probe on startup.
    if self.result.state == "armed" then
        self.result.state = "interrupted"
        self:_save()
    end
    self.wakeup_callback = function() self:_onAlarm() end
    self.sleep_callback = function()
        if self.active and not self.device.screen_saver_mode then
            self.ui:suspend()
        end
    end
    return self
end

function Probe:_save()
    local ok = pcall(function()
        self.store:saveSetting("result", self.result)
        self.store:flush()
    end)
    if not ok then self.logger.warn("TRMNL RTC: could not save diagnostic result") end
end

function Probe:_powerState()
    local ok, state = pcall(function() return self.device.powerd:getPowerdState() end)
    return ok and state or "unknown"
end

function Probe:available()
    return self.device:isKindle() and self.device:supportsScreensaver()
        and self.device.wakeup_mgr ~= nil
        and type(self.device.wakeup_mgr.addTask) == "function"
        and type(self.device.wakeup_mgr.removeTasks) == "function"
        and self.device.powerd ~= nil and self.device.powerd.lipc_handle ~= nil
end

function Probe:arm(delay)
    if self.active or not self:available() or type(delay) ~= "number" or delay < 120 then
        return false
    end
    self.result = {
        state = "armed", armed_at = self.now(), delay_seconds = delay,
        target_at = self.now() + delay, power_state = self:_powerState(),
    }
    local ok = pcall(function()
        self.device.wakeup_mgr:addTask(delay, self.wakeup_callback)
    end)
    if not ok then
        self.device.wakeup_mgr:removeTasks(nil, self.wakeup_callback)
        self.result.state = "failed"
        self:_save()
        self.logger.warn("TRMNL RTC: could not register probe")
        return false
    end
    self.active = true
    self:_save()
    self.logger.info("TRMNL RTC: armed", self.result.target_at, "delay", delay)
    -- Let the confirmation dialog close before requesting the first sleep.
    self.ui:scheduleIn(2, self.sleep_callback)
    return true
end

function Probe:onSuspend()
    if not self.active then return end
    self.result.suspend_event_at = self.now()
    self.result.power_state = self:_powerState()
    self:_save()
    -- This is the screensaver lifecycle event, not proof of hardware suspend.
    self.logger.info("TRMNL RTC: suspend event", self.result.suspend_event_at)
end

function Probe:_onAlarm()
    if not self.active then return end
    self.active = false
    self.result.state = "fired"
    self.result.fired_at = self.now()
    self.result.lateness_seconds = self.result.fired_at - self.result.target_at
    self.result.power_state = self:_powerState()
    self:_save()
    self.logger.info("TRMNL RTC: fired", self.result.fired_at,
        "lateness", self.result.lateness_seconds, "state", self.result.power_state)
    -- WakeupMgr removes the queue head AFTER invoking this callback. Do not
    -- remove/reorder tasks here, or we could accidentally consume another task.
    -- On Kindle UIManager:suspend() toggles the power button. Calling it while
    -- still in screensaver mode could wake the screen. Let powerd return to sleep.
end

function Probe:cancel(reason)
    if not self.active then return false end
    self.active = false
    self.ui:unschedule(self.sleep_callback)
    -- Remove only this probe, preserving every other plugin's RTC tasks.
    self.device.wakeup_mgr:removeTasks(nil, self.wakeup_callback)
    self.result.state = reason or "cancelled"
    self.result.ended_at = self.now()
    self.result.power_state = self:_powerState()
    self:_save()
    self.logger.info("TRMNL RTC:", self.result.state, self.result.ended_at)
    return true
end

function Probe:onResume()
    if self.active then
        self:cancel("user_resumed")
    elseif self.result.state == "fired" then
        self.result.user_resume_at = self.now()
        self:_save()
    end
end

return Probe
