"""Calendar, event detail, and RSVP calls for laget.se's JSON API."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from laget_cli.api.normalize import _normalize_event_type, _strip_html
from laget_cli.errors import ParseError
from laget_cli.session import API_URL, HTTP_TIMEOUT


API_BASE_URL = API_URL
_PAGE_SIZE = 50
_MAX_PAGES = 100
_STOCKHOLM = ZoneInfo("Europe/Stockholm")
_DETAIL_FIELDS = {"location", "assembly_time", "location_url", "notes", "rsvp"}


def _response_json(response):
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise ParseError("laget.se API returned invalid JSON") from exc


def _epoch_to_local_iso(value):
    """Return an offset-free Europe/Stockholm ISO timestamp."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(_STOCKHOLM).replace(tzinfo=None)
            return parsed.isoformat(timespec="seconds")
    if not isinstance(value, (int, float)):
        return None
    # The mobile API currently returns milliseconds, but tolerate seconds.
    seconds = value / 1000 if abs(value) >= 100_000_000_000 else value
    try:
        local = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(_STOCKHOLM)
    except (OSError, OverflowError, ValueError):
        return None
    return local.replace(tzinfo=None).isoformat(timespec="seconds")


def _time_from_value(value):
    if isinstance(value, dict):
        if not value.get("enabled"):
            return None
        value = value.get("date")
    normalized = _epoch_to_local_iso(value)
    if normalized:
        return normalized[11:16]
    if isinstance(value, str):
        import re

        match = re.search(r"\b(\d{1,2}:\d{2})\b", value)
        if match:
            return match.group(1)
    return None


def _site(event):
    value = event.get("site")
    return value if isinstance(value, dict) else {}


def _site_slug(event, fallback=None):
    site = _site(event)
    raw = site.get("url") or event.get("teamSlug") or fallback
    if not isinstance(raw, str):
        return fallback
    path = urlparse(raw).path if "://" in raw else raw
    slug = path.strip("/").split("/", 1)[0]
    return slug or fallback


def _site_id(event):
    value = _site(event).get("id", event.get("siteId"))
    return str(value) if value is not None else None


def _event_id(event):
    value = event.get("id", event.get("eventId"))
    return str(value) if value is not None else None


def _event_type(event):
    raw = event.get("eventType", event.get("type"))
    if isinstance(raw, str) and not raw.isdigit():
        return _normalize_event_type(raw)
    # Numeric event types are not documented; the title is the stable semantic
    # source used by the previous CLI as well.
    return _normalize_event_type(event.get("title"))


def _location(event):
    value = event.get("place", event.get("location"))
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("address")
    return value if isinstance(value, str) and value.strip() else None


def _location_url(event):
    value = event.get("place", event.get("location"))
    if isinstance(value, dict):
        return value.get("url") or value.get("mapUrl") or value.get("locationUrl")
    candidate = event.get("locationUrl") or event.get("mapUrl")
    return candidate if isinstance(candidate, str) and candidate else None


def _attending_response(value):
    if value is True or value == 1 or str(value).lower() in {"1", "yes", "true"}:
        return "yes"
    if value is False or value == 2 or str(value).lower() in {"2", "no", "false"}:
        return "no"
    return "unanswered"


def _concernee_states(event):
    """Return public responses and private per-member RSVP state."""
    raw_concernees = event.get("concernees")
    if not isinstance(raw_concernees, list):
        raw_concernees = []
    responses = []
    by_member = {}
    for concernee in raw_concernees:
        if not isinstance(concernee, dict) or concernee.get("id") is None:
            continue
        state = concernee.get("rsvp")
        if not isinstance(state, dict):
            # The app treats a concernee without an RSVP object as a person
            # associated with the event, not as an invited RSVP recipient.
            continue
        member_id = str(concernee["id"])
        state = dict(state)
        by_member[member_id] = state
        responses.append({
            "id": member_id,
            "name": concernee.get("name") if isinstance(concernee.get("name"), str) else None,
            "my_response": _attending_response(state.get("attending")),
            "answer": state.get("answer") if isinstance(state.get("answer"), str) else None,
            "reason": state.get("reason") if isinstance(state.get("reason"), str) else None,
        })
    return responses, by_member


def _rsvp_state(event, session_user_id=None):
    user_rsvp = event.get("userRsvp")
    if not isinstance(user_rsvp, dict):
        user_rsvp = None
    responses, by_member = _concernee_states(event)
    concernee_member_ids = set(by_member)
    if user_rsvp is not None and session_user_id is not None:
        by_member.setdefault(str(session_user_id), dict(user_rsvp))
    enabled = bool(event.get("rsvp")) or user_rsvp is not None or bool(by_member)
    if not enabled:
        return None, None, responses, by_member

    selected_member = None
    if len(concernee_member_ids) == 1:
        selected_member = next(iter(concernee_member_ids))
    elif user_rsvp is not None and session_user_id is not None:
        selected_member = str(session_user_id)
    state = dict(by_member.get(selected_member, user_rsvp or {}))
    response = _attending_response(state.get("attending"))
    event_id = _event_id(event)
    slug = _site_slug(event)
    url = None
    if event_id and selected_member and slug:
        url = f"https://www.laget.se/{slug}/Rsvp/{event_id}/{selected_member}"
    return {
        "yes": None,
        "no": None,
        "unanswered": None,
        "my_response": response,
        "url": url,
    }, state, responses, by_member


def _normalise_event(event, team_slug=None, include_team=False, user_id=None):
    if not isinstance(event, dict):
        raise ParseError("laget.se API event must be an object")
    event_id = _event_id(event)
    if event_id is None:
        raise ParseError("laget.se API event is missing id")
    start = _epoch_to_local_iso(
        event.get("dateStart", event.get("startDate", event.get("date")))
    )
    end = _epoch_to_local_iso(event.get("dateEnd", event.get("endDate")))
    rsvp, private_rsvp, responses, rsvp_by_member = _rsvp_state(
        event, session_user_id=user_id
    )
    notes = event.get("body", event.get("notes", event.get("description")))
    if isinstance(notes, str):
        notes = _strip_html(notes) or None
    else:
        notes = None
    cancelled = bool(
        event.get("cancelled", event.get("isCancelled", event.get("canceled", False)))
    )
    result = {
        "id": event_id,
        "type": _event_type(event),
        "title": event.get("title") if isinstance(event.get("title"), str) else None,
        "cancelled": cancelled,
        "date": start,
        "start_time": start[11:16] if start else None,
        "end_time": end[11:16] if end else None,
        "location": _location(event),
        "assembly_time": _time_from_value(event.get("assembly")),
        "location_url": _location_url(event),
        "notes": notes,
        "rsvp": rsvp,
    }
    if include_team:
        result = {
            "id": result["id"],
            "team": None,
            "team_slug": _site_slug(event, team_slug),
            **{key: value for key, value in result.items() if key != "id"},
            "responses": responses,
        }
    return result, {
        "site_id": _site_id(event),
        "user_rsvp": private_rsvp,
        "rsvp_by_member": rsvp_by_member,
        "eligible_member_ids": set(rsvp_by_member),
        "concernee_member_ids": {response["id"] for response in responses},
        "raw": event,
    }


def _event_cache(session):
    cache = getattr(session, "_laget_event_state", None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            setattr(session, "_laget_event_state", cache)
        except (AttributeError, TypeError):
            pass
    return cache


def _cache_event(session, event_id, state):
    _event_cache(session)[str(event_id)] = state


def _session_user_id(session):
    value = getattr(session, "user_id", None)
    if value is None:
        raise ParseError("Authenticated session is missing user_id")
    return str(value)


def _team_site_id(session, team_slug, explicit=None):
    if explicit is not None:
        return str(explicit)
    mapping = getattr(session, "team_site_ids", None)
    value = mapping.get(team_slug) if isinstance(mapping, dict) else None
    if isinstance(value, dict):
        value = value.get("site_id", value.get("id"))
    if value is None:
        raise ParseError(f"No site id is known for team '{team_slug}'")
    return str(value)


def _events_from_payload(payload):
    if not isinstance(payload, dict):
        raise ParseError("laget.se API event list must be an object")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ParseError("laget.se API event list is missing events")
    return events


def _fetch_feed(session, user_id, feed, start, end, site_id):
    cache = getattr(session, "_laget_event_feed_pages", None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            session._laget_event_feed_pages = cache
        except (AttributeError, TypeError):
            pass
    cache_key = (str(user_id), feed, start.isoformat(), end.isoformat())
    if cache_key in cache:
        return [raw for raw in cache[cache_key] if _site_id(raw) == site_id]

    collected = []
    for page_index in range(_MAX_PAGES):
        response = session.get(
            f"{API_BASE_URL}/v4/users/{user_id}/events/{feed}",
            params={"pageIndex": page_index, "pageSize": _PAGE_SIZE},
            timeout=HTTP_TIMEOUT,
        )
        page = _events_from_payload(_response_json(response))
        if not page:
            break

        page_dates = []
        for raw in page:
            if not isinstance(raw, dict):
                raise ParseError("laget.se API event list contains a non-object")
            when = _epoch_to_local_iso(raw.get("dateStart"))
            if when:
                page_dates.append(when[:10])
            if not when:
                continue
            if start.isoformat() <= when[:10] <= end.isoformat():
                collected.append(raw)

        if len(page) < _PAGE_SIZE:
            break
        # The app feeds are ordered away from today. Stop only after every
        # dated record in a full page has crossed the requested boundary.
        if page_dates and feed == "upcoming" and min(page_dates) > end.isoformat():
            break
        if page_dates and feed == "past" and max(page_dates) < start.isoformat():
            break
    else:
        raise ParseError("laget.se API event pagination exceeded safety limit")
    cache[cache_key] = collected
    return [raw for raw in collected if _site_id(raw) == site_id]


def fetch_calendar(session, team_slug, year, month):
    """Compatibility wrapper for one calendar month."""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = date.fromordinal(next_month.toordinal() - 1)
    return fetch_calendar_range(
        session,
        team_slug,
        date(year, month, 1).isoformat(),
        end.isoformat(),
    )


def fetch_calendar_range(
    session,
    team_slug,
    start_date,
    end_date,
    limit=None,
    detail_fields=None,
):
    """Fetch, filter, deduplicate and normalize a team's API events."""
    today = date.today()
    try:
        previous_year = today.replace(year=today.year - 1)
    except ValueError:
        previous_year = today.replace(year=today.year - 1, day=28)
    try:
        default_end = today.replace(year=today.year + 1)
    except ValueError:
        default_end = today.replace(year=today.year + 1, day=28)
    start = date.fromisoformat(start_date) if start_date else previous_year if end_date else today
    end = date.fromisoformat(end_date) if end_date else default_end
    if start > end:
        raise ValueError("calendar start date must be on or before end date")
    month_count = (end.year - start.year) * 12 + end.month - start.month + 1
    if month_count > 24:
        raise ValueError("calendar date range may span at most 24 months")

    user_id = _session_user_id(session)
    site_id = _team_site_id(session, team_slug)
    feeds = []
    if start <= today:
        feeds.append("past")
    if end >= today:
        feeds.append("upcoming")

    raw_events = []
    for feed in feeds:
        raw_events.extend(_fetch_feed(session, user_id, feed, start, end, site_id))

    deduplicated = {}
    for raw in raw_events:
        event_id = _event_id(raw)
        if event_id is not None:
            deduplicated[event_id] = raw
    normalized = []
    for raw in deduplicated.values():
        item, state = _normalise_event(raw, team_slug=team_slug, user_id=user_id)
        _cache_event(session, item["id"], state)
        normalized.append(item)
    normalized.sort(key=lambda item: item["date"] or "")
    if limit is not None:
        normalized = normalized[:limit]

    # All detail fields already exist in the JSON list. Retain the argument to
    # preserve the public function contract and selective CLI behavior.
    if detail_fields is not None:
        requested = set(detail_fields) & _DETAIL_FIELDS
        for item in normalized:
            for field in _DETAIL_FIELDS - requested:
                # Keep the stable schema; only requested fields carry values.
                item[field] = None
    return normalized


def fetch_event_detail(session, team_slug, event_id, site_id=None):
    """Fetch and normalize an event detail object from the JSON API."""
    resolved_site_id = _team_site_id(session, team_slug, explicit=site_id)
    response = session.get(
        f"{API_BASE_URL}/v4/events/{event_id}",
        params={"siteId": resolved_site_id},
        timeout=HTTP_TIMEOUT,
    )
    payload = _response_json(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
        raise ParseError("laget.se API event detail is missing event")
    detail, state = _normalise_event(
        payload["event"],
        team_slug=team_slug,
        include_team=True,
        user_id=_session_user_id(session),
    )
    state["site_id"] = state.get("site_id") or resolved_site_id
    _cache_event(session, event_id, state)
    return detail


def _ids_from_rsvp_url(rsvp_url):
    if not isinstance(rsvp_url, str):
        return None, None
    parts = urlparse(rsvp_url).path.strip("/").split("/")
    try:
        index = next(i for i, part in enumerate(parts) if part.casefold() == "rsvp")
    except StopIteration:
        return None, None
    event_id = parts[index + 1] if len(parts) > index + 1 else None
    user_id = parts[index + 2] if len(parts) > index + 2 else None
    return event_id, user_id


def _json_id(value):
    """Use the API's numeric ID type when a cached ID contains only digits."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def submit_rsvp(
    session,
    rsvp_url,
    response,
    comment=None,
    event_id=None,
    member_id=None,
):
    """Submit a yes/no RSVP using cached current values from event detail."""
    if response not in {"yes", "no"}:
        raise ValueError("response must be 'yes' or 'no'")
    url_event_id, _ = _ids_from_rsvp_url(rsvp_url)
    resolved_event_id = str(event_id or url_event_id or "")
    if not resolved_event_id:
        raise ParseError("Could not identify RSVP event")
    authenticated_user_id = _session_user_id(session)
    state = _event_cache(session).get(resolved_event_id, {})
    site_id = state.get("site_id")
    if site_id is None:
        raise ParseError("Could not identify RSVP site")
    eligible = {str(value) for value in state.get("eligible_member_ids", set())}
    concernees = {str(value) for value in state.get("concernee_member_ids", set())}
    if member_id is not None:
        resolved_member_id = str(member_id)
        if resolved_member_id not in eligible:
            raise ParseError(f"Member {resolved_member_id} is not eligible for this RSVP")
    elif len(concernees) == 1:
        resolved_member_id = next(iter(concernees))
    elif authenticated_user_id in eligible:
        resolved_member_id = authenticated_user_id
    else:
        raise ParseError("RSVP has multiple eligible members; member_id is required")
    rsvp_by_member = state.get("rsvp_by_member")
    rsvp_by_member = rsvp_by_member if isinstance(rsvp_by_member, dict) else {}
    current = rsvp_by_member.get(resolved_member_id)
    current = current if isinstance(current, dict) else {}
    payload = {
        "siteId": _json_id(site_id),
        "attending": 1 if response == "yes" else 2,
        "car": current.get("numCarSeats", current.get("car", 0)),
        "assembly": current.get("attendingAssembly", current.get("assembly", False)),
        "answer": current.get("answer") or "",
        "reason": current.get("reason") or "",
    }
    if comment is not None:
        payload["answer" if response == "yes" else "reason"] = comment
    result = session.put(
        f"{API_BASE_URL}/v1/events/{resolved_event_id}/rsvp/{resolved_member_id}",
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    result.raise_for_status()
    result.laget_member_id = resolved_member_id
    return result
