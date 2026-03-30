"""Shared normalization functions for laget.se HTML parsing."""

import re
import sys
from datetime import datetime, timedelta

_SWEDISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

_EVENT_TYPE_MAP = {
    "träning": "training",
    "traning": "training",
    "träningsmatch": "match",
    "traningsmatch": "match",
    "match": "match",
    "cup": "match",
    "tävling": "match",
    "tavling": "match",
    "möte": "meeting",
    "mote": "meeting",
    "aktivitet": "other",
}


def _normalize_datetime(raw):
    """Normalize a Swedish date string to YYYY-MM-DDTHH:MM:SS.

    Handles:
    - "DD mon YYYY" (e.g. "28 aug 2023")
    - "DD mon" (no year, infer year)
    - "idag" (today)
    - "igår" (yesterday)
    - "N timmar sedan" (N hours ago)
    - "N minuter sedan" (N minutes ago)

    Returns ISO string or None if unparseable.
    """
    if raw is None:
        return None
    raw = raw.strip()

    # "DD mon YYYY"
    m = re.fullmatch(r"(\d{1,2})\s+([a-zåäö]+)\s+(\d{4})", raw, re.IGNORECASE)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _SWEDISH_MONTHS.get(mon)
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}T00:00:00"

    # "DD mon" (no year)
    m = re.fullmatch(r"(\d{1,2})\s+([a-zåäö]+)", raw, re.IGNORECASE)
    if m:
        day, mon = int(m.group(1)), m.group(2).lower()
        month = _SWEDISH_MONTHS.get(mon)
        if month:
            today = datetime.now()
            year = today.year
            candidate = datetime(year, month, day)
            if (candidate - today).days > 183:
                year -= 1
            return f"{year:04d}-{month:02d}-{day:02d}T00:00:00"

    # "idag"
    if raw.lower() == "idag":
        d = datetime.now().date()
        return f"{d.isoformat()}T00:00:00"

    # "igår"
    if raw.lower() == "igår":
        d = (datetime.now() - timedelta(days=1)).date()
        return f"{d.isoformat()}T00:00:00"

    # "N timmar sedan"
    m = re.fullmatch(r"(\d+)\s+timmar?\s+sedan", raw, re.IGNORECASE)
    if m:
        hours = int(m.group(1))
        dt = datetime.now() - timedelta(hours=hours)
        dt = dt.replace(second=0, microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    # "N minuter sedan"
    m = re.fullmatch(r"(\d+)\s+minuter?\s+sedan", raw, re.IGNORECASE)
    if m:
        minutes = int(m.group(1))
        dt = datetime.now() - timedelta(minutes=minutes)
        dt = dt.replace(second=0, microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    # ISO passthrough: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}:\d{2})?", raw)
    if m:
        date_part = m.group(1)
        time_part = m.group(2) or "T00:00:00"
        return f"{date_part}{time_part}"

    print(f"Warning: could not parse datetime '{raw}'", file=sys.stderr)
    return None


def _normalize_time(raw):
    """Extract HH:MM from a time string.

    Returns "HH:MM" or None.
    """
    if raw is None:
        return None
    m = re.search(r"(\d{1,2}:\d{2})", raw)
    if m:
        return m.group(1)
    return None


def _normalize_event_type(raw):
    """Map a Swedish event type string to a normalized type.

    Returns one of: "training", "match", "meeting", "other".
    """
    if raw is None:
        return "other"
    normalized = raw.strip().lower()

    if normalized in _EVENT_TYPE_MAP:
        return _EVENT_TYPE_MAP[normalized]

    for key in sorted(_EVENT_TYPE_MAP, key=len, reverse=True):
        if normalized.startswith(key):
            return _EVENT_TYPE_MAP[key]

    return "other"


def _strip_html(raw):
    """Strip HTML tags from a string, converting block elements to newlines.

    Replaces <br>, </p>, </div> with newlines, strips remaining tags,
    collapses excessive blank lines, and strips leading/trailing whitespace.
    """
    if raw is None:
        return ""
    text = raw
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _infer_notification_type(url):
    """Infer notification type from a relative URL path.

    Returns one of: "news", "guestbook", "rsvp", "unknown".
    """
    if "/News/" in url:
        return "news"
    if "/Guestbook" in url:
        return "guestbook"
    if "/Event/" in url:
        return "rsvp"
    print(f"Warning: unknown notification URL '{url}'", file=sys.stderr)
    return "unknown"
