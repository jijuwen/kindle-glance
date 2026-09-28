-- Journal ownership before changing powerd. Recover only this plugin's lease.
local Guard = {}
Guard.__index = Guard
function Guard:new(options)
    local self = setmetatable(options, Guard)
    self.lease = self.store:readSetting("power_lease")
    if self.lease then self:release() end
    return self
end
function Guard:_persist(lease)
    self.store:saveSetting("power_lease", lease)
    self.store:flush()
    self.lease = lease
end
function Guard:acquire()
    if self.lease then return false, "上次常驻状态尚未恢复，请先重试恢复电源设置。" end
    local ok, reason = pcall(function()
        local previous = self.get()
        if previous ~= 0 then error("其他程序正在阻止自动休眠，请先关闭 Keep alive。", 0) end
        self:_persist({previous = previous, owned = true})
        self.set(1)
        if self.get() ~= 1 then error("无法确认常驻电源状态。", 0) end
    end)
    if not ok then
        if self.lease then self:release() end
        return false, tostring(reason)
    end
    return true
end
function Guard:release()
    if not self.lease then return true end
    local ok = pcall(function()
        local current = self.get()
        if current == 1 then
            self.set(self.lease.previous or 0)
            if self.get() ~= (self.lease.previous or 0) then error("power restoration not confirmed") end
        elseif current ~= 0 then error("unexpected power state") end
        self:_persist(nil)
    end)
    self.recovery_error = not ok
    return ok
end
return Guard
