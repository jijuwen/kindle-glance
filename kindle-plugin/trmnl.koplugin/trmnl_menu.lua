local Menu = {}

-- Pin only our entry; preserve the relative order of every other menu item.
-- Called at runtime, without editing KOReader's files or saved menu settings.
function Menu.pin(order)
    if type(order.tools) ~= "table" then return end
    for _, entries in pairs(order) do
        if type(entries) == "table" then
            for i = #entries, 1, -1 do
                if entries[i] == "trmnl" then table.remove(entries, i) end
            end
        end
    end
    table.insert(order.tools, 1, "trmnl")
end

return Menu
