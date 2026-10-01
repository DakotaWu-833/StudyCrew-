"""One authoritative list of selectable IANA zones and their current offsets."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones


@lru_cache(maxsize=2)
def _options_for_hour(hour: int) -> tuple[dict[str, str], ...]:
    instant = datetime.fromtimestamp(hour * 3600, tz=timezone.utc)
    options: list[dict[str, str]] = []
    for name in sorted(available_timezones()):
        offset = instant.astimezone(ZoneInfo(name)).utcoffset()
        minutes = int(offset.total_seconds() // 60) if offset else 0
        sign = "+" if minutes >= 0 else "-"
        hours, remainder = divmod(abs(minutes), 60)
        gmt = f"GMT{sign}{hours:02d}:{remainder:02d}"
        options.append({"value": name, "label": f"({gmt}) {name.replace('_', ' ')}", "offset": gmt})
    return tuple(options)


def time_zone_options() -> tuple[dict[str, str], ...]:
    """Refresh offsets hourly so daylight-saving changes stay accurate."""

    hour = int(datetime.now(timezone.utc).timestamp() // 3600)
    return _options_for_hour(hour)
