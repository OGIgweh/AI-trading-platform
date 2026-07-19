from __future__ import annotations

from datetime import datetime, timezone, time
from functools import lru_cache
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

# Fallback holiday/early-close table. pandas_market_calendars is preferred when installed,
# but this keeps Render from showing the wrong status if the dependency is unavailable.
_US_MARKET_HOLIDAYS = {
    # 2026 NYSE holidays
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027 NYSE holidays
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
_EARLY_CLOSES = {
    "2026-11-27": time(13, 0),
    "2026-12-24": time(13, 0),
    "2027-11-26": time(13, 0),
}


def now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(NY_TZ)


@lru_cache(maxsize=16)
def _calendar_status_for_minute(minute_bucket: str) -> tuple[str, str]:
    """Return regular-session NYSE status using an exchange calendar when available."""
    del minute_bucket
    now = now_et()
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=now.date().isoformat(), end_date=now.date().isoformat())
        if schedule.empty:
            return "CLOSED", "NYSE calendar: no regular trading session today."
        market_open = schedule.iloc[0]["market_open"].to_pydatetime().astimezone(NY_TZ)
        market_close = schedule.iloc[0]["market_close"].to_pydatetime().astimezone(NY_TZ)
        if market_open <= now <= market_close:
            return "OPEN", f"NYSE regular session open until {market_close.strftime('%-I:%M %p %Z')}."
        if now < market_open:
            return "CLOSED", f"NYSE regular session opens at {market_open.strftime('%-I:%M %p %Z')}."
        return "CLOSED", f"NYSE regular session closed at {market_close.strftime('%-I:%M %p %Z')}."
    except Exception:
        return _fallback_status(now)


def _fallback_status(now: datetime) -> tuple[str, str]:
    date_key = now.date().isoformat()
    if now.weekday() >= 5:
        return "CLOSED", "Weekend: NYSE regular session is closed."
    if date_key in _US_MARKET_HOLIDAYS:
        return "CLOSED", "NYSE holiday: regular session is closed."
    open_t = time(9, 30)
    close_t = _EARLY_CLOSES.get(date_key, time(16, 0))
    current_t = now.time()
    if open_t <= current_t <= close_t:
        return "OPEN", f"Fallback NYSE regular session window {open_t.strftime('%I:%M %p')}–{close_t.strftime('%I:%M %p')} ET."
    if current_t < open_t:
        return "CLOSED", "Before NYSE regular session."
    return "CLOSED", "After NYSE regular session."


def market_status() -> str:
    now = now_et()
    bucket = now.strftime("%Y-%m-%d-%H-%M")
    return _calendar_status_for_minute(bucket)[0]


def market_status_detail() -> dict:
    now = now_et()
    bucket = now.strftime("%Y-%m-%d-%H-%M")
    status, reason = _calendar_status_for_minute(bucket)
    return {
        "status": status,
        "reason": reason,
        "timezone": "America/New_York",
        "checked_at_et": now.isoformat(),
        "session": "NYSE regular session",
    }
