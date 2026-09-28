local fixture_data=dofile("kindle-plugin/tests/loop.lua")
local fixture,now=fixture_data.fixture,fixture_data.now
local Guard=require("trmnl_power_guard")
local count=0
local function check(v,label) assert(v,label);count=count+1 end
local function guarded()
    local f=fixture()
    f.prevent=0;f.sets=0
    f.guard=Guard:new{store=f.store,get=function() if f.get_failed then error("offline") end;return f.prevent end,
        set=function(v) if f.set_failed then error("offline") end;f.prevent=v;f.sets=f.sets+1 end}
    f.loop.power_guard=f.guard
    return f
end

local f=guarded()
local start=now()
check(f.loop:start(60,"auto"),"one minute starts with power guard")
check(f.prevent==1 and f.guard.lease and f.store.data.power_lease,"power change is journaled and owned")
f.advance(now()+20)
check(f.loop.mode=="awake" and f.loop.result.state=="waiting" and f.wifi,"one minute keeps Wi-Fi connected between requests")
check(f.sleeps==0 and #f.mgr._task_queue==0,"awake mode never schedules RTC or suspend")
f.advance(start+181)
check(f.fetches==4 and f.sets==1,"one timer fetch per minute with no repeated power writes")
check(f.loop.result.next_target_at==start+240 and f.loop.result.last_success_at==start+180,"minute schedule and success timestamp maintained")
f.loop:cancel("tap_exit");local fetches=f.fetches;f.advance(now()+200)
check(f.prevent==0 and not f.guard.lease and not f.wifi and f.fetches==fetches,"exit restores power, closes owned Wi-Fi, cancels timer")
check(f.share.pause_auto_suspend==nil,"awake mode releases KOReader autosuspend pause")

f=guarded();f.wifi=true;f.loop:start(300,"awake");f.advance(now()+20)
check(f.loop.mode=="awake" and f.prevent==1 and f.sleeps==0,"five minute explicit awake override supported")
f.loop:cancel("user_exit")
check(f.wifi and f.prevent==0,"pre-existing Wi-Fi state is restored on exit")

for _,seconds in ipairs({300,900,1800,3600,43200,86400}) do
    f=guarded();local baseline=now();check(f.loop:start(seconds,"auto"),"valid sleep preset starts")
    f.advance(now()+20)
    check(f.loop.mode=="sleep" and f.loop.result.next_target_at==baseline+seconds,"preset uses exact RTC interval")
    check(f.prevent==0 and f.sets==0 and not f.wifi,"sleep preset never disables auto sleep")
    f.fire()
    check(f.fetches==2 and f.loop.result.next_target_at==baseline+2*seconds,"preset repeats after real wake queue callback")
    f.loop:cancel("user_exit")
end
f=guarded();check(not f.loop:start(120,"auto") and f.prevent==0,"unsupported intervals do not change power")
f=guarded();f.prevent=1
check(not f.loop:start(60,"auto") and f.prevent==1 and not f.guard.lease,"existing Keep alive owner is not overwritten")
f=guarded();f.set_failed=true
check(not f.loop:start(60,"auto") and not f.loop.active,"failed power acquisition does not start scheduler")

f=guarded();f.loop:start(60,"auto");f.advance(now()+20)
f.set_failed=true;f.loop:cancel("user_exit")
check(f.loop.result.power_restore_failed and f.guard.lease,"failed restoration retains recovery journal")
f.set_failed=false
local recovered=Guard:new{store=f.store,get=function() return f.prevent end,set=function(v) f.prevent=v end}
check(f.prevent==0 and not recovered.lease and not f.store.data.power_lease,"next startup recovers interrupted owned power setting")

f=guarded();f.loop:start(60,"auto");f.advance(now()+20);f.loop:onSuspend()
check(not f.loop.active and f.prevent==0 and f.loop.result.state=="manual_sleep","manual sleep exits awake mode and restores power")
f=guarded();f.fail=true;f.loop:start(60,"auto");f.advance(now()+40)
check(f.fetches==3 and f.loop.result.consecutive_failures==1 and f.loop.active,"temporary errors retry within one awake round")
f.fail=false;f.advance(now()+30)
check(f.loop.result.consecutive_failures==0 and f.loop.result.last_success_at,"later success clears consecutive failures")
f.loop:cancel("user_exit")

f=guarded();f.loop:start(60,"auto");f.advance(now()+20)
check(f.loop:refreshNow(),"manual refresh can run without stopping awake mode")
f.advance(now()+1)
check(f.fetches==2 and f.loop.active and f.prevent==1,"manual refresh preserves mode and power lease")
f.loop:cancel("user_exit")
f=guarded();f.loop:start(900,"auto");f.advance(now()+20)
f.device.screen_saver_mode=false;f.loop:onResume()
check(f.loop:refreshNow(),"manual refresh can replace sleep mode's thirty-second user window")
f.advance(now()+20)
check(f.fetches==2 and f.loop.active and f.device.screen_saver_mode and #f.mgr._task_queue==1,"manual sleep-mode update rearms exactly one alarm")
f.loop:cancel("user_exit")

-- Bounded journal rotation uses only fixed owned paths, closes handles, and never touches crash.log.
local original_open,original_remove,original_rename=io.open,os.remove,os.rename
local calls,contents={},{}
local size=512*1024
io.open=function(path,mode)
    calls[#calls+1]=path
    if mode=="rb" then return {seek=function() return size end,close=function() end} end
    return {write=function(_,s) contents[#contents+1]=s;return true end,close=function() end}
end
os.remove=function(path) calls[#calls+1]=path;return true end
os.rename=function(a,b) calls[#calls+1]=a;calls[#calls+1]=b;return true end
local journal=require("trmnl_journal").new("/fixture/board.log",{warn=function() error("unexpected write failure") end})
journal.info("round",1,"updated")
check(contents[1]:find("round 1 updated",1,true),"journal writes readable timestamped events")
for _,path in ipairs(calls) do check(path=="/fixture/board.log" or path=="/fixture/board.log.1","rotation touches only owned journal paths") end
io.open,os.remove,os.rename=original_open,original_remove,original_rename

-- Load the actual integrated 1.0 UI with regression stubs.
local plugin=dofile("kindle-plugin/tests/stage1.lua")
local menu={};plugin:addToMainMenu(menu)
local items=menu.trmnl.sub_item_table
check(#items==6 and items[1].text_func()=="开始看板" and items[6].text=="设置与诊断","formal menu has six clear entry points")
check(#items[3].sub_item_table==7,"all seven refresh presets exposed")
items[3].sub_item_table[1].callback()
check(plugin.settings.board_interval==60 and items[3].text_func()=="刷新间隔：1 分钟","interval selection saves and updates display")
for _,item in ipairs(items) do check(not (item.text or ""):find("测试",1,true),"daily menu has no test labels") end
local testbase={new=function(_,v) return v end}
package.loaded["ui/widget/textviewer"]=testbase
local device=package.loaded.device
device.getPowerDevice=function() return {invalidateCapacityCache=function() end,getCapacity=function() return 87 end} end
plugin:showLowPowerStatus()
check(package.loaded["ui/uimanager"].last_widget.title=="运行状态","status uses formal title")
plugin:showConfigDialog()
local fields=package.loaded["ui/uimanager"].last_widget.fields
check(#fields==4,"server configuration no longer exposes conflicting legacy refresh interval")

print("PASS: " .. count .. " board 1.0 checks + loop and stage-1 regression")
return plugin
