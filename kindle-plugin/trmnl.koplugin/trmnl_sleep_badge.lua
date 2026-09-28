-- Scoped screensaver override: no persistent/core screensaver settings are changed.
local Badge = {}
Badge.__index = Badge

function Badge:new(options) return setmetatable(options, self) end

function Badge:install()
    if self.installed then return end
    local ss = require("ui/screensaver")
    self.ss = ss
    self.original_show, self.original_close = ss.show, ss.close
    self.show_hook = function(s, ...)
        if self.owner.active and not s.event_message and (not s.prefix or s.prefix == "") then
            local ok = pcall(function() self:show(s) end)
            if ok then return end
            self.owner.logger.warn("TRMNL LOOP: battery badge failed; stopping loop and restoring normal screensaver")
            self.owner:cancel("badge_failed")
        end
        return self.original_show(s, ...)
    end
    self.close_hook = function(s, ...)
        if self.widget then
            self.ui:close(self.widget)
            self.widget = nil
            return true
        end
        return self.original_close(s, ...)
    end
    ss.show, ss.close = self.show_hook, self.close_hook
    self.installed = true
end

function Badge:show(ss)
    local Device = self.device
    local Screen = Device.screen
    local powerd = Device:getPowerDevice()
    local ok, level = pcall(function()
        powerd:invalidateCapacityCache()
        return powerd:getCapacity()
    end)
    local label = ok and type(level) == "number" and tostring(math.floor(math.max(0, math.min(100, level)))) or "--"
    self.owner:mark("sleep_battery", ok and type(level) == "number" and level or -1)
    -- Read the current radio state, not an earlier request/result or mere absence of an IP.
    local radio_ok, radio_on = pcall(function() return self.owner.network:isWifiOn() end)
    local radio_state = radio_ok and radio_on == false and "off"
        or (radio_ok and radio_on == true and "on" or "unknown")
    self.owner:mark("sleep_wifi_state", radio_state)
    if radio_state ~= "off" then label = label .. " !" end
    local Frame = require("ui/widget/container/framecontainer")
    local Text = require("ui/widget/textwidget")
    local BB = require("ffi/blitbuffer")
    local Geom = require("ui/geometry")
    -- Render the text into a grayscale mask. Painting that mask with
    -- colorblitFrom keeps the board pixels around the glyphs untouched, so the
    -- badge has neither a border nor a rectangular background.
    local frame = Frame:new{padding = 0, margin = 0, bordersize = 0,
        Text:new{text = label, face = require("ui/font"):getFace("infofont", 11),
            fgcolor = BB.COLOR_WHITE},
    }
    local size = frame:getSize()
    local buffer = BB.new(size.w, size.h, BB.TYPE_BB8)
    buffer:fill(BB.COLOR_BLACK)
    frame:paintTo(buffer, 0, 0)
    frame:free()
    local angle = self.angle() or 0
    if angle ~= 0 then
        local rotated = buffer:rotatedCopy(angle)
        buffer:free()
        buffer = rotated
    end
    local margin = Screen:scaleBySize(4)
    local width, height = Screen:getWidth(), Screen:getHeight()
    local overlay = require("ui/widget/widget"):new{dimen = Geom:new{w = width, h = height}}
    overlay.paintTo = function(_, bb, x, y)
        if self.hidden then return end
        bb:colorblitFrom(buffer, x + width - buffer:getWidth() - margin,
            y + height - buffer:getHeight() - margin, 0, 0,
            buffer:getWidth(), buffer:getHeight(), BB.COLOR_BLACK)
    end
    overlay.free = function() if buffer then buffer:free(); buffer = nil end end
    local widget = require("ui/widget/screensaverwidget"):new{widget = overlay, background = nil, covers_fullscreen = false}
    widget.modal = true
    -- Kindle disables input in hardware sleep. If a tap is delivered while awake,
    -- stop the loop as well as dismissing the screen, so no delayed task survives.
    widget.onTap = function()
        self.owner:cancel("tap_exit")
        if self.on_exit then self.on_exit() end
        return true
    end
    Device.screen_saver_mode = true
    Device.orig_rotation_mode = nil
    if self.ui.setIgnoreTouchInput then self.ui:setIgnoreTouchInput(false) end
    self.widget = widget
    ss.screensaver_widget = widget
    -- A new overlay alone need not repaint widgets below it. Mark the existing
    -- board dirty too, then let the normal screensaver full refresh paint both.
    -- This is one bounded attempt, not proof that the stock UI won't draw again.
    if self.restore_screen then
        local restored, result = pcall(self.restore_screen)
        self.owner:mark("sleep_screen_restore", restored and result == true and "queued"
            or (restored and "skipped" or "failed"))
    end
    self.ui:show(widget, "full")
end

function Badge:uninstall()
    if not self.installed then return end
    if self.widget then self.ui:close(self.widget); self.widget = nil end
    if self.ss.show == self.show_hook then self.ss.show = self.original_show end
    if self.ss.close == self.close_hook then self.ss.close = self.original_close end
    self.installed = false
end

return Badge
