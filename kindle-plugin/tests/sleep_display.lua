local plugin = dofile("kindle-plugin/tests/board.lua")
local Badge = require("trmnl_sleep_badge")
local count = 0
local function check(value, label) assert(value, label); count = count + 1 end
local fake = {new = function(_, value) return value end}
package.loaded["ui/geometry"] = fake
package.loaded["ui/widget/widget"] = fake
package.loaded["ui/widget/textwidget"] = fake
package.loaded["ui/widget/screensaverwidget"] = fake
package.loaded["ui/font"] = {getFace = function(_, _, size) return {size=size} end}
local text, bitmap_frees, mask_fills
package.loaded["ui/widget/container/framecontainer"] = {new = function(_, options)
    check(options.bordersize==0,"battery and warning text have no surrounding border")
    check(options.background==nil and options.padding==0,"battery text has no rectangular background or padding")
    check(options[1].face.size==11,"battery text uses the smaller font")
    check(options[1].fgcolor==255,"battery text is rendered as a mask")
    text = options[1].text
    return {getSize = function() return {w=80,h=30} end,paintTo=function() end,free=function() end}
end}
package.loaded["ffi/blitbuffer"] = {COLOR_BLACK=0,COLOR_WHITE=255,TYPE_BB8=1,new=function()
    return {getWidth=function() return 80 end,getHeight=function() return 30 end,
        fill=function(_,color) check(color==0,"transparent mask is initialized without a white fill");mask_fills=mask_fills+1 end,
        free=function() bitmap_frees=bitmap_frees+1 end}
end}
local device={screen={getWidth=function() return 1236 end,getHeight=function() return 1648 end,
    scaleBySize=function(_,n) return n end},
    getPowerDevice=function() return {invalidateCapacityCache=function() end,getCapacity=function() return 87 end} end}

local cases={
    {read=function() return false end, state="off", label="87"},
    {read=function() return true end, state="on", label="87 !"},
    {read=function() return nil end, state="unknown", label="87 !"},
    {read=function() error("radio query failed") end, state="unknown", label="87 !"},
    {read=function() return false end, state="off", label="87", missing_image=true},
    {read=function() return false end, state="off", label="87", redraw_failed=true},
    {read=function() return true end, state="on", label="87 !", hidden=true},
}
for _, test in ipairs(cases) do
    local events, result, reads = {}, {}, 0
    local cached_image={}
    plugin.image_widget=cached_image
    if test.missing_image then plugin.image_widget=nil end
    local shown
    bitmap_frees,mask_fills=0,0
    local ui={setDirty=function(_,widget,refresh)
        if test.redraw_failed then error("paint queue failed") end
        check(widget==cached_image and refresh=="ui","repaint targets existing local board without a blank fill")
        events[#events+1]="board_dirty"
    end,show=function(_,widget) shown=widget;events[#events+1]="screensaver_show" end,
        close=function(_,widget) widget.widget:free() end}
    package.loaded["ui/uimanager"]=ui
    local ss={show=function() error("unexpected fallback") end,close=function() end}
    package.loaded["ui/screensaver"]=ss
    local owner={active=true,logger={warn=function() end},
        network={isWifiOn=function() reads=reads+1;return test.read() end},
        mark=function(_,key,value) result[key]=value end,
        cancel=function() error("unexpected loop cancellation") end}
    local badge=Badge:new{owner=owner,device=device,ui=ui,hidden=test.hidden,angle=function() return 0 end,
        restore_screen=function() return plugin:prepareSleepDisplay() end}
    badge:install();ss:show()
    check(shown and owner.active and reads==1,"sleep overlay reads radio once without new polling or stopping the loop")
    check(text==test.label and result.sleep_wifi_state==test.state,"number or warning reflects fresh radio state")
    local expected=test.redraw_failed and "failed" or (test.missing_image and "skipped" or "queued")
    check(result.sleep_screen_restore==expected,"log distinguishes queued, skipped, and failed; never claims icon removed")
    check(events[#events]=="screensaver_show" and (expected~="queued" or events[1]=="board_dirty"),
        "board is marked dirty before the normal screensaver refresh")
    local blits=0
    shown.widget:paintTo({colorblitFrom=function(_,_,x,y,_,_,_,_,color)
        check(x==1152 and y==1614 and color==0,"transparent text is painted four pixels from the lower-right corner")
        blits=blits+1
    end},0,0)
    check(blits==(test.hidden and 0 or 1),"user-hidden badge remains hidden while redraw and diagnostics still run")
    check(mask_fills==1,"one transparent mask is prepared per sleep display")
    badge:uninstall()
    check(bitmap_frees==1,"overlay bitmap is released on exit")
end
print("PASS: " .. count .. " sleep display 1.0.1 checks + prior regression")
