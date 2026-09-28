-- User-facing 1.0 interface, independent of the transfer and diagnostic engines.
local Board = {}
local intervals = {{60,"1 分钟"},{300,"5 分钟"},{900,"15 分钟"},{1800,"30 分钟"},
    {3600,"1 小时"},{43200,"12 小时"},{86400,"24 小时"}}
local names = {idle="尚未启动",connecting="正在连接网络",fetching="正在更新",waking="正在唤醒",
    closing_wifi="正在关闭网络",armed="休眠等待",waiting="常驻等待",user_awake="等待操作（30 秒）",
    updated="更新成功",metadata_failed="获取画面信息失败",download_failed="下载失败",file_failed="保存失败",
    render_failed="绘制失败",fetch_exception="更新异常",wifi_timeout="联网超时",wifi_failed="开启网络失败",
    interrupted="会话已结束",tap_exit="已点按退出",key_exit="已按键退出",user_exit="已停止",
    manual_sleep="已手动休眠",manual_fetch="已切换为单次更新",badge_failed="电量显示异常，已停止",
    alarm_failed="无法设置唤醒，已停止",suspended_during_fetch="更新被休眠中断",cancelled="已取消"}
local function label(value) return names[value] or value or "—" end
local function stamp(value) return value and os.date("%m-%d %H:%M:%S", value) or "—" end
local function textView(title, text)
    require("ui/uimanager"):show(require("ui/widget/textviewer"):new{title=title,text=text})
end
local function interval(self)
    for _, item in ipairs(intervals) do if self.settings.board_interval == item[1] then return item[1],item[2] end end
    return 900,"15 分钟"
end
local function mode(self)
    return (interval(self)==60 or self.settings.board_power=="awake") and "awake" or "sleep"
end
local function modeLabel(value) return value=="awake" and "常驻 · 保持联网" or "省电 · 更新后休眠" end
local function stopForSetting(self)
    if self.rtc_loop.active then self:stopLowPower(); self:showInfo("已停止看板。设置保存后，点击“开始看板”应用。") end
end

function Board.install(Plugin)
    function Plugin:prepareSleepDisplay()
        if not self.image_widget then return false end
        -- Repaint the existing local image/placeholder through KOReader's stack.
        -- No blank rectangle, server request, global UI mutation, or extra timer.
        require("ui/uimanager"):setDirty(self.image_widget, "ui")
        return true
    end
    function Plugin:refreshBoardNow()
        if not self.rtc_loop.active then self:fetchAndDisplay(true); return end
        if not self.rtc_loop:refreshNow() then self:showInfo("更新正在进行，或设备仍处于休眠状态。") end
    end
    function Plugin:showConfigDialog()
        stopForSetting(self)
        local ui=require("ui/uimanager")
        local dialog
        dialog=require("ui/widget/multiinputdialog"):new{
            title="服务器与设备",
            fields={{text=self.settings.base_url or "",hint="服务器地址（HTTP / HTTPS）"},
                {text=self.settings.api_key or "",hint="设备令牌",text_type="password"},
                {text=self.settings.mac_header_name or "ID",hint="设备标识请求头（默认 ID）"},
                {text=self.settings.mac_address or "",hint="设备 MAC（留空自动读取）"}},
            buttons={{{text="取消",callback=function() ui:close(dialog) end},
                {text="保存",callback=function()
                    local fields=dialog:getFields()
                    local url=(fields[1] or ""):gsub("%s+$",""):gsub("^%s+",""):gsub("/+$","")
                    if not url:match("^https?://[^/]+") or not fields[2] or fields[2]=="" then
                        self:showError("请填写有效的 HTTP(S) 服务器地址和设备令牌。");return
                    end
                    self.settings.base_url=url;self.settings.api_key=fields[2]
                    self.settings.mac_header_name=fields[3]~="" and fields[3] or "ID"
                    self.settings.mac_address=fields[4]~="" and fields[4] or nil
                    self:saveSettings();ui:close(dialog)
                end}}},
        }
        ui:show(dialog)
    end

    function Plugin:getBoardProblem()
        local Device = require("device")
        local share = require("pluginshare")
        if self.rtc_loop.active then return "看板已经运行。" end
        if self.rtc_probe.active or self.rtc_refresh.active then return "设备自检尚未结束，请先取消自检。" end
        if self.power_guard and self.power_guard.lease then return "电源状态尚未恢复，请打开“设置与诊断 → 恢复自动休眠”。" end
        if share.keepalive or share.pause_auto_suspend then return "请先关闭 Keep alive 或其他禁止休眠功能。" end
        if not self.settings.base_url or self.settings.base_url=="" then return "请先设置看板服务器地址。" end
        if not self.settings.api_key or self.settings.api_key=="" then return "请先设置设备令牌。" end
        if not Device.wakeup_mgr then return "当前设备缺少唤醒接口。" end
        local ok,value=pcall(function() return Device.powerd.lipc_handle:get_int_property("com.lab126.powerd","preventScreenSaver") end)
        if not ok or value~=0 then return "无法接管休眠状态。请关闭 Keep alive，再重启 KOReader 后重试。" end
    end

    function Plugin:confirmLowPower()
        local problem=self:getBoardProblem()
        if problem then self:showInfo(problem); return end
        local seconds,title=interval(self)
        local selected_mode=mode(self)
        local detail=selected_mode=="awake"
            and "设备和 Wi-Fi 保持开启，前光可自行关闭。此方式耗电较高；点一下看板即可停止并恢复电源状态。"
            or "每次更新后关闭 Wi-Fi 并休眠。退出时先按电源键唤醒，再在 30 秒内点一下看板；不操作则继续回睡。"
        if seconds>=43200 then detail=detail .. "\n\n此长间隔需验证本机深度休眠后的唤醒可靠性。" end
        require("ui/uimanager"):show(require("ui/widget/confirmbox"):new{
            text="每 " .. title .. "更新一次\n" .. modeLabel(selected_mode) .. "\n\n" .. detail
                .. "\n\n启动时先更新一次。退出或重启 KOReader 不会自动开始。",
            ok_text="开始看板",cancel_text="取消",
            ok_callback=function()
                local changed=self:getBoardProblem()
                if changed then self:showInfo(changed); return end
                local ok,reason=self.rtc_loop:start(seconds,self.settings.board_power or "auto")
                if not ok then self:showError(reason or "无法启动看板。"); return end
                if selected_mode=="sleep" and self.settings.board_battery~=false then
                    self.sleep_badge=require("trmnl_sleep_badge"):new{
                        owner=self.rtc_loop,device=require("device"),ui=require("ui/uimanager"),
                        angle=function() return self.settings.sleep_battery_angle or 0 end,
                        restore_screen=function() return self:prepareSleepDisplay() end,
                        on_exit=function() self:stopLowPower() end,
                    }
                    self.sleep_badge:install()
                elseif selected_mode=="sleep" then
                    -- Keep the scoped screen-preserving override, but omit the badge itself.
                    self.sleep_badge=require("trmnl_sleep_badge"):new{
                        owner=self.rtc_loop,device=require("device"),ui=require("ui/uimanager"),hidden=true,
                        angle=function() return 0 end,on_exit=function() self:stopLowPower() end,
                        restore_screen=function() return self:prepareSleepDisplay() end,
                    }
                    self.sleep_badge:install()
                end
                self:showLowPowerWaitingScreen()
            end,
        })
    end

    function Plugin:showLowPowerStatus()
        local r=self.rtc_loop.result
        local powerd=require("device"):getPowerDevice()
        local ok,battery=pcall(function() powerd:invalidateCapacityCache();return powerd:getCapacity() end)
        local lines={"运行：" .. (self.rtc_loop.active and "运行中" or "已停止"),"状态：" .. label(r.state),
            "刷新间隔：" .. select(2,interval(self)),"电源方式：" .. modeLabel(r.mode or mode(self)),
            "最近更新成功：" .. stamp(r.last_success_at),
            "下一次计划：" .. (self.rtc_loop.active and stamp(r.next_target_at) or "—"),
            "连续失败：" .. tostring(r.consecutive_failures or 0) .. " 次",
            "最近错误：" .. require("trmnl_diagnostics").label(r.last_error),
            "当前电量：" .. (ok and tostring(battery) .. "%" or "暂不可用")}
        if r.sleep_wifi_state then
            lines[#lines+1]="入睡时无线：" .. (r.sleep_wifi_state=="off" and "已关闭" or "未确认关闭（角标 !）")
        end
        if self.power_guard and self.power_guard.lease and not self.rtc_loop.active then lines[#lines+1]="\n电源恢复待处理，请打开设置与诊断。" end
        lines[#lines+1]="\n成功时间是设备取图时间，不代表页面数据的生成时间。"
        textView("运行状态",table.concat(lines,"\n"))
    end

    function Plugin:showBoardRecords(detailed)
        local rows={}
        for i=#self.rtc_loop.history,1,-1 do
            local r=self.rtc_loop.history[i]
            local elapsed=r.fetch_finished_at and r.attempts and r.attempts[1] and r.fetch_finished_at-r.attempts[1].started_at
            rows[#rows+1]="#" .. r.cycle .. "  " .. stamp(r.fetch_finished_at or r.target_at) .. "  " .. label(r.outcome or r.state)
                .. "\n耗时 " .. (elapsed and tostring(elapsed) .. " 秒" or "—") .. " · 尝试 " .. (r.attempt_count or 0) .. " 次"
                .. " · 电量 " .. (r.sleep_battery and tostring(r.sleep_battery) or "—")
            if detailed then
                rows[#rows+1]="唤醒 " .. stamp(r.rtc_at) .. "；关网 " .. stamp(r.wifi_off_at) .. "；回睡 " .. stamp(r.return_screensaver_at)
                if r.sleep_wifi_state then
                    local redraw={queued="已提交",skipped="无底图，跳过",failed="失败"}
                    rows[#rows+1]="入睡无线：" .. (r.sleep_wifi_state=="off" and "已关闭" or "未确认关闭")
                        .. "；底图重绘：" .. (redraw[r.sleep_screen_restore] or "—")
                end
                for n,a in ipairs(r.attempts or {}) do
                    if a.diagnostic then rows[#rows+1]="尝试 " .. n .. "：" .. a.diagnostic.phase .. " / " .. a.diagnostic.message end
                end
            end
            rows[#rows+1]=""
        end
        if #rows==0 then rows[1]="暂无运行记录。启动看板后自动记录最近 48 轮。" end
        if detailed then rows[#rows+1]="完整事件：koreader/board.log（上一份为 board.log.1）。每份约 512 KiB，自动轮转。" end
        textView(detailed and "详细诊断" or "运行记录",table.concat(rows,"\n"))
    end

    function Plugin:addToMainMenu(menu_items)
        local presets={}
        for _,item in ipairs(intervals) do
            local seconds,title=item[1],item[2]
            presets[#presets+1]={text=title .. (seconds==60 and " · 常驻" or ""),
                checked_func=function() return interval(self)==seconds end,
                callback=function() stopForSetting(self);self.settings.board_interval=seconds;self:saveSettings() end}
        end
        local rotation={}
        for _,value in ipairs({0,90,180,270}) do
            local angle=value
            rotation[#rotation+1]={text=angle .. "°",checked_func=function() return (self.settings.sleep_battery_angle or 0)==angle end,
                callback=function() self.settings.sleep_battery_angle=angle;self:saveSettings() end}
        end
        local power={}
        for _,value in ipairs({"auto","awake"}) do
            local strategy=value
            power[#power+1]={text=strategy=="auto" and "自动（推荐）" or "常驻（耗电较高）",
                checked_func=function() return (self.settings.board_power or "auto")==strategy end,
                callback=function() stopForSetting(self);self.settings.board_power=strategy;self:saveSettings() end}
        end
        local config=self:createConfigMenuItem();config.text="服务器与设备"
        menu_items.trmnl={text="Kindle 看板",sorting_hint="tools",sub_item_table={
            {text_func=function() return self.rtc_loop.active and "停止看板" or "开始看板" end,
                callback=function() if self.rtc_loop.active then self:stopLowPower() else self:confirmLowPower() end end},
            {text="立即更新",callback=function() self:refreshBoardNow() end},
            {text_func=function() return "刷新间隔：" .. select(2,interval(self)) end,sub_item_table=presets},
            {text="运行状态",callback=function() self:showLowPowerStatus() end},
            {text="显示与电源",sub_item_table={
                {text="休眠电量角标",checked_func=function() return self.settings.board_battery~=false end,
                    callback=function() stopForSetting(self);self.settings.board_battery=self.settings.board_battery==false;self:saveSettings() end},
                {text="角标文字方向",sub_item_table=rotation},
                {text="电源策略",sub_item_table=power},
                {text="屏幕刷新方式",sub_item_table={self:createRadioMenuItem("UI (balanced)","refresh_type","ui"),
                    self:createRadioMenuItem("Full (best quality)","refresh_type","full")}},
            }},
            {text="设置与诊断",sub_item_table={config,
                {text="运行记录",callback=function() self:showBoardRecords(false) end},
                {text="详细诊断",callback=function() self:showBoardRecords(true) end},
                {text="恢复自动休眠",enabled_func=function() return not self.rtc_loop.active end,
                    callback=function() local ok=self.power_guard:release();self:showInfo(ok and "本插件的电源状态已恢复。" or "恢复失败，请重启 KOReader 后重试。") end},
                {text="关于 Kindle 看板",callback=function() textView("Kindle 看板 1.0.2","七档刷新间隔 · 常驻与省电双模式\n\n休眠角标：透明背景的小号纯数字表示已确认关闭无线；带 ! 表示未确认关闭。进入屏保时重绘原看板，尝试清除系统飞机图标。\n\n1 分钟自动常驻，其他间隔默认休眠。12／24 小时长间隔需要本机验收。\n\n退出或重启后不自动运行。常驻模式异常退出时，下次启动将尝试恢复电源设置。\n\n查看行情时请关注服务端标注的数据时间。") end},
            }},
        }}
    end
    function Plugin:onTrmnlStartInteractive() self:confirmLowPower() end
    function Plugin:onTrmnlFetch() self:refreshBoardNow() end
end
return Board
