-- Two bounded files owned exclusively by this plugin; never truncate crash.log.
local Journal = {}
function Journal.new(path, fallback)
    local function write(...)
        local args, count = {...}, select("#", ...)
        local ok = pcall(function()
            local existing = io.open(path, "rb")
            local size = existing and existing:seek("end") or 0
            if existing then existing:close() end
            if size >= 512 * 1024 then
                -- Fixed sibling path, not derived from remote data.
                os.remove(path .. ".1")
                assert(os.rename(path, path .. ".1"))
            end
            local parts = {os.date("%Y-%m-%d %H:%M:%S")}
            for i = 1, count do
                parts[#parts + 1] = tostring(args[i]):gsub("[%c]", " "):sub(1, 180)
            end
            local file = assert(io.open(path, "ab"))
            local written = file:write(table.concat(parts, " ") .. "\n")
            file:close()
            assert(written)
        end)
        if not ok then fallback.warn("Kindle board: journal write failed") end
    end
    return {info = write, warn = write, dbg = function() end}
end
return Journal
