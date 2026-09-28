"""Per-render preferences; ContextVar isolates concurrent rendering threads."""
from contextvars import ContextVar

preferences = ContextVar("display_preferences", default={})


def temperature_unit():
    return "°F" if preferences.get().get("temperature_unit") == "fahrenheit" else "°C"


def clock(value, pattern="%H:%M"):
    if preferences.get().get("hour_format") == "12":
        pattern = pattern.replace("%H:%M", "%I:%M %p")
    return value.strftime(pattern)
