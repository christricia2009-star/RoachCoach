"""Turn vision/caption schedule slots into a compact week + map pin.

CloudKit Sighting.note is STRING 255, so the week has to fit in one line
the website (and iOS last-5 list) can parse:

  WEEKLY 2026-08-24: Mon CLOSED; Tue CLOSED; Wed 7–10 AM @ Eufay Wood Spray Park; ...
"""

from __future__ import annotations

import datetime
import re
from typing import Optional

CLOUDKIT_STRING_MAX = 255
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WD_INDEX = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _weekday_index(raw) -> Optional[int]:
    key = re.sub(r"[^a-z]", "", str(raw or "").lower())
    return _WD_INDEX.get(key)


def _parse_date(raw, today: datetime.date) -> Optional[datetime.date]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_hhmm(raw) -> tuple[Optional[int], int]:
    text = str(raw or "").strip().upper().replace(".", "")
    if not text:
        return None, 0
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", text)
    if not match:
        return None, 0
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if suffix == "PM" and hour < 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None, 0
    return hour, minute


def format_clock(hour: int, minute: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    if minute:
        return f"{hour12}:{minute:02d} {suffix}"
    return f"{hour12} {suffix}"


def format_hours(start, end) -> str:
    sh, sm = _parse_hhmm(start)
    if sh is None:
        return ""
    eh, em = _parse_hhmm(end)
    if eh is None:
        return format_clock(sh, sm)
    start_suffix = "AM" if sh < 12 else "PM"
    end_suffix = "AM" if eh < 12 else "PM"

    def short(hour: int, minute: int) -> str:
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute:02d}" if minute else str(hour12)

    if start_suffix == end_suffix:
        return f"{short(sh, sm)}–{short(eh, em)} {start_suffix}"
    return f"{format_clock(sh, sm)}–{format_clock(eh, em)}"


def monday_of(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def _clean_place(raw) -> Optional[str]:
    text = " ".join(str(raw or "").split()).strip(" ,.-")
    if len(text) < 4:
        return None
    if text.lower() in {"closed", "none", "n/a", "unknown"}:
        return None
    return text[:80]


def normalize_week(
    slots: list,
    today: datetime.date,
    kind: str = "",
) -> list[dict]:
    """Return 7 days (weekly flyer) or 1 day (we're-here-now)."""
    parsed: list[dict] = []
    for slot in slots or []:
        if not isinstance(slot, dict):
            continue
        closed = bool(slot.get("closed"))
        place = _clean_place(slot.get("location_text"))
        if not closed and not place:
            continue
        wd_i = _weekday_index(slot.get("weekday"))
        slot_date = _parse_date(slot.get("date"), today)
        parsed.append(
            {
                "date": slot_date,
                "weekday_index": wd_i,
                "closed": closed,
                "location_text": None if closed else place,
                "start_time": slot.get("start_time"),
                "end_time": slot.get("end_time"),
            }
        )
    if not parsed:
        return []

    dated = [row["date"] for row in parsed if row["date"]]
    anchor = dated[0] if dated else today
    if abs((anchor - today).days) > 10:
        anchor = today
    week_monday = monday_of(anchor)

    by_offset: dict[int, dict] = {}
    for row in parsed:
        offset = None
        if row["date"]:
            offset = (row["date"] - week_monday).days
        elif row["weekday_index"] is not None:
            offset = row["weekday_index"]
        if offset is None or offset < 0 or offset > 6:
            continue
        existing = by_offset.get(offset)
        if existing and not existing.get("closed") and row.get("closed"):
            continue
        by_offset[offset] = row

    weekly = (
        str(kind or "").lower() == "weekly_schedule"
        or len(by_offset) >= 2
        or any(row.get("closed") for row in by_offset.values())
    )
    if not weekly:
        if not by_offset:
            return []
        offset, row = next(iter(sorted(by_offset.items())))
        day = week_monday + datetime.timedelta(days=offset)
        return [
            {
                "date": day.isoformat(),
                "weekday": WEEKDAYS[offset],
                "closed": bool(row.get("closed")),
                "location_text": row.get("location_text"),
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
            }
        ]

    days = []
    for offset, weekday in enumerate(WEEKDAYS):
        day = week_monday + datetime.timedelta(days=offset)
        row = by_offset.get(offset)
        if row:
            days.append(
                {
                    "date": day.isoformat(),
                    "weekday": weekday,
                    "closed": bool(row.get("closed")),
                    "location_text": None if row.get("closed") else row.get("location_text"),
                    "start_time": row.get("start_time"),
                    "end_time": row.get("end_time"),
                }
            )
        else:
            days.append(
                {
                    "date": day.isoformat(),
                    "weekday": weekday,
                    "closed": True,
                    "location_text": None,
                    "start_time": None,
                    "end_time": None,
                }
            )
    return days


def format_weekly_note(days: list[dict]) -> str:
    if not days:
        return ""
    week_start = days[0]["date"]
    parts = []
    for day in days:
        wd = day["weekday"]
        if day.get("closed") or not day.get("location_text"):
            parts.append(f"{wd} CLOSED")
            continue
        hours = format_hours(day.get("start_time"), day.get("end_time"))
        place = day["location_text"]
        if hours:
            parts.append(f"{wd} {hours} @ {place}")
        else:
            parts.append(f"{wd} @ {place}")
    note = f"WEEKLY {week_start}: " + "; ".join(parts)
    if len(note) <= CLOUDKIT_STRING_MAX:
        return note
    short_parts = []
    for day in days:
        wd = day["weekday"]
        if day.get("closed") or not day.get("location_text"):
            short_parts.append(f"{wd} X")
            continue
        hours = format_hours(day.get("start_time"), day.get("end_time"))
        place = day["location_text"].split(",")[0][:28]
        bit = f"{wd} {hours} @{place}" if hours else f"{wd} @{place}"
        short_parts.append(bit)
    note = f"WEEKLY {week_start}: " + "; ".join(short_parts)
    return note[:CLOUDKIT_STRING_MAX]


def pick_schedule_pin(days: list[dict], today: datetime.date) -> Optional[dict]:
    """Park to drop on the map: today/next open, else last open this week."""
    open_days = [
        day
        for day in days
        if not day.get("closed") and day.get("location_text")
    ]
    if not open_days:
        return None
    today_iso = today.isoformat()
    for day in open_days:
        if day["date"] >= today_iso:
            return day
    return open_days[-1]


def slot_datetime(day: dict, tz) -> datetime.datetime:
    raw_date = datetime.date.fromisoformat(day["date"])
    hour, minute = _parse_hhmm(day.get("start_time") or "11:00")
    if hour is None:
        hour, minute = 11, 0
    return datetime.datetime(
        raw_date.year,
        raw_date.month,
        raw_date.day,
        hour,
        minute,
        tzinfo=tz,
    )


def week_end_datetime(days: list[dict], tz) -> datetime.datetime:
    start = datetime.date.fromisoformat(days[0]["date"])
    monday = monday_of(start)
    return datetime.datetime.combine(
        monday + datetime.timedelta(days=8),
        datetime.time(8, 0),
        tzinfo=tz,
    )
