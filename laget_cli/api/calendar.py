"""laget.se calendar API - fetch and parse events."""

import re
from datetime import date
from html import unescape

from laget_cli.api.normalize import _normalize_event_type, _normalize_time, _strip_html
from laget_cli.session import AJAX_HEADERS, BASE_URL, HTTP_TIMEOUT


def fetch_calendar(session, team_slug, year, month):
    """Fetch calendar events for a single month.

    GET /{team_slug}/Event/FilterEvents?year={year}&month={month}&siteType=Team&types=2&types=4&types=6&types=7

    Returns a list of event dicts for that month.
    """
    resp = session.get(
        f"{BASE_URL}/{team_slug}/Event/FilterEvents",
        params={
            "year": year,
            "month": month,
            "siteType": "Team",
            "types": [2, 4, 6, 7],
        },
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_calendar_month(resp.text, year, month)


def fetch_calendar_range(session, team_slug, start_date, end_date):
    """Fetch calendar events across a date range, spanning multiple months if needed.

    Args:
        session: authenticated requests.Session
        team_slug: team URL slug
        start_date: ISO date string "YYYY-MM-DD" or None (defaults to 1 year ago)
        end_date: ISO date string "YYYY-MM-DD" or None (defaults to 1 year from now)

    Returns a deduplicated, sorted list of event dicts.
    """
    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today.replace(year=today.year - 1)
    end = date.fromisoformat(end_date) if end_date else today.replace(year=today.year + 1)

    # Build list of (year, month) pairs to fetch
    months = []
    current_year = start.year
    current_month = start.month
    while (current_year, current_month) <= (end.year, end.month):
        months.append((current_year, current_month))
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    all_events = []
    seen_ids = set()
    for year, month in months:
        events = fetch_calendar(session, team_slug, year, month)
        for event in events:
            if event["id"] not in seen_ids:
                seen_ids.add(event["id"])
                all_events.append(event)

    all_events.sort(key=lambda e: e["date"])
    return all_events


def _extract_outer_li_content(html, start_pos):
    """Return the content inside the <li> starting at start_pos, balancing nested <li> tags.

    Returns (content, end_pos) where content is the HTML between the outer opening
    and closing <li> tags (exclusive), and end_pos is the position after </li>.
    Returns (None, start_pos) if parsing fails.
    """
    # Find the end of the opening tag
    open_end = html.find(">", start_pos)
    if open_end == -1:
        return None, start_pos
    pos = open_end + 1
    depth = 1

    while pos < len(html) and depth > 0:
        next_open = html.find("<li", pos)
        next_close = html.find("</li>", pos)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 3
        else:
            depth -= 1
            if depth == 0:
                return html[open_end + 1:next_close], next_close + 5
            pos = next_close + 5

    return None, start_pos


def _parse_calendar_month(html, year, month):
    """Parse the ul.fullCalendar HTML fragment for a single month.

    Returns a list of event dicts.
    """
    events = []

    # Find all day container opening tags: <li class="fullCalendar__day..." data-day="N">
    for day_tag_match in re.finditer(
        r'<li\b[^>]*class="fullCalendar__day[^"]*"[^>]*data-day="(\d+)"[^>]*>',
        html,
    ):
        day = int(day_tag_match.group(1))
        tag_start = day_tag_match.start()

        day_html, _ = _extract_outer_li_content(html, tag_start)
        if not day_html:
            continue

        # Find event items within this day
        for item_tag_match in re.finditer(
            r'<li\b[^>]*class="fullCalendar__item"[^>]*id="js-event-\d+-(\d+)"[^>]*>',
            day_html,
        ):
            event_id = item_tag_match.group(1)
            item_start = item_tag_match.start()
            item_html, _ = _extract_outer_li_content(day_html, item_start)
            if not item_html:
                continue

            # Skip ad slots
            if re.search(r'class="event_ad-|div-gpt-', item_html):
                continue

            event = _parse_event_item(item_html, event_id, year, month, day)
            if event:
                events.append(event)

    return events


def _parse_event_item(html, event_id, year, month, day):
    """Parse a single fullCalendar__item li into an event dict."""
    # Start time: first <span class="fullCalendar__time">
    start_time = None
    m = re.search(r'<span class="fullCalendar__time">(\d{1,2}:\d{2})</span>', html)
    if m:
        start_time = m.group(1)

    # End time: <span class="fullCalendar__time float--left"> with arrow icon and <br>
    end_time = None
    m = re.search(
        r'<span class="fullCalendar__time float--left">\s*<i[^>]*></i><br>(\d{1,2}:\d{2})',
        html,
    )
    if m:
        end_time = m.group(1)

    # Event title: text after icon inside <p class="fullCalendar__text">
    title = None
    m = re.search(
        r'<p class="fullCalendar__text">\s*(?:<i[^>]*></i>)?\s*(.*?)\s*</p>',
        html,
        re.DOTALL,
    )
    if m:
        raw_title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        title = unescape(raw_title) if raw_title else None

    event_type = _normalize_event_type(title)

    # Build ISO datetime
    if start_time:
        date_str = f"{year:04d}-{month:02d}-{day:02d}T{start_time}:00"
    else:
        date_str = f"{year:04d}-{month:02d}-{day:02d}T00:00:00"

    return {
        "id": event_id,
        "type": event_type,
        "title": title,
        "cancelled": False,
        "date": date_str,
        "start_time": start_time,
        "end_time": end_time,
        "location": None,
        "assembly_time": None,
        "location_url": None,
        "notes": None,
        "rsvp": None,
    }


def fetch_event_detail(session, team_slug, event_id):
    """Fetch the event detail fragment for a single event.

    GET /{team_slug}/Event/Single?eventId={event_id}

    Returns a parsed event detail dict.
    """
    resp = session.get(
        f"{BASE_URL}/{team_slug}/Event/Single",
        params={"eventId": event_id},
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_event_detail(resp.text, event_id, team_slug)


def _parse_event_detail(html, event_id, team_slug):
    """Parse the bare HTML fragment returned by Event/Single.

    Returns an event detail dict with location, assembly_time, notes, rsvp,
    and null for fields only available in the list view (type, title, date, etc.).
    """
    location = _parse_location(html)
    location_url = _parse_maps_url(html)
    assembly_time = _parse_assembly_time(html)
    notes = _parse_notes(html)
    rsvp = _parse_rsvp(html)

    return {
        "id": str(event_id),
        "team": None,
        "team_slug": team_slug,
        "type": None,
        "title": None,
        "cancelled": False,
        "date": None,
        "start_time": None,
        "end_time": None,
        "assembly_time": assembly_time,
        "location": location,
        "location_url": location_url,
        "notes": notes,
        "rsvp": rsvp,
        "responses": [],
    }


def _parse_location(html):
    """Extract location name from the map marker icon text node."""
    m = re.search(
        r'<i class="fullCalendar__icon--place icon-map-marker"></i>\s*(.*?)(?:\s*</div>|\s*<a\b)',
        html,
        re.DOTALL,
    )
    if m:
        raw = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return unescape(raw) if raw else None
    return None


def _parse_maps_url(html):
    """Extract Google Maps URL from an <a href> or inline text (Övrig platsinfo)."""
    # Check for <a href="...google.com/maps/search/...">
    m = re.search(r'href="(https://www\.google\.com/maps/search/[^"]*)"', html)
    if m:
        return m.group(1)

    # Check inline URL in Övrig platsinfo text
    m = re.search(
        r'Övrig platsinfo:\s*</span>\s*([\s\S]*?)</div>',
        html,
    )
    if m:
        inline = re.search(r'(https://www\.google\.com/maps/search/\S+)', m.group(1))
        if inline:
            return inline.group(1)

    return None


def _parse_assembly_time(html):
    """Extract assembly time from Samlingstid label."""
    m = re.search(r'Samlingstid:\s*</span>\s*(\d{1,2}:\d{2})', html)
    if m:
        return _normalize_time(m.group(1))
    return None


def _parse_notes(html):
    """Extract notes from Anteckning label."""
    m = re.search(r'Anteckning:\s*</span>([\s\S]*?)</div>', html)
    if m:
        raw = m.group(1).strip()
        cleaned = _strip_html(raw)
        return cleaned if cleaned else None
    return None


def _parse_rsvp(html):
    """Extract RSVP status from Anmälan label.

    Returns a dict with my_response or None if no RSVP section found.
    """
    if "Anmälan:" not in html:
        return None

    # Find the RSVP link text
    m = re.search(
        r'<a\s+href="[^"]*/Rsvp/[^"]*">\s*(.*?)\s*</a>',
        html,
        re.DOTALL,
    )
    if not m:
        return None

    rsvp_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    my_response = "unanswered"
    if re.search(r'har svarat kommer inte', rsvp_text, re.IGNORECASE):
        my_response = "no"
    elif re.search(r'har svarat kommer', rsvp_text, re.IGNORECASE):
        my_response = "yes"
    elif re.search(r'har ej svarat', rsvp_text, re.IGNORECASE):
        my_response = "unanswered"

    return {
        "yes": None,
        "no": None,
        "unanswered": None,
        "my_response": my_response,
    }
