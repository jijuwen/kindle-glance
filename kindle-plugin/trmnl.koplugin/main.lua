--[[--
TRMNL Display Plugin for KOReader

Fetches and displays personalized screens from the TRMNL API.
Supports automatic periodic refresh, full-screen display, and WiFi management.
]]

local DataStorage = require("datastorage")
local Device = require("device")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local InfoMessage = require("ui/widget/infomessage")
local ImageWidget = require("ui/widget/imagewidget")
local InputContainer = require("ui/widget/container/inputcontainer")
local LuaSettings = require("luasettings")
local MultiInputDialog = require("ui/widget/multiinputdialog")
local NetworkMgr = require("ui/network/manager")
local RenderImage = require("ui/renderimage")
local Screen = Device.screen
local Input = Device.input
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local Dispatcher = require("dispatcher")
local logger = require("logger")
local util = require("util")
local _ = require("trmnl_i18n")
local T = require("ffi/util").template
local Diagnostics = require("trmnl_diagnostics")

local function limitedSink(sink, limit)
    local received = 0
    return function(chunk, err)
        if chunk then
            received = received + #chunk
            if received > limit then return nil, "response too large" end
        end
        return sink(chunk, err)
    end
end

--[[--
Retry Manager - handles exponential backoff for failed requests.
Implements: 60s, 120s, 240s, 480s, etc., capped at max_delay.
--]]
local RetryManager = {}
RetryManager.__index = RetryManager
RetryManager.BASE_DELAY = 60
RetryManager.MIN_DELAY = 60

function RetryManager:new(max_delay)
    local instance = {
        count = 0,
        max_delay = max_delay or 1800
    }
    setmetatable(instance, self)
    return instance
end

function RetryManager:getDelay()
    local delay = self.BASE_DELAY * (2 ^ self.count)
    return math.min(delay, math.max(self.max_delay, self.MIN_DELAY))
end

function RetryManager:increment()
    self.count = self.count + 1
    return self:getDelay()
end

function RetryManager:reset()
    self.count = 0
end

--[[--
Main plugin class extending WidgetContainer.
Provides lifecycle hooks (init, onSuspend, onResume) and menu integration.
]]
local TrmnlDisplay = WidgetContainer:extend {
    name = "trmnl",
    is_doc_only = false,

    settings = nil,
    settings_file = nil,

    refresh_task = nil,
    auto_refresh_enabled = false,
    auto_refresh_scheduled = false,
    interactive_mode = false,
    image_widget = nil,
    last_image_path = nil,
    last_image_filename = nil,
    last_fetch_timestamp = 0,

    retry_manager = nil,
}

TrmnlDisplay.CONSTANTS = {
    RETRY = {
        BASE_DELAY = 60,
        MIN_DELAY = 60,
    },
    TIMING = {
        DEFAULT_REFRESH_INTERVAL = 1800,
        DEBOUNCE_DELAY = 25,
    },
    FILES = {
        DEFAULT_IMAGE = "trmnl_screen.png",
        API_KEY = "apikey.txt",
    }
}

TrmnlDisplay.default_settings = {
    api_key = nil,
    base_url = "",
    refresh_interval = 1800,
    user_agent = "trmnl-display/0.1.0-koreader",
    use_server_refresh_rate = false,
    refresh_type = "ui",
    show_notifications = true,
    mac_header_name = nil,  -- Header name for MAC address (configurable for BYOS)
    mac_address = nil,  -- Manual MAC address override (nil = auto-detect)
}

--[[--
Plugin initialization - loads settings, initializes managers, and restores state.
]]
function TrmnlDisplay:init()
    self.settings_file = LuaSettings:open(DataStorage:getSettingsDir() .. "/trmnl.lua")
    self.settings = self.settings_file:readSetting("settings") or util.tableDeepCopy(self.default_settings)
    self.auto_refresh_enabled = self.settings_file:readSetting("auto_refresh_enabled") or false

    self.retry_manager = RetryManager:new(self.settings.refresh_interval or
        self.CONSTANTS.TIMING.DEFAULT_REFRESH_INTERVAL)

    -- Try auto-loading API key from file
    local file_api_key = self:loadApiKeyFromFile()
    if file_api_key and (not self.settings.api_key or self.settings.api_key == "") then
        self.settings.api_key = file_api_key
        self:saveSettings()
        logger.info("TRMNL: API key auto-configured from file")
    end

    -- Must be instance-specific for UIManager to track properly
    self.refresh_task = function()
        self:fetchAndDisplay()
    end

    self.rtc_probe = require("trmnl_rtc_probe"):new{
        device = Device, ui = UIManager, logger = logger,
        store = LuaSettings:open(DataStorage:getSettingsDir() .. "/trmnl-rtc-test.lua"),
    }
    local menu = require("trmnl_menu")
    self.rtc_refresh = require("trmnl_rtc_refresh"):new{
        device = Device, ui = UIManager, network = NetworkMgr, logger = logger,
        share = require("pluginshare"),
        store = LuaSettings:open(DataStorage:getSettingsDir() .. "/trmnl-rtc-refresh.lua"),
        fetch = function(mark) return self:performRtcFetch(mark) end,
        suspend_seconds = function()
            return require("ui/time").to_number(Device.last_suspend_time or 0)
        end,
    }
    menu.pin(require("ui/elements/reader_menu_order"))
    self.power_guard = require("trmnl_power_guard"):new{
        store = LuaSettings:open(DataStorage:getSettingsDir() .. "/board-power.lua"),
        get = function() return Device.powerd.lipc_handle:get_int_property("com.lab126.powerd", "preventScreenSaver") end,
        set = function(value) Device.powerd.lipc_handle:set_int_property("com.lab126.powerd", "preventScreenSaver", value) end,
    }
    local board_logger = require("trmnl_journal").new((DataStorage.getDataDir and DataStorage:getDataDir() or ".") .. "/board.log", logger)
    self.rtc_loop = require("trmnl_loop"):new{
        device = Device, ui = UIManager, network = NetworkMgr, logger = board_logger, power_guard = self.power_guard,
        share = require("pluginshare"),
        store = LuaSettings:open(DataStorage:getSettingsDir() .. "/trmnl-loop.lua"),
        fetch = function(mark) return self:performRtcFetch(mark) end,
        suspend_seconds = function() return require("ui/time").to_number(Device.last_suspend_time or 0) end,
        on_stopped = function() if self.sleep_badge then self.sleep_badge:uninstall() end end,
    }
    menu.pin(require("ui/elements/filemanager_menu_order"))

    Dispatcher:registerAction("trmnl_fetch_now", {category="none", event="TrmnlFetch", title=_("TRMNL: Fetch now"), general=true})
    Dispatcher:registerAction("trmnl_start_interactive", {category="none", event="TrmnlStartInteractive", title="Kindle 看板：开始看板", general=true})

    self.ui.menu:registerToMainMenu(self)

    if self.auto_refresh_enabled then
        -- Migrate legacy timers without starting a second scheduler on install.
        self.auto_refresh_enabled = false
        self:saveSettings()
    end
end

--[[--
Save settings to disk (called automatically on suspend/exit).
]]
function TrmnlDisplay:onFlushSettings()
    if self.settings_file then
        self.settings_file:saveSetting("settings", self.settings)
        self.settings_file:saveSetting("auto_refresh_enabled", self.auto_refresh_enabled)
        self.settings_file:flush()
    end
end

function TrmnlDisplay:saveSettings()
    self:onFlushSettings()
end

function TrmnlDisplay:getPluginDir()
    local info = debug.getinfo(1, "S")
    local filepath = info.source:match("^@(.+)$")
    if filepath then
        return filepath:match("(.*/)")
    end
    return nil
end

--[[--
Load API key from apikey.txt in plugin directory (if present).
]]
function TrmnlDisplay:loadApiKeyFromFile()
    local plugin_dir = self:getPluginDir()
    if not plugin_dir then
        return nil
    end

    local apikey_path = plugin_dir .. self.CONSTANTS.FILES.API_KEY
    local file = io.open(apikey_path, "r")
    if not file then
        return nil
    end

    local content = file:read("*all")
    file:close()

    if not content or content == "" then
        return nil
    end

    local api_key = content:match("^%s*(.-)%s*$")
    if api_key and api_key ~= "" then
        logger.info("TRMNL: API key loaded from file")
        return api_key
    end

    return nil
end

--[[--
Get MAC address of the wireless network interface.

Uses FFI (Foreign Function Interface) to call POSIX system calls:
- getifaddrs(): Enumerate all network interfaces
- ioctl(SIOCGIWNAME): Check if interface is wireless
- ioctl(SIOCGIFHWADDR): Get hardware (MAC) address

@treturn string|nil MAC address (format: "XX:XX:XX:XX:XX:XX") or nil if not available
]]
function TrmnlDisplay:getMacAddress()
    local interfaces = {
        "wlan0",
        "wlan1",
        "mlan0",
    }
 
    for _, iface in ipairs(interfaces) do
        local path = "/sys/class/net/" .. iface .. "/address"
        local file = io.open(path, "r")
 
        if file then
            local mac = file:read("*l")
            file:close()
 
            if mac and mac ~= "" then
                mac = mac:upper()
 
                -- Ignore invalid/all-zero addresses
                if mac ~= "00:00:00:00:00:00" then
                    logger.info(
                        "TRMNL: Auto-detected MAC address:",
                        mac,
                        "interface:",
                        iface
                    )
                    return mac
                end
            end
        end
    end
 
    logger.info("TRMNL: No wireless interface MAC address found")
    return nil
end

--============================================================================--
-- Network and API Methods
--
-- These methods handle:
-- - HTTP/HTTPS requests to TRMNL API
-- - JSON parsing
-- - Image downloads
-- - Error handling and retry logic
--============================================================================--

--[[--
Fetch screen metadata from TRMNL API.

Makes HTTP GET request to /api/display endpoint with headers:
- access-token: User's API key
- percent-charged: Device battery percentage
- png-width/png-height: Screen dimensions in pixels
- rssi: WiFi signal strength (hardcoded to 0 for now)
- User-Agent: Plugin version string

@treturn table|nil Decoded JSON response table, or nil on error
]]
function TrmnlDisplay:fetchScreenMetadata()
    if not self.settings.api_key or self.settings.api_key == "" then
        self:showError("Please configure your TRMNL API key first.")
        return nil, Diagnostics.localError("metadata", "auth", "API token is not configured")
    end

    -- LuaSocket libraries for HTTP/HTTPS requests
    local http = require("socket.http") -- HTTP protocol
    local https = require("ssl.https")  -- HTTPS/TLS protocol
    local ltn12 = require("ltn12")      -- Streaming data I/O filters
    local JSON = require("json")        -- JSON parsing

    -- ltn12.sink.table accumulates response body into a Lua table
    local sink = {}
    local request_url = self.settings.base_url .. "/api/display"

    -- Get device information for API headers
    -- Device:hasBattery() checks if device has battery capability
    -- Device:getPowerDevice() returns power device object with getCapacity() method
    local percent_charged = "0"
    if Device:hasBattery() then
        local powerd = Device:getPowerDevice()
        percent_charged = tostring(powerd:getCapacity()) -- Returns 0-100 percentage
    end

    -- Screen:getWidth()/getHeight() return pixel dimensions
    -- TRMNL uses this to generate appropriately sized images
    local png_width = tostring(Screen:getWidth())
    local png_height = tostring(Screen:getHeight())

    -- Get MAC address: manual entry wins (if not empty), otherwise auto-detect
    local mac_address
    local manual_mac = self.settings.mac_address
    if manual_mac and manual_mac ~= "" then
        -- Manual MAC provided - use it
        mac_address = manual_mac
        logger.dbg("TRMNL: Using manual MAC address:", mac_address)
    else
        -- No manual MAC or empty string - try auto-detection.
        -- Staying nil drops the header from the table constructor below, which is
        -- what we want: claiming a made-up MAC is worse than claiming none.
        mac_address = self:getMacAddress()
        logger.dbg("TRMNL: Using MAC address:", mac_address or "(none detected)")
    end

    -- Get custom header name for MAC address
    local mac_header_name = self.settings.mac_header_name or "ID"

    logger.info("TRMNL: Fetching screen from", request_url)
    logger.dbg("TRMNL: Screen dimensions:", png_width, "x", png_height)

    -- Build HTTP request table (LuaSocket format)
    local request = {
        url = request_url,
        method = "GET",
        headers = {
            ["access-token"] = self.settings.api_key,  -- TRMNL API authentication
            ["percent-charged"] = percent_charged,     -- Device battery level
            ["png-width"] = png_width,                 -- Screen width in pixels
            ["png-height"] = png_height,               -- Screen height in pixels
            ["rssi"] = "0",                            -- WiFi signal strength (TODO: implement)
            [mac_header_name] = mac_address,           -- MAC address with custom header name
            ["User-Agent"] = self.settings.user_agent, -- Plugin identification
        },
        sink = self.rtc_network
            and limitedSink(require("socketutil").table_sink(sink), 128 * 1024)
            or ltn12.sink.table(sink),
        -- SSL/TLS configuration for HTTPS
        protocol = "any",                              -- Accept any SSL/TLS version
        options = { "all", "no_sslv2", "no_sslv3" },   -- Disable insecure SSL versions
        verify = "peer",
    }

    -- Choose HTTP or HTTPS based on URL scheme
    local httpx = request_url:match("^https://") and https or http
    local success_code, status_code = require("trmnl_transport").request(request, self.settings.ca_file)

    logger.dbg("TRMNL: Success code:", success_code)
    logger.dbg("TRMNL: HTTP status code:", status_code)

    if not success_code or success_code ~= 1 then
        local diagnostic = Diagnostics.transport("metadata", status_code, {self.settings.api_key})
        if self.rtc_network then return nil, diagnostic end
        logger.err("TRMNL: Request failed - success code:", success_code)
        local context = _("Network error - check WiFi connection\nURL: ") .. request_url
        self:showError(T(_("Failed to reach TRMNL API (code: %1)"), tostring(success_code)), context)
        return nil, diagnostic
    end

    if status_code ~= 200 then
        if self.rtc_network then return nil, Diagnostics.http("metadata", status_code) end
        logger.err("TRMNL: API returned HTTP", status_code)
        local context_msg
        if status_code == 401 or status_code == 403 then
            context_msg = "Check your API key in settings"
        elseif status_code == 404 then
            context_msg = "Endpoint not found - verify base URL"
        elseif status_code >= 500 then
            context_msg = "Server error - try again later"
        else
            context_msg = "HTTP " .. tostring(status_code)
        end
        self:showError("API request failed", context_msg)
        return nil, Diagnostics.http("metadata", status_code)
    end

    local response_body = table.concat(sink)
    if not self.rtc_network then
        logger.dbg("TRMNL: Received metadata bytes:", #response_body)
    end

    local ok, response = pcall(JSON.decode, response_body)
    if not ok or type(response) ~= "table" then
        logger.err("TRMNL: Failed to parse JSON response")
        return nil, Diagnostics.localError("metadata", "json", "Expected a JSON object; response body not recorded")
    end

    return response
end

function TrmnlDisplay:downloadImage(image_url, filepath)
    local http = require("socket.http")
    local https = require("ssl.https")
    local ltn12 = require("ltn12")

    if self.rtc_network then
        logger.info("TRMNL RTC2: downloading image")
    else
        logger.info("TRMNL: Downloading signed image")
    end

    local file = io.open(filepath, "wb")
    if not file then
        logger.err("TRMNL: Failed to open file for writing:", filepath)
        return false, Diagnostics.localError("image", "file", "Cannot open image temporary file")
    end

    local request = {
        url = image_url,
        sink = self.rtc_network
            and limitedSink(require("socketutil").file_sink(file), 8 * 1024 * 1024)
            or ltn12.sink.file(file),
        headers = {
            ["User-Agent"] = self.settings.user_agent,
        },
        -- SSL/TLS configuration (same as API request)
        protocol = "any",
        options = { "all", "no_sslv2", "no_sslv3" },
        verify = "peer",
    }

    local httpx = image_url:match("^https://") and https or http
    local request_ok, success_code, status_code = pcall(require("trmnl_transport").request, request, self.settings.ca_file)
    pcall(function() file:close() end)

    logger.dbg("TRMNL: Image download success code:", success_code)
    logger.dbg("TRMNL: Image download HTTP status:", status_code)

    if not request_ok or not success_code or success_code ~= 1 then
        logger.err("TRMNL: Image download failed")
        os.remove(filepath)
        return false, Diagnostics.transport("image", request_ok and status_code or success_code, {self.settings.api_key})
    end

    if status_code ~= 200 then
        logger.err("TRMNL: Image download failed - HTTP", status_code)
        os.remove(filepath)
        return false, Diagnostics.http("image", status_code)
    end

    logger.info("TRMNL: Image downloaded successfully")
    return true
end

function TrmnlDisplay:displayImage(image_path)
    -- NOTE: Keep old image visible while rendering new one
    -- Only close it if we successfully render the replacement
    -- This prevents empty screens during network/rendering errors

    local screen_width = Screen:getWidth()
    local screen_height = Screen:getHeight()

    logger.info("TRMNL: Rendering image", image_path)

    local image_bb = RenderImage:renderImageFile(
        image_path,
        true, -- enable caching
        screen_width,
        screen_height
    )

    if not image_bb then
        logger.err("TRMNL: Failed to render image")
        return false
    end

    -- Close previous image widget only after successfully rendering new one
    if self.image_widget then
        UIManager:close(self.image_widget)
        self.image_widget = nil
    end

    local image = ImageWidget:new {
        image = image_bb,
        image_disposable = true,
        width = screen_width,
        height = screen_height,
        alpha = true,
    }

    -- Wrap in InputContainer to handle tap events
    self.image_widget = InputContainer:new {
        dimen = {
            x = 0,
            y = 0,
            w = screen_width,
            h = screen_height,
        },
        image,
    }

    -- Add tap handler to close the image
    self.image_widget.onTapClose = function()
        logger.info("TRMNL: Closing image via tap")
        if self.rtc_loop then self.rtc_loop:cancel("tap_exit") end
        if self.interactive_mode then
            logger.info("TRMNL: Exiting interactive mode")
            self.interactive_mode = false
            self:stopAutoRefresh()
        end
        UIManager:close(self.image_widget)
        self.image_widget = nil
        return true
    end

    -- Add key press handler for non-touch devices
    self.image_widget.onAnyKeyPressed = function()
        logger.info("TRMNL: Closing image via button press")
        if self.rtc_loop then self.rtc_loop:cancel("key_exit") end
        if self.interactive_mode then
            logger.info("TRMNL: Exiting interactive mode")
            self.interactive_mode = false
            self:stopAutoRefresh()
        end
        UIManager:close(self.image_widget)
        self.image_widget = nil
        return true
    end

    -- Register tap gesture
    if Device:isTouchDevice() then
        self.image_widget.ges_events = {
            TapClose = {
                GestureRange:new {
                    ges = "tap",
                    range = Geom:new {
                        x = 0, y = 0,
                        w = screen_width,
                        h = screen_height,
                    }
                }
            }
        }
    end

    -- Register key events for non-touch devices
    if Device:hasKeys() then
        self.image_widget.key_events = {
            AnyKeyPressed = { { Input.group.Any } }
        }
    end

    -- Add widget to UIManager's display stack
    UIManager:show(self.image_widget)

    --[[--
    E-ink refresh optimization

    E-ink displays have several refresh modes with tradeoffs:
    - "ui": Balanced speed/quality (default)
    - "full": Slowest but best quality, clears ghosting
    - "flashui": With screen flash for better contrast
    - "partial": Fastest but may cause ghosting
    ]]
    local refresh_type = self.settings.refresh_type or "ui"
    logger.info("TRMNL: Applying refresh type:", refresh_type)

    -- UIManager:setDirty() marks widget for screen update with specified refresh mode
    -- This triggers the e-ink controller to redraw the widget's area
    UIManager:setDirty(self.image_widget, refresh_type)

    logger.info("TRMNL: Image displayed")
    return true
end

--============================================================================--
-- Helper Methods
--============================================================================--

--[[--
Smart notification system - shows informative messages without overwhelming.

Types: "error", "info", "success", "progress"
Can be toggled on/off via settings.show_notifications
@tparam string message Main message text
@tparam table opts Optional: {type, context, timeout, force}
]]
function TrmnlDisplay:notify(message, opts)
    if self.rtc_network then return end
    opts = opts or {}
    local msg_type = opts.type or "info"
    local context = opts.context

    -- Always log, even if notifications disabled
    logger.info("TRMNL [" .. msg_type .. "]: " .. message)
    if context then
        logger.dbg("TRMNL Context: " .. context)
    end

    -- Skip showing notification if disabled (unless force = true)
    -- Always show errors though, they're important
    if not self.settings.show_notifications and msg_type ~= "error" and not opts.force then
        return
    end

    local timeout
    if opts.timeout then
        timeout = opts.timeout
    elseif msg_type == "error" then
        timeout = 5
    elseif msg_type == "progress" then
        timeout = 3
    else
        timeout = 2
    end

    local full_message = _(message)
    if context and context ~= "" then
        full_message = full_message .. "\n\n" .. _(context)
    end

    local prefix = ""
    if msg_type == "error" then
        prefix = "⚠ "
    elseif msg_type == "success" then
        prefix = "✓ "
    elseif msg_type == "progress" then
        prefix = "⟳ "
    end

    UIManager:show(InfoMessage:new {
        text = prefix .. full_message,
        timeout = timeout,
    })
end

function TrmnlDisplay:showError(message, context)
    self:notify(message, { type = "error", context = context })
end

function TrmnlDisplay:showInfo(message)
    self:notify(message, { type = "info" })
end

function TrmnlDisplay:showSuccess(message)
    self:notify(message, { type = "success" })
end

function TrmnlDisplay:showProgress(message, context)
    self:notify(message, { type = "progress", context = context })
end

--[[--
Unschedule any pending refresh task.

Safely removes any scheduled refresh task and updates the flag.
Safe to call even if no task is scheduled.
]]
function TrmnlDisplay:unscheduleRefreshTask()
    if self.refresh_task then
        UIManager:unschedule(self.refresh_task)
        self.auto_refresh_scheduled = false
        logger.dbg("TRMNL: Unscheduled refresh task")
    end
end

--[[--
Prevent device from automatically suspending (sleeping).

Uses KOReader's standby prevention API to keep device awake while auto-refresh is active.
This ensures the dashboard remains visible and refreshes continue.
Works on all devices (Kindle, Kobo, PocketBook, etc.).
]]
function TrmnlDisplay:preventAutoSuspend()
    UIManager:preventStandby()
    logger.info("TRMNL: Device sleep prevented (auto-refresh active)")
end

--[[--
Re-enable device auto-suspend (sleeping).

Restores normal power management behavior when auto-refresh is disabled.
]]
function TrmnlDisplay:allowAutoSuspend()
    UIManager:allowStandby()
    logger.info("TRMNL: Device sleep re-enabled (normal behavior)")
end

--[[--
Schedule the next refresh if auto-refresh is enabled.

Uses the configured refresh_interval to schedule the next fetch cycle.
Unschedules any existing pending task to prevent double-scheduling.
]]
function TrmnlDisplay:scheduleNextRefresh()
    if not self.auto_refresh_enabled then
        logger.info("TRMNL: Auto-refresh disabled, not scheduling")
        return
    end

    self:unscheduleRefreshTask()

    local interval = self.settings.refresh_interval or self.CONSTANTS.TIMING.DEFAULT_REFRESH_INTERVAL
    logger.info("TRMNL: Scheduling next refresh in", interval, "seconds")
    UIManager:scheduleIn(interval, self.refresh_task)
    self.auto_refresh_scheduled = true
end

--[[--
Check if scheduling state is valid.
@treturn boolean true if state is valid
]]
function TrmnlDisplay:isScheduleStateValid()
    if self.auto_refresh_enabled then
        return self.auto_refresh_scheduled
    else
        return not self.auto_refresh_scheduled
    end
end

--[[--
Validate and fix scheduling state.
Ensures exactly one task when enabled, zero tasks when disabled.
]]
function TrmnlDisplay:validateAndFixScheduleState()
    if self:isScheduleStateValid() then
        return
    end

    if self.auto_refresh_enabled then
        logger.warn("TRMNL: Auto-refresh enabled but no task scheduled - fixing!")
        self:scheduleNextRefresh()
    else
        logger.warn("TRMNL: Auto-refresh disabled but task still scheduled - fixing!")
        self:unscheduleRefreshTask()
    end
end

--[[--
Handle fetch errors with exponential backoff retry logic.

Increments retry counter, shows user notification,
and schedules retry if auto-refresh is enabled.

@tparam string error_message User-friendly error description
]]
function TrmnlDisplay:handleFetchError(error_message)
    local retry_delay = self.retry_manager:increment()

    logger.err("TRMNL:", error_message, "(attempt", self.retry_manager.count, ")")
    if self.auto_refresh_enabled then
        self:showError(T(_("Failed: %1. Will retry in %2 seconds."), _(error_message), retry_delay))
    else
        self:showError(T(_("Failed: %1."), _(error_message)))
    end

    -- NOTE: afterWifiAction will be called by the caller to clean up WiFi

    if self.auto_refresh_enabled then
        logger.info("TRMNL: Scheduling retry in", retry_delay, "seconds")
        UIManager:scheduleIn(retry_delay, self.refresh_task)
    end
end

--[[--
Update refresh interval from server response if configured to do so.

@tparam table response API response containing optional refresh_rate field
]]
function TrmnlDisplay:updateRefreshInterval(response)
    if not self.settings.use_server_refresh_rate or not response.refresh_rate then
        return
    end

    local new_interval = tonumber(response.refresh_rate)
    if new_interval and new_interval > 0 then
        logger.info("TRMNL: Using server refresh rate:", new_interval, "seconds")
        self.settings.refresh_interval = new_interval
        self:saveSettings()
    end
end

--[[--
Download screen image if it has changed since last fetch.

Compares filename to detect changes. If unchanged, uses cached file.
If changed, downloads new image and updates cache tracking.
Automatically deletes old image file to prevent accumulation.

@tparam table response API response containing image_url and filename
@treturn string|nil Path to image file, or nil on download failure
]]
function TrmnlDisplay:downloadImageIfNeeded(response)
    local filename = response.filename or self.CONSTANTS.FILES.DEFAULT_IMAGE
    if not filename:match("%.png$") then
        filename = filename .. ".png"
    end

    local image_path = DataStorage:getDataDir() .. "/" .. filename

    -- Check if image has changed
    if filename == self.last_image_filename then
        logger.info("TRMNL: Image unchanged, using cached file:", image_path)
        return image_path
    end

    -- Image changed, clean up old file before downloading new one
    logger.info("TRMNL: Image changed, downloading:", filename)
    self:showProgress("Downloading new screen...", filename)

    if self.last_image_path and self.last_image_path ~= image_path then
        logger.info("TRMNL: Removing old image file:", self.last_image_path)
        local success = os.remove(self.last_image_path)
        if success then
            logger.dbg("TRMNL: Old image file deleted successfully")
        else
            logger.warn("TRMNL: Could not delete old image file (may not exist)")
        end
    end

    -- Download new image
    if not self:downloadImage(response.image_url, image_path) then
        return nil -- Download failed
    end

    -- Update cache tracking
    self.last_image_path = image_path
    self.last_image_filename = filename
    return image_path
end

--[[--
Check debounce timing to prevent rapid API calls.
@treturn boolean true if check passed, false if debouncing
]]
function TrmnlDisplay:checkDebounce(skip_debounce)
    if skip_debounce then
        return true
    end

    local now = UIManager:getElapsedTimeSinceBoot()
    local time_since_last = now - self.last_fetch_timestamp

    if time_since_last <= self.CONSTANTS.TIMING.DEBOUNCE_DELAY then
        logger.dbg("TRMNL: Debouncing - last fetch", time_since_last, "seconds ago")
        return false
    end

    self.last_fetch_timestamp = now
    return true
end

--[[--
Finalize successful fetch - cleanup, reset state, and schedule next refresh.
]]
function TrmnlDisplay:finalizeFetchSuccess(image_path)
    self:displayImage(image_path)
    logger.info("TRMNL: Fetch and display completed successfully")

    self:showSuccess("Screen updated successfully")

    -- Clean up WiFi using KOReader's framework
    NetworkMgr:afterWifiAction()

    self.retry_manager:reset()

    self:scheduleNextRefresh()
    self:validateAndFixScheduleState()
end

--[[--
Main workflow - fetches screen from API and displays it.

Called by user action, auto-refresh timer, or network availability callback.
Uses pipeline pattern for clear flow control and early exits on errors.
]]
function TrmnlDisplay:fetchAndDisplay(skip_debounce)
    if self.rtc_loop then self.rtc_loop:cancel("manual_fetch") end
    if self.rtc_refresh then self.rtc_refresh:cancel("cancelled") end
    if self.rtc_probe then self.rtc_probe:cancel("cancelled") end
    logger.info("TRMNL: Starting fetch and display cycle")

    if not self:checkDebounce(skip_debounce) then
        return
    end

    -- Use KOReader's WiFi management framework
    -- runWhenConnected will turn on WiFi if needed and wait for connection
    NetworkMgr:runWhenConnected(function()
        self:_doFetchAndDisplay()
    end)
end

--[[--
Internal fetch implementation that runs after WiFi is confirmed connected.
Separated from fetchAndDisplay to work with NetworkMgr:runWhenConnected().

Includes a small delay after WiFi connection to ensure the network stack is fully ready
for HTTP requests, as some devices report "connected" before being able to make requests.
]]
function TrmnlDisplay:_doFetchAndDisplay()
    -- Give WiFi a moment to fully stabilize after connection
    -- This prevents "connected but not really" issues on some devices
    logger.info("TRMNL: WiFi connected, waiting 2 seconds for network to stabilize...")
    UIManager:scheduleIn(2, function()
        self:_performFetch()
    end)
end

--[[--
Perform the actual fetch and display after WiFi is ready.
]]
function TrmnlDisplay:_performFetch()
    local response = self:fetchScreenMetadata()
    if not response or not response.image_url then
        -- NOTE: the API reports device/token problems as HTTP 200 with
        -- {"status": 500, "error": "..."}, so the only place that detail survives is here.
        local detail = response and (response.error or
            (response.status and "status " .. tostring(response.status)))
        if detail then
            logger.err("TRMNL: API returned no image_url:", detail)
        end
        self:handleFetchError(detail or "Failed to fetch screen metadata")
        NetworkMgr:afterWifiAction()
        return
    end

    self:updateRefreshInterval(response)

    local image_path = self:downloadImageIfNeeded(response)
    if not image_path then
        self:handleFetchError("Failed to download image")
        NetworkMgr:afterWifiAction()
        return
    end

    self:finalizeFetchSuccess(image_path)
end

--============================================================================--
-- Auto-Refresh Control
--
-- These methods start/stop the automatic refresh cycle.
-- Called by menu actions and lifecycle hooks.
--============================================================================--

--[[--
Start auto-refresh cycle.

Called by:
- User selecting "Enable auto-refresh" menu item
- Plugin init() if auto-refresh was previously enabled

Flow:
1. Enable auto-refresh flag
2. Save state to disk
3. Fetch and display immediately (no delay for first refresh)
4. fetchAndDisplay() will schedule subsequent refreshes
]]
function TrmnlDisplay:startAutoRefresh()
    if self.rtc_loop then self.rtc_loop:cancel("auto_refresh_started") end
    if self.rtc_refresh then self.rtc_refresh:cancel("cancelled") end
    if self.rtc_probe then self.rtc_probe:cancel("cancelled") end
    if self.auto_refresh_enabled and self.auto_refresh_scheduled then
        logger.info("TRMNL: Auto-refresh already active")
        return
    end

    logger.info("TRMNL: Starting auto-refresh")

    -- NOTE: Ensure clean state before starting
    self:unscheduleRefreshTask()

    self.auto_refresh_enabled = true
    self.auto_refresh_scheduled = false -- Will be set to true after first fetch schedules next
    self:saveSettings()                 -- Persist across KOReader restarts

    -- Prevent device from sleeping while displaying dashboard
    self:preventAutoSuspend()

    self:showProgress("Starting auto-refresh...", "Fetching first screen")

    -- Start immediately - will display the image and schedule next refresh
    self:fetchAndDisplay()

    logger.dbg("TRMNL: Auto-refresh started, initial fetch triggered")
end

--[[--
Stop auto-refresh cycle.

Called by:
- User selecting "Disable auto-refresh" menu item
- Device lifecycle events (suspend, plugin close)

Unschedules any pending refresh tasks using UIManager:unschedule().
]]
function TrmnlDisplay:stopAutoRefresh()
    if not self.auto_refresh_enabled then
        logger.dbg("TRMNL: Auto-refresh already stopped")
        return
    end

    logger.info("TRMNL: Stopping auto-refresh")

    -- NOTE: Unschedule first to ensure clean state
    self:unscheduleRefreshTask()

    self.auto_refresh_enabled = false
    self.auto_refresh_scheduled = false
    self:saveSettings() -- Persist across KOReader restarts

    -- Re-enable device sleep
    self:allowAutoSuspend()

    logger.dbg("TRMNL: Auto-refresh stopped, all tasks unscheduled")
end

--============================================================================--
-- Lifecycle Handlers
--
-- These are lifecycle hooks called automatically by KOReader:
-- - onSuspend: Called when device is about to sleep
-- - onResume: Called when device wakes from sleep
-- - onCloseWidget: Called when plugin is disabled or KOReader exits
--
-- Proper lifecycle handling ensures:
-- - Tasks don't run while device is suspended (saves battery)
-- - Fresh data is fetched immediately on wake
-- - No resource leaks when plugin is disabled
--============================================================================--

--[[--
Device is suspending (going to sleep).

Unschedule refresh task to prevent it running during sleep.
]]
function TrmnlDisplay:onSuspend()
    if self.rtc_loop then self.rtc_loop:onSuspend() end
    if self.rtc_refresh then self.rtc_refresh:onSuspend() end
    if self.rtc_probe then self.rtc_probe:onSuspend() end
    if self.auto_refresh_enabled then
        self:unscheduleRefreshTask()
    end
end

--[[--
Device is resuming (waking from sleep).

If auto-refresh is enabled, fetch immediately rather than waiting for the
scheduled interval. This ensures fresh data after potentially long sleep periods.
Unschedules any pending task first to prevent double-refresh.

NOTE: If auto_restore_wifi is enabled, skip immediate fetch to prevent duplicate
network events and connection UI popups. The WiFi will be auto-restored and we'll
wait for the next scheduled refresh instead.
]]
function TrmnlDisplay:onResume()
    if self.rtc_loop and self.rtc_loop:onResume() then return end
    if self.rtc_refresh and self.rtc_refresh:onResume() then return end
    if self.rtc_probe then self.rtc_probe:onResume() end
    if Device:hasWifiRestore() and NetworkMgr.wifi_was_on and
        G_reader_settings:isTrue("auto_restore_wifi") then
        if self.auto_refresh_enabled then
            self:validateAndFixScheduleState()
        end
        return
    end

    if not self.auto_refresh_enabled then
        return
    end

    self:unscheduleRefreshTask()
    self:fetchAndDisplay()
end

--[[--
Plugin is being disabled or KOReader is exiting.

Clean up:
- Stop auto-refresh cycle
- Close any displayed image widgets
- Settings are automatically flushed by onFlushSettings()
]]
function TrmnlDisplay:onCloseWidget()
    if self.rtc_loop then self.rtc_loop:cancel("interrupted") end
    if self.rtc_refresh then self.rtc_refresh:cancel("interrupted") end
    if self.rtc_probe then self.rtc_probe:cancel("interrupted") end
    logger.dbg("TRMNL: Plugin closing")
    self:stopAutoRefresh()
    if self.image_widget then
        UIManager:close(self.image_widget)
        self.image_widget = nil
    end
end

--============================================================================--
-- UI Configuration
--
-- These methods create and manage user interface elements:
-- - Configuration dialogs for settings
-- - Main menu integration
-- - Submenus for advanced options
--
-- KOReader UI Components Used:
-- - MultiInputDialog: Multiple text/number fields in one dialog
-- - InfoMessage: Temporary notification pop-ups
-- - menu_items table: Hierarchical menu structure
-- - text_func: Dynamic menu text based on state
-- - checked_func: Radio button/checkbox state
--============================================================================--

--[[--
Show configuration dialog for basic settings.

Uses MultiInputDialog which provides multiple input fields in one dialog:
- API Key (password-masked text input)
- Base URL (text input)
- Refresh Interval (number input)

Fields are retrieved via getFields() which returns array of values in order.
]]
function TrmnlDisplay:showConfigDialog()
    -- Get auto-detected MAC to show as placeholder/hint
    local auto_mac = self:getMacAddress() or "Auto-detect unavailable"
    local mac_hint = auto_mac ~= "Auto-detect unavailable"
        and _("MAC address (leave empty to use:") .. auto_mac .. ")"
        or _("MAC address (auto-detect unavailable)")

    self.config_dialog = MultiInputDialog:new {
        title = _("Configure TRMNL"),
        fields = {
            {
                text = self.settings.api_key or "",
                hint = _("Enter your TRMNL API key"),
                input_type = "string",
                password = true,
            },
            {
                text = self.settings.base_url or "",
                hint = _("TRMNL base URL"),
                input_type = "string",
            },
            {
                text = tostring(self.settings.refresh_interval or 1800),
                hint = _("Refresh interval (seconds)"),
                input_type = "number",
            },
            {
                text = self.settings.mac_header_name or "ID",
                hint = _("MAC address header name (e.g. ID)"),
                input_type = "string",
            },
            {
                text = self.settings.mac_address or "",
                hint = mac_hint,
                input_type = "string",
            },
        },
        buttons = {
            {
                {
                    text = _("Cancel"),
                    id = "close",
                    callback = function()
                        UIManager:close(self.config_dialog)
                    end,
                },
                {
                    text = _("Save"),
                    is_enter_default = true,
                    callback = function()
                        local fields = self.config_dialog:getFields()
                        self.settings.api_key = fields[1]
                        self.settings.base_url = fields[2]
                        self.settings.refresh_interval = tonumber(fields[3]) or 1800
                        self.settings.mac_header_name = fields[4]
                        self.settings.mac_address = fields[5] ~= "" and fields[5] or nil
                        self:saveSettings()
                        UIManager:close(self.config_dialog)
                        self:showInfo("TRMNL settings saved.")
                    end,
                },
            },
        },
    }

    UIManager:show(self.config_dialog)
end

--============================================================================--
-- Menu Builders
--============================================================================--

--[[--
Create a toggle menu item that switches between two states.
@tparam string label_when_on Text to show when currently on
@tparam string label_when_off Text to show when currently off
@tparam function getter Function that returns current state (boolean)
@tparam function toggler Function called to toggle state, should return success message
@treturn table Menu item configuration
]]
function TrmnlDisplay:createToggleMenuItem(label_when_on, label_when_off, getter, toggler)
    return {
        text_func = function()
            return getter() and _(label_when_on) or _(label_when_off)
        end,
        callback = function()
            local message = toggler()
            if message then
                UIManager:show(InfoMessage:new {
                    text = _(message),
                    timeout = 2,
                })
            end
        end
    }
end

--[[--
Create a radio button menu item for exclusive choices.
@tparam string label Display text
@tparam string setting_key Settings key to check/update
@tparam string value Value to compare and set
@treturn table Menu item configuration
]]
function TrmnlDisplay:createRadioMenuItem(label, setting_key, value)
    return {
        text = _(label),
        checked_func = function()
            return self.settings[setting_key] == value
        end,
        callback = function()
            self.settings[setting_key] = value
            self:saveSettings()
        end
    }
end

--[[--
Create menu item constructors for each feature.
]]
function TrmnlDisplay:createFetchMenuItem()
    return {
        text = _("Fetch screen now"),
        callback = function()
            self:fetchAndDisplay(true)
        end
    }
end

function TrmnlDisplay:createStartInteractiveMenuItem()
    return {
        text = _("Start TRMNL (interactive)"),
        callback = function()
            self:onTrmnlStartInteractive()
        end
    }
end

function TrmnlDisplay:createConfigMenuItem()
    return {
        text = _("Configure TRMNL"),
        keep_menu_open = true,
        callback = function()
            self:showConfigDialog()
        end
    }
end

function TrmnlDisplay:createAutoRefreshToggle()
    return self:createToggleMenuItem(
        "Disable auto-refresh",
        "Enable auto-refresh",
        function() return self.auto_refresh_enabled end,
        function()
            if self.auto_refresh_enabled then
                self:stopAutoRefresh()
                return "Auto-refresh disabled."
            else
                self:startAutoRefresh()
                return "Auto-refresh enabled."
            end
        end
    )
end

function TrmnlDisplay:createServerRefreshToggle()
    return self:createToggleMenuItem(
        "Use manual refresh interval",
        "Use server refresh interval",
        function() return self.settings.use_server_refresh_rate end,
        function()
            self.settings.use_server_refresh_rate = not self.settings.use_server_refresh_rate
            self:saveSettings()
            return self.settings.use_server_refresh_rate
                and "Will use server's recommended refresh interval"
                or "Will use your manual refresh interval"
        end
    )
end

function TrmnlDisplay:createNotificationsToggle()
    return self:createToggleMenuItem(
        "Hide status notifications",
        "Show status notifications",
        function() return self.settings.show_notifications end,
        function()
            self.settings.show_notifications = not self.settings.show_notifications
            self:saveSettings()
            return self.settings.show_notifications
                and "Status notifications enabled (errors always shown)"
                or "Status notifications hidden (errors still shown)"
        end
    )
end

--============================================================================--
-- Menu Integration
--============================================================================--

--[[--
Register plugin in KOReader's main menu.
]]
function TrmnlDisplay:addToMainMenu(menu_items)
    menu_items.trmnl = {
        text = _("TRMNL Display"),
        sorting_hint = "tools",
        sub_item_table = {
            self:createFetchMenuItem(),
            self:createLowPowerMenu(),
            self:createRtcTestMenuItem(),
            self:createConfigMenuItem(),
            self:createStartInteractiveMenuItem(),
            self:createAutoRefreshToggle(),
            self:createServerRefreshToggle(),
            self:createNotificationsToggle(),
            {
                text = _("E-ink refresh type"),
                sub_item_table = {
                    self:createRadioMenuItem("UI (balanced)", "refresh_type", "ui"),
                    self:createRadioMenuItem("Full (best quality)", "refresh_type", "full"),
                    self:createRadioMenuItem("Flash UI (with flash)", "refresh_type", "flashui"),
                    self:createRadioMenuItem("Partial (fastest)", "refresh_type", "partial"),
                }
            },
        }
    }
end

-- First-stage diagnostic. A successful callback is shown only when the user
-- returns to this menu, so the probe itself cannot disturb the sleeping display.
function TrmnlDisplay:getRtcTestProblem()
    if self.rtc_loop and self.rtc_loop.active then return "低功耗循环正在运行，请先停止循环。" end
    if not self.rtc_probe or not self.rtc_probe:available() then
        return "当前设备未提供可用的 Kindle RTC 唤醒接口。"
    elseif self.auto_refresh_enabled then
        return "请先关闭连续自动刷新，再进行 RTC 休眠测试。"
    elseif self.rtc_probe.active then
        return "RTC 测试已经在等待唤醒。"
    elseif self.rtc_refresh.active then
        return "第二阶段更新测试仍在运行。"
    end
    local share = require("pluginshare")
    if share.keepalive or share.pause_auto_suspend then
        return "请先关闭“保持运行（Keep alive）”，再进行休眠测试。"
    end
    local ok, prevented = pcall(function()
        return Device.powerd.lipc_handle:get_int_property("com.lab126.powerd", "preventScreenSaver")
    end)
    if not ok then return "无法读取系统休眠状态，请退出并重新启动 KOReader。" end
    if prevented ~= 0 then return "系统正在阻止休眠，请先关闭 Keep alive 或其他禁止休眠设置。" end
    if Device.powerd:isCharging() then
        return "本次测试需要验证真实休眠，请先拔掉 USB／充电线。"
    elseif NetworkMgr:isWifiOn() then
        return "请先关闭 Wi-Fi，以便验证从断网休眠状态开始的完整流程。"
    end
end

function TrmnlDisplay:confirmRtcTest()
    local problem = self:getRtcTestProblem()
    if problem then self:showInfo(problem); return end
    UIManager:show(require("ui/widget/confirmbox"):new{
        text = "登记一次 15 分钟后的 RTC 唤醒，然后自动进入休眠。\n\n测试期间不联网、不刷新画面，屏幕可能始终显示“已休眠”。请等待 17 分钟后，再按电源键回来查看测试结果。\n\n提前手动唤醒或退出 KOReader 会取消本次测试。",
        ok_text = "开始并休眠",
        cancel_text = "取消",
        ok_callback = function()
            local changed = self:getRtcTestProblem()
            if changed then self:showInfo(changed); return end
            if not self.rtc_probe:arm(15 * 60) then
                self:showError("RTC 测试登记失败，请查看测试结果或日志。")
            end
        end,
    })
end

function TrmnlDisplay:showRtcTestResult()
    local result = self.rtc_probe.result
    local states = {
        idle = "尚未测试", armed = "等待定时唤醒", fired = "RTC 回调已执行",
        user_resumed = "已提前手动唤醒，测试取消", cancelled = "已取消",
        interrupted = "KOReader 会话已结束，测试中断", failed = "登记失败",
    }
    local function stamp(value)
        return value and os.date("%m-%d %H:%M:%S", value) or "—"
    end
    UIManager:show(InfoMessage:new{
        text = "RTC 测试结果\n\n状态：" .. (states[result.state] or result.state)
            .. "\n登记时间：" .. stamp(result.armed_at)
            .. "\n计划唤醒：" .. stamp(result.target_at)
            .. "\n进入屏保：" .. stamp(result.suspend_event_at)
            .. "\n实际回调：" .. stamp(result.fired_at)
            .. "\n回调延迟：" .. (result.lateness_seconds and (result.lateness_seconds .. " 秒") or "—")
            .. "\n\n回调成功只证明 RTC 唤醒通路，不代表已验证联网刷新与再次休眠。\n日志：koreader/crash.log（TRMNL RTC）",
    })
end

function TrmnlDisplay:createRtcTestMenuItem()
    return {
        text = "低功耗测试",
        sub_item_table = {
            { text = "第二阶段：15 分钟后更新一次", callback = function() self:confirmRtcRefresh() end },
            { text = "查看第二阶段结果", callback = function() self:showRtcRefreshResult() end },
            { text = "查看联网诊断（修订 2）", callback = function() self:showRtcNetworkDiagnostics() end },
            { text = "15 分钟 RTC 唤醒测试", callback = function() self:confirmRtcTest() end },
            { text = "查看第一阶段结果", callback = function() self:showRtcTestResult() end },
            {
                text = "取消等待中的测试",
                enabled_func = function() return self.rtc_probe.active or self.rtc_refresh.active end,
                callback = function()
                    self.rtc_probe:cancel("cancelled")
                    self.rtc_refresh:cancel("cancelled")
                    self:showInfo("RTC 测试已取消。已写入系统的闹钟仍可能产生一次空唤醒。")
                end,
            },
        },
    }
end

function TrmnlDisplay:onTrmnlFetch()
    self:fetchAndDisplay(true)
end

function TrmnlDisplay:onTrmnlStartInteractive()
    logger.info("TRMNL: Starting interactive mode")
    -- If auto-refresh is already enabled, we just set the flag but don't
    -- touch the persistent setting.
    self.interactive_mode = true
    if not self.auto_refresh_enabled then
        self:startAutoRefresh()
    else
        -- Already running, but ensure image is displayed
        self:fetchAndDisplay(true)
    end
end

function TrmnlDisplay:performRtcFetch(mark)
    local socketutil = require("socketutil")
    local old_block, old_total = socketutil.block_timeout, socketutil.total_timeout
    self.rtc_network = true
    socketutil:set_timeout(8, 20)
    local tmp_path
    local ok, outcome, diagnostic = pcall(function()
        local response, metadata_error = self:fetchScreenMetadata()
        if not response then return "metadata_failed", metadata_error end
        if type(response.image_url) ~= "string" or not response.image_url:match("^https?://") then
            return "metadata_failed", Diagnostics.localError("metadata", "image_url", "Missing or invalid HTTP(S) image URL")
        end
        mark("metadata_at")
        -- Two owned slots preserve the currently displayed image on failures.
        local a = DataStorage:getDataDir() .. "/trmnl-rtc-a.png"
        local target = self.last_image_path ~= a and a or (DataStorage:getDataDir() .. "/trmnl-rtc-b.png")
        tmp_path = target .. ".part"
        local downloaded, download_error = self:downloadImage(response.image_url, tmp_path)
        if not downloaded then return "download_failed", download_error end
        if not os.rename(tmp_path, target) then
            return "file_failed", Diagnostics.localError("image", "file", "Cannot replace image cache file")
        end
        tmp_path = nil
        mark("downloaded_at")
        if not self:displayImage(target) then
            return "render_failed", Diagnostics.localError("image", "render", "Image renderer returned no image")
        end
        self.last_image_path = target
        -- Our fixed slots do not have the server filename used by the manual cache.
        self.last_image_filename = nil
        mark("displayed_at")
        return true
    end)
    socketutil:set_timeout(old_block, old_total)
    self.rtc_network = false
    if tmp_path then os.remove(tmp_path) end
    if not ok then
        return "fetch_exception", Diagnostics.localError("transfer", "exception", Diagnostics.clean(outcome, {self.settings.api_key}))
    end
    return outcome, diagnostic
end

function TrmnlDisplay:confirmRtcRefresh()
    local function problem()
        return self:getRtcTestProblem()
            or ((not self.settings.api_key or self.settings.api_key == "") and "请先配置设备令牌并验证手动更新。")
            or (type(NetworkMgr.restoreWifiAsync) ~= "function" and "当前系统缺少自动恢复 Wi-Fi 的接口。")
    end
    local reason = problem()
    if reason then self:showInfo(reason); return end
    UIManager:show(require("ui/widget/confirmbox"):new{
        text = "第二阶段·修订 2\n\n15 分钟后自动唤醒，Wi-Fi 连续就绪 10 秒后取图。临时接口错误最多请求 3 次，重试间隔 5 / 10 秒，然后关闭 Wi-Fi 并再次休眠。\n\n随后安排一次 3 分钟后的无联网复查。请在开始约 22 分钟后回来查看结果及联网诊断。\n\n测试期间可能短暂亮屏或闪屏，请勿操作设备。",
        ok_text = "开始并休眠", cancel_text = "取消",
        ok_callback = function()
            local changed = problem()
            if changed then self:showInfo(changed); return end
            if not self.rtc_refresh:arm(900) then self:showError("无法登记第二阶段测试。") end
        end,
    })
end

function TrmnlDisplay:showRtcRefreshResult()
    local r = self.rtc_refresh.result
    local states = {
        idle = "尚未测试", armed = "等待 RTC 唤醒", waking = "正在退出屏保",
        connecting = "正在连接 Wi-Fi", fetching = "正在拉图", closing_wifi = "正在关闭 Wi-Fi",
        checking_sleep = "等待休眠复查", verified = "已收到复查唤醒",
        interrupted = "会话中断", cancelled = "已取消", user_resumed = "手动唤醒，测试结束",
        alarm_failed = "无法登记 RTC", verify_alarm_failed = "无法登记复查", suspended_during_fetch = "取图期间进入屏保",
    }
    local outcomes = {
        updated = "画面已更新", wifi_failed = "开启 Wi-Fi 失败", wifi_timeout = "连接 Wi-Fi 超时",
        metadata_failed = "获取画面信息失败", download_failed = "下载失败", file_failed = "保存图片失败",
        render_failed = "绘制失败", fetch_exception = "取图异常", fetch_failed = "取图失败",
        wake_failed = "退出屏保失败", wake_timeout = "退出屏保超时",
    }
    local function stamp(t) return t and os.date("%H:%M:%S", t) or "—" end
    UIManager:show(InfoMessage:new{
        text = "第二阶段结果（" .. (r.version or "旧版") .. "）\n状态：" .. (states[r.state] or r.state)
            .. "\n取图：" .. (outcomes[r.outcome] or "尚未完成")
            .. "\n尝试：" .. tostring(r.attempt_count or 0) .. " / 3；末次错误：" .. Diagnostics.label(r.last_error)
            .. "\n计划 / RTC：" .. stamp(r.target_at) .. " / " .. stamp(r.rtc_at)
            .. "\nWi-Fi 已连接：" .. stamp(r.wifi_connected_at)
            .. "\n画面已绘制：" .. stamp(r.displayed_at)
            .. "\nWi-Fi 已关闭：" .. stamp(r.wifi_off_at)
            .. "\n再次进入屏保：" .. stamp(r.return_screensaver_at)
            .. "\n复查唤醒：" .. stamp(r.verify_at)
            .. "\n系统记录休眠：" .. (r.observed_suspend_seconds and (r.observed_suspend_seconds .. " 秒") or "—")
            .. "\n复查 Wi-Fi：" .. (r.verify_at and (r.verify_wifi_off and "已关闭" or "未确认关闭") or "—")
            .. "\n\n详细错误见“查看联网诊断”。请同时检查画面与 NAS 取图时间。",
    })
end

function TrmnlDisplay:showRtcNetworkDiagnostics()
    local r = self.rtc_refresh.result
    local lines = {"版本：" .. (r.version or "旧版，无详细诊断"), "只记录脱敏错误，不记录令牌或响应正文。"}
    for i, attempt in ipairs(r.attempts or {}) do
        lines[#lines + 1] = "\n第 " .. i .. " 次：" .. os.date("%H:%M:%S", attempt.started_at)
            .. " → " .. (attempt.finished_at and os.date("%H:%M:%S", attempt.finished_at) or "进行中")
        lines[#lines + 1] = "结果：" .. (attempt.outcome or "进行中")
        local d = attempt.diagnostic
        if d then
            lines[#lines + 1] = "阶段：" .. d.phase .. "；" .. Diagnostics.label(d)
            lines[#lines + 1] = "详情：" .. d.message
        end
    end
    UIManager:show(require("ui/widget/textviewer"):new{
        title = "联网诊断 · 修订 2", text = table.concat(lines, "\n"),
    })
end

function TrmnlDisplay:stopLowPower()
    self.rtc_loop:cancel("user_exit")
    if self.image_widget then UIManager:close(self.image_widget); self.image_widget = nil end
end

function TrmnlDisplay:showLowPowerWaitingScreen()
    if self.image_widget then return end
    if self.last_image_path and self:displayImage(self.last_image_path) then return end
    local width, height = Screen:getWidth(), Screen:getHeight()
    local content = require("ui/widget/container/centercontainer"):new{
        dimen = Geom:new{w = width, h = height},
        require("ui/widget/container/framecontainer"):new{padding = Screen:scaleBySize(16),
            background = require("ffi/blitbuffer").COLOR_WHITE,
            require("ui/widget/textwidget"):new{text = "正在连接看板…点按退出循环", face = require("ui/font"):getFace("infofont", 22)},
        },
    }
    self.image_widget = InputContainer:new{
        dimen = Geom:new{x = 0, y = 0, w = width, h = height}, content,
        ges_events = {TapClose = {GestureRange:new{ges = "tap", range = Geom:new{x = 0, y = 0, w = width, h = height}}}},
        onTapClose = function() self:stopLowPower(); return true end,
    }
    UIManager:show(self.image_widget)
    UIManager:setDirty(self.image_widget, "ui")
end

function TrmnlDisplay:createLowPowerMenu()
    local items = {
        {text = "开始：每 15 分钟循环", callback = function() self:confirmLowPower() end},
        {text = "停止循环并退出看板", enabled_func = function() return self.rtc_loop.active end,
            callback = function() self:stopLowPower() end},
        {text = "查看循环状态与日志", callback = function() self:showLowPowerStatus() end},
    }
    local rotations = {}
    for _, value in ipairs({0, 90, 180, 270}) do
        local angle = value
        rotations[#rotations + 1] = {text = tostring(angle) .. "°",
            checked_func = function() return (self.settings.sleep_battery_angle or 0) == angle end,
            callback = function() self.settings.sleep_battery_angle = angle; self:saveSettings() end}
    end
    items[#items + 1] = {text = "角落电量文字旋转", sub_item_table = rotations}
    return {text = "低功耗循环（15 分钟）", sub_item_table = items}
end

function TrmnlDisplay:confirmLowPower()
    local function problem()
        return self:getRtcTestProblem()
            or ((not self.settings.api_key or self.settings.api_key == "") and "请先配置令牌并验证手动更新。")
    end
    local reason = problem()
    if reason then self:showInfo(reason); return end
    UIManager:show(require("ui/widget/confirmbox"):new{
        text = "启动后立即更新一次，随后按 15 分钟间隔循环唤醒、更新、关网和休眠。失败也会关网回睡，下轮再试。\n\n休眠角落显示入睡时的电量，替代中央横幅。\n\n退出：按电源键唤醒，再在 30 秒内点一下看板；没有点按则继续回睡。也可从菜单停止。真正休眠时不能仅靠触摸唤醒。\n\n退出或重启 KOReader 不自动恢复循环。",
        ok_text = "开始循环", cancel_text = "取消",
        ok_callback = function()
            local changed = problem()
            if changed then self:showInfo(changed); return end
            self.sleep_badge = require("trmnl_sleep_badge"):new{
                owner = self.rtc_loop, device = Device, ui = UIManager,
                angle = function() return self.settings.sleep_battery_angle or 0 end,
                on_exit = function() self:stopLowPower() end,
            }
            self.sleep_badge:install()
            if not self.rtc_loop:start() then
                self.sleep_badge:uninstall(); self:showError("无法启动低功耗循环。")
            else
                self:showLowPowerWaitingScreen()
            end
        end,
    })
end

function TrmnlDisplay:showLowPowerStatus()
    local loop = self.rtc_loop
    local r = loop.result
    local names = {idle = "尚未启动", connecting = "连接与稳定等待", fetching = "取图中", waking = "正在唤醒",
        closing_wifi = "正在关网", armed = "等待下一轮", user_awake = "等待点按退出（30 秒）",
        updated = "更新成功", metadata_failed = "接口请求失败", download_failed = "下载失败",
        file_failed = "图片保存失败", render_failed = "绘制失败", fetch_exception = "取图异常",
        wifi_timeout = "联网超时", wifi_failed = "开启无线失败", interrupted = "会话结束",
        tap_exit = "点按退出", user_exit = "手动退出", badge_failed = "角标异常，已停止",
        suspended_during_fetch = "取图时被外部休眠，已停止", alarm_failed = "闹钟登记失败，已停止"}
    local function label(value) return names[value] or value or "尚未完成" end
    local function stamp(t) return t and os.date("%m-%d %H:%M:%S", t) or "—" end
    local lines = {"低功耗循环 · 版本 3", "运行：" .. (loop.active and "是" or "否"),
        "状态：" .. label(r.state), "轮次：" .. tostring(r.cycle or 0),
        "本轮取图：" .. label(r.outcome), "下一次：" .. (loop.active and stamp(r.next_target_at) or "已停止"),
        "上次入睡电量：" .. tostring(r.sleep_battery or "—") .. "%",
        "\n最近 48 轮（完整事件见 crash.log 中 TRMNL LOOP / RTC2）："}
    for _, entry in ipairs(loop.history) do
        lines[#lines + 1] = "\n#" .. entry.cycle .. " " .. stamp(entry.target_at) .. " " .. label(entry.outcome or entry.state)
            .. "\n取图尝试 " .. tostring(entry.attempt_count or 0) .. " 次；关网 " .. stamp(entry.wifi_off_at)
            .. "\n回睡 " .. stamp(entry.return_screensaver_at) .. "；电量 " .. tostring(entry.sleep_battery or "—") .. "%"
        for i, attempt in ipairs(entry.attempts or {}) do
            if attempt.diagnostic then lines[#lines + 1] = "尝试 " .. i .. "：" .. Diagnostics.label(attempt.diagnostic) .. " / " .. attempt.diagnostic.message end
        end
    end
    UIManager:show(require("ui/widget/textviewer"):new{title = "低功耗循环状态", text = table.concat(lines, "\n")})
end

require("trmnl_dashboard").install(TrmnlDisplay)
return TrmnlDisplay
