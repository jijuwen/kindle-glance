package.path = "kindle-plugin/trmnl.koplugin/?.lua;" .. package.path
local now = 3000000
os.time = function() return now end
local logger = {info = function() end, warn = function() end, dbg = function() end}
package.loaded.logger = logger
package.loaded["ffi/rtc"] = {secondsFromNowToEpoch = function(_, seconds) return now + seconds end}
local WakeupMgr = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/wakeupmgr.lua")
local Loop = require("trmnl_loop")
local D = require("trmnl_diagnostics")
local count = 0
local function check(value, label) assert(value, label); count = count + 1 end
local function fixture()
    local f = {fetches = 0, sleeps = 0, wifi = false, stopped = 0}
    f.store = {data = {}, readSetting = function(s,k) return s.data[k] end,
        saveSetting = function(s,k,v) s.data[k] = v end, flush = function() end}
    f.mgr = WakeupMgr:new{rtc = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/kindle/mockrtc.lua")}
    f.device = {screen_saver_mode = false, wakeup_mgr = f.mgr, powerd = {}}
    f.device.powerd.getPowerdState = function() return f.device.screen_saver_mode and "screenSaver" or "active" end
    f.device.powerd.toggleSuspend = function() f.device.screen_saver_mode = false; f.loop:onResume() end
    f.ui = {tasks = {}, scheduleIn = function(s,d,fn) s.tasks[fn] = now+d end,
        unschedule = function(s,fn) s.tasks[fn] = nil end,
        suspend = function() f.sleeps = f.sleeps+1; f.device.screen_saver_mode = true; f.loop:onSuspend() end}
    f.network = {restoreWifiAsync = function() f.wifi = true end,
        isWifiOn = function() return f.wifi end, isConnected = function() return true end,
        disableWifi = function() f.wifi = false end}
    f.share = {}
    f.loop = Loop:new{device = f.device, ui = f.ui, network = f.network, share = f.share,
        store = f.store, logger = logger, suspend_seconds = function() return 800 end,
        fetch = function(mark)
            f.fetches = f.fetches + 1
            if f.fail then return "metadata_failed", D.transport("metadata", "timeout") end
            mark("displayed_at"); return true
        end,
        on_stopped = function() f.stopped = f.stopped+1 end}
    function f.advance(target)
        while true do
            local fn, at
            for callback,t in pairs(f.ui.tasks) do
                if t <= target and (not at or t < at) then fn,at = callback,t end
            end
            if not fn then break end
            f.ui.tasks[fn] = nil; now = at; fn()
        end
        now = target
    end
    function f.fire()
        f.advance(f.loop.result.next_target_at+5)
        check(f.mgr:wakeupAction(90), "real RTC queue dispatches loop alarm")
        f.advance(now+30)
    end
    return f
end

local f = fixture()
local started = now
check(f.loop:start(), "loop starts explicitly")
check(not f.loop:start(), "duplicate start rejected")
f.advance(now+20)
check(f.fetches == 1 and f.sleeps == 1 and not f.wifi, "initial update immediately connects, draws, shuts down and sleeps")
check(f.loop.result.next_target_at == started+900, "first next slot is fifteen minutes from start")
check(#f.mgr._task_queue == 1 and #f.loop.history == 1, "one next alarm and one recorded cycle; no extra verification alarm")
f.fire(); f.fire()
check(f.fetches == 3 and f.loop.active and f.sleeps == 3, "three rounds do not stop the loop")
check(f.loop.result.next_target_at == started+2700, "rounds stay on fixed fifteen-minute schedule without cumulative drift")
check(#f.mgr._task_queue == 1 and #f.loop.history == 3, "RTC callback never deletes newly armed task")
check(f.loop.result.previous_suspend_seconds == 800, "next real wake records prior suspend span")
f.fail = true; f.fire()
check(f.fetches == 6 and not f.wifi and f.loop.active, "three failed attempts still sleep and continue next scheduled round")
check(f.loop.history[4].outcome == "metadata_failed", "failed round retained in history")
f.fail = false; f.fire()
check(f.loop.history[5].outcome == "updated", "following round recovers without manual intervention")
local before = f.fetches
f.device.screen_saver_mode = false; f.loop:onResume(); f.advance(now+29)
check(f.fetches == before and f.loop.result.state == "user_awake", "manual wake leaves thirty-second tap window without fetching")
f.advance(now+2)
check(f.loop.active and f.device.screen_saver_mode and #f.mgr._task_queue == 1, "no tap returns to sleep with one alarm")
local other = function() end
f.mgr:addTask(3600, other)
f.device.screen_saver_mode = false; f.loop:onResume(); f.loop:cancel("tap_exit")
f.advance(now+100)
check(not f.loop.active and not f.wifi and f.fetches == before and f.stopped == 1, "tap cancellation prevents all late work")
check(#f.mgr._task_queue == 1 and f.mgr._task_queue[1].callback == other, "exit preserves unrelated alarm")
check(f.share.pause_auto_suspend == nil, "autosuspend state restored on exit")
check(f.loop.result.state == "tap_exit" and not f.store.data.result.running, "exit reason persisted")
check(f.loop:start(), "same session can start a new loop after exit")
f.advance(now+20)
check(#f.loop.history == 1, "restarting clears prior run history and records first new cycle")
f.loop:cancel("interrupted")

f = fixture(); f.loop:start(); f.advance(now+4); f.loop:cancel("tap_exit"); f.advance(now+100)
check(f.fetches == 0 and not f.wifi and #f.mgr._task_queue == 0, "exit while connecting cancels delayed initial update")

f = fixture(); f.loop:start(); f.advance(now+20)
for i=1,50 do f.fire() end
check(f.loop.active and #f.loop.history == 48 and f.loop.history[48].cycle == 51, "continuous operation has bounded 48-cycle storage")
f.loop:cancel("interrupted")

-- Scoped hook lifecycle and overlay rendering contract, with device drawing stubs.
local Badge = require("trmnl_sleep_badge")
local normal_show, normal_close, closed, draws, freed = 0,0,0,0,0
local ss = {show = function() normal_show=normal_show+1 end, close = function() normal_close=normal_close+1 end}
package.loaded["ui/screensaver"] = ss
local original_show, original_close = ss.show, ss.close
local fake = {new = function(_, v) return v end}
package.loaded["ui/geometry"] = fake
package.loaded["ui/widget/widget"] = fake
package.loaded["ui/widget/textwidget"] = fake
package.loaded["ui/widget/screensaverwidget"] = fake
package.loaded["ui/font"] = {getFace = function(_, _, size) return {size=size} end}
package.loaded["ui/widget/container/framecontainer"] = {new = function(_,v)
    check(v[1].text == "87", "badge shows battery number without percent sign")
    check(v.padding == 0 and v.background == nil and v.bordersize == 0,
        "badge has no rectangular background, padding, or border")
    check(v[1].face.size == 11, "badge uses the smaller font")
    return {getSize = function() return {w=80,h=30} end, paintTo = function() end, free = function() end}
end}
local function buffer(w,h)
    return {fill = function(_,color) check(color==0,"badge mask starts transparent") end,
        getWidth=function() return w end, getHeight=function() return h end,
        free=function() freed=freed+1 end, rotatedCopy=function(_,a) return buffer(h,w) end}
end
package.loaded["ffi/blitbuffer"] = {new=buffer, TYPE_BB8=1, COLOR_BLACK=0, COLOR_WHITE=255}
local owner = {active=true,logger=logger,mark=function() end,network={isWifiOn=function() return false end}}
local device = {screen={getWidth=function() return 1236 end,getHeight=function() return 1648 end,scaleBySize=function(_,n) return n end},
    getPowerDevice=function() return {invalidateCapacityCache=function() end,getCapacity=function() return 87 end} end}
local shown
local ui = {show=function(_,w) shown=w; draws=draws+1 end,close=function(_,w) closed=closed+1;w.widget:free();device.screen_saver_mode=false end}
local badge = Badge:new{owner=owner,device=device,ui=ui,angle=function() return 90 end}
owner.cancel=function() owner.active=false;badge:uninstall() end
badge:install(); ss:show()
check(normal_show==0 and draws==1 and device.screen_saver_mode, "loop replaces only sleep display with battery overlay")
shown.widget:paintTo({colorblitFrom=function(_,bb,x,y,ox,oy,w,h,color)
    check(x==1202 and y==1564 and color==0, "rotated transparent badge stays close to the corner")
end},0,0)
ss:close()
check(closed==1 and not badge.widget and normal_close==0, "programmatic wake removes custom badge immediately")
ss.event_message="Power off"; ss:show(); ss.event_message=nil
check(normal_show==1, "poweroff message is not replaced by sleep badge")
ss:show();shown:onTap()
check(not owner.active and ss.show==original_show and ss.close==original_close, "tap exits and restores original screensaver hooks")
check(freed==4, "temporary and rotated bitmap buffers freed")
print("PASS: " .. count .. " loop and battery-badge checks")
return {fixture=fixture, now=function() return now end}
