-- Run from the workspace root with LuaJIT 2.1 (or Lupa's luajit21 runtime).
package.path = "kindle-plugin/trmnl.koplugin/?.lua;" .. package.path
local now = 1000000
os.time = function() return now end
local logs = {}
local logger = {
    info = function(...) logs[#logs + 1] = {...} end,
    warn = function(...) logs[#logs + 1] = {...} end,
    dbg = function() end,
}
package.loaded.logger = logger
package.loaded["ffi/rtc"] = {
    secondsFromNowToEpoch = function(_, seconds) return now + seconds end,
}
local WakeupMgr = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/wakeupmgr.lua")
local Probe = require("trmnl_rtc_probe")
local count = 0
local function check(condition, label)
    assert(condition, label)
    count = count + 1
end
local function newStore(initial)
    return {
        data = initial or {},
        readSetting = function(self, key) return self.data[key] end,
        saveSetting = function(self, key, value) self.data[key] = value end,
        flush = function() end,
    }
end
local function fixture(store)
    local mgr = WakeupMgr:new{rtc = dofile("kindle-plugin/tests/fixtures/koreader/frontend/device/kindle/mockrtc.lua")}
    local device = {
        isKindle = function() return true end,
        supportsScreensaver = function() return true end,
        screen_saver_mode = false,
        wakeup_mgr = mgr,
        powerd = {
            lipc_handle = {get_int_property = function() return 0 end},
            getPowerdState = function() return "screenSaver" end,
            isCharging = function() return false end,
        },
    }
    local ui = {
        tasks = {}, suspend_count = 0,
        scheduleIn = function(self, delay, fn) self.tasks[fn] = delay end,
        unschedule = function(self, fn) self.tasks[fn] = nil end,
        suspend = function(self) self.suspend_count = self.suspend_count + 1 end,
        show = function(self, widget) self.last_widget = widget end,
    }
    local probe = Probe:new{device = device, ui = ui, logger = logger, store = store or newStore()}
    return probe, device, ui, mgr
end

-- Test the exact WakeupMgr and mock RTC shipped in the user's v2026.07.1.
local probe, device, ui, mgr = fixture()
check(probe:arm(900), "one-shot probe registers")
check(mgr:getWakeupAlarmEpoch() == now + 900, "uses Kindle RTC queue")
check(not probe:arm(900), "cannot arm a duplicate probe")
local other_called = false
local other_callback = function() other_called = true end
mgr:addTask(1800, other_callback)
probe.sleep_callback()
check(ui.suspend_count == 1, "initial suspend requested once")
device.screen_saver_mode = true
probe.sleep_callback()
check(ui.suspend_count == 1, "does not toggle power while already in screensaver")
probe:onSuspend()
now = now + 915
check(mgr:wakeupAction(90), "real WakeupMgr accepts scheduled callback")
check(probe.result.state == "fired" and probe.result.lateness_seconds == 15, "records actual callback time")
check(ui.suspend_count == 1, "RTC callback never toggles power button")
check(#mgr._task_queue == 1 and mgr._task_queue[1].callback == other_callback, "callback preserves the next plugin's task")
check(not other_called, "does not run an unrelated callback")
check(not mgr:wakeupAction(90), "probe cannot fire twice")
probe:onResume()
check(probe.result.state == "fired", "manual resume after success preserves result")

probe, device, ui, mgr = fixture()
mgr:addTask(500, other_callback)
probe:arm(900)
probe:onResume()
check(probe.result.state == "user_resumed", "early user resume cancels probe")
check(#mgr._task_queue == 1 and mgr._task_queue[1].callback == other_callback, "cancellation removes only owned callback")
check(ui.tasks[probe.sleep_callback] == nil, "cancellation removes delayed suspend")
probe.wakeup_callback()
check(probe.result.state == "user_resumed", "late delivery after cancellation is inert")

probe, device, ui, mgr = fixture(newStore{result = {state = "armed", target_at = now + 900}})
check(probe.result.state == "interrupted" and #mgr._task_queue == 0, "restart does not recreate a stale alarm")
device.wakeup_mgr = nil
check(not probe:arm(900), "unsupported device is rejected")

local Menu = require("trmnl_menu")
local order = {tools = {"other", "trmnl", "last"}, more_tools = {"trmnl", "keep_alive"}}
Menu.pin(order)
Menu.pin(order)
check(table.concat(order.tools, ",") == "trmnl,other,last", "pin is first and idempotent")
check(table.concat(order.more_tools, ",") == "keep_alive", "pin removes duplicate without disturbing other items")
package.loaded.gettext = function(text) return text end
check(require("trmnl_i18n")("TRMNL Display") == "Kindle 看板", "plugin-local Chinese translation")

-- Load the integrated plugin with UI/network stubs: the probe must not fetch.
probe, device, ui, mgr = fixture()
device.screen = {}
device.input = {}
device.hasWifiRestore = function() return false end
local Base = {}
function Base:extend(values) return setmetatable(values or {}, {__index = self}) end
function Base:new(values) return self:extend(values) end
local stub_modules = {"ui/geometry", "ui/gesturerange", "ui/widget/infomessage", "ui/widget/imagewidget",
    "ui/widget/container/inputcontainer", "ui/widget/container/widgetcontainer", "ui/widget/multiinputdialog", "ui/widget/confirmbox"}
for _, name in ipairs(stub_modules) do package.loaded[name] = Base end
local stores = {}
package.loaded.luasettings = {open = function(_, path)
    stores[path] = stores[path] or newStore()
    return stores[path]
end}
package.loaded.datastorage = {getSettingsDir = function() return "test-settings" end}
package.loaded.device = device
package.loaded["ui/uimanager"] = ui
package.loaded["ui/renderimage"] = {}
package.loaded.dispatcher = {registerAction = function() end}
package.loaded.pluginshare = {}
package.loaded.util = {tableDeepCopy = function(values)
    local result = {}; for k, v in pairs(values) do result[k] = v end; return result
end}
package.loaded["ffi/util"] = {template = function(message) return message end}
package.loaded["ui/elements/reader_menu_order"] = {tools = {"other"}}
package.loaded["ui/elements/filemanager_menu_order"] = {tools = {"other"}}
local fetch_count = 0
local wifi_on = false
package.loaded["ui/network/manager"] = {
    isWifiOn = function() return wifi_on end,
    runWhenConnected = function() fetch_count = fetch_count + 1 end,
}
G_reader_settings = {isTrue = function() return false end}
local Plugin = dofile("kindle-plugin/trmnl.koplugin/main.lua")
local plugin = Plugin:new{
    ui = {menu = {registerToMainMenu = function() end}},
    loadApiKeyFromFile = function() return nil end,
}
plugin:init()
check(not plugin.auto_refresh_enabled and fetch_count == 0, "install does not enable auto refresh or network")
wifi_on = true
check(plugin:getRtcTestProblem() ~= nil, "probe rejects active Wi-Fi")
wifi_on = false
plugin.auto_refresh_enabled = true
check(plugin:getRtcTestProblem() ~= nil, "probe rejects continuous refresh")
plugin.auto_refresh_enabled = false
package.loaded.pluginshare.keepalive = true
check(plugin:getRtcTestProblem() ~= nil, "probe rejects Keep alive")
package.loaded.pluginshare.keepalive = false
device.powerd.isCharging = function() return true end
check(plugin:getRtcTestProblem() ~= nil, "probe rejects charging during diagnostic")
device.powerd.isCharging = function() return false end
plugin:confirmRtcTest()
ui.last_widget.ok_callback()
check(plugin.rtc_probe.active and fetch_count == 0, "start diagnostic performs no fetch")
device.screen_saver_mode = true
plugin:onSuspend()
now = now + 915
check(mgr:wakeupAction(90) and fetch_count == 0, "integrated RTC callback performs no fetch")
plugin:onResume()
check(plugin.rtc_probe.result.state == "fired" and fetch_count == 0, "resume does not fetch when auto refresh disabled")
plugin:fetchAndDisplay(true)
check(fetch_count == 1, "existing manual fetch still reaches network framework")
local items = {}
plugin:addToMainMenu(items)
check(items.trmnl.text == "Kindle 看板", "integrated menu is Chinese")
check(items.trmnl.sub_item_table[6].text == "设置与诊断", "diagnostics grouped under settings")

-- Exercise both real menu orders through KOReader's real sorting algorithm.
device.hasExitOptions = function() return true end
package.loaded["libs/libkoreader-lfs"] = {attributes = function() return nil end}
package.loaded["ffi/util"].orderedPairs = pairs
local Sorter = dofile("kindle-plugin/tests/fixtures/koreader/frontend/ui/menusorter.lua")
for _, mode in ipairs({"reader", "filemanager"}) do
    local real_order = dofile("kindle-plugin/tests/fixtures/koreader/frontend/ui/elements/" .. mode .. "_menu_order.lua")
    Menu.pin(real_order)
    local menu_items = {}
    for id, children in pairs(real_order) do
        menu_items[id] = menu_items[id] or {text = id, sub_item_table = {}}
        for _, child in ipairs(children) do
            if child ~= "----------------------------" then
                menu_items[child] = menu_items[child] or {text = child, sub_item_table = {}}
            end
        end
    end
    plugin:addToMainMenu(menu_items)
    local sorted = Sorter:mergeAndSort(mode, menu_items, real_order)
    local tools = Sorter:findById(sorted, "tools")
    check(tools[1].id == "trmnl", "real " .. mode .. " menu pins dashboard first")
end
for _, name in ipairs({"main.lua", "_meta.lua", "trmnl_menu.lua", "trmnl_i18n.lua", "trmnl_rtc_probe.lua"}) do
    assert(loadfile("kindle-plugin/trmnl.koplugin/" .. name))
end
print("PASS: " .. count .. " stage-1 checks (real v2026.07.1 WakeupMgr + mocked device/UI)")
return plugin
