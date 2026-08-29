"""Authenticated content feed from the laget.se mobile JSON API.

The mobile API does not expose the website's legacy notification list. The
``notifications`` command therefore consumes the authenticated news feed.
"""

from urllib.parse import urlparse

from laget_cli.api.normalize import _normalize_json_datetime, _strip_html
from laget_cli.errors import ParseError
from laget_cli.session import API_URL, HTTP_TIMEOUT


def _string_id(value):
    return None if value is None else str(value)


def _display_name(value):
    if not isinstance(value, dict):
        return None
    display_names = value.get("displayNames")
    if isinstance(display_names, dict):
        return display_names.get("long") or display_names.get("short")
    return value.get("displayName") or value.get("name")


def _slug_from_url(url):
    if not isinstance(url, str) or not url:
        return None
    parsed = urlparse(url)
    path = parsed.path if parsed.scheme or parsed.netloc else url
    parts = [part for part in path.split("/") if part]
    return parts[0] if parts else None


def _publisher_name(item):
    publisher = item.get("publisher")
    if not isinstance(publisher, dict):
        return None
    if item.get("showPublisher") is False:
        return None
    return publisher.get("name") or publisher.get("displayName")


def _normalize_feed_item(item):
    """Normalize one native feed item while retaining its native semantics."""
    if not isinstance(item, dict):
        return None
    site = item.get("site") if isinstance(item.get("site"), dict) else {}
    url = item.get("url")
    return {
        "id": _string_id(item.get("id")),
        "type": item.get("type") or "unknown",
        "title": item.get("title"),
        "body": _strip_html(item.get("content") or item.get("description")),
        "date": _normalize_json_datetime(item.get("date")),
        "author": _publisher_name(item),
        "comment_count": item.get("numComments", 0),
        "site_id": _string_id(site.get("id")),
        "site_name": _display_name(site),
        "team": None,
        "team_slug": _slug_from_url(url or site.get("url")),
        "url": url,
    }


def fetch_feed(session, limit=None, max_pages=20, page_size=50, since=None):
    """Fetch a bounded, deduplicated set of authenticated feed items.

    ``since`` may be an ISO date or timestamp. It is only used for an early
    stop when a page is demonstrably sorted newest-first; callers remain
    responsible for applying their exact date filter.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    if page_size < 1 or page_size > 50:
        raise ValueError("page_size must be between 1 and 50")
    if limit == 0:
        return []

    results = []
    seen = set()
    since_date = str(since)[:10] if since is not None else None
    for page_index in range(max_pages):
        response = session.get(
            f"{API_URL}/v5/users/{session.user_id}/news",
            params={
                "pageIndex": page_index,
                "pageSize": page_size,
                "excerptLength": 100,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ParseError("Invalid JSON returned for content feed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
            raise ParseError("Content feed response is missing news")

        raw_items = payload["news"]
        page_dates = []
        for raw_item in raw_items:
            item = _normalize_feed_item(raw_item)
            if item is None:
                continue
            key = (item["type"], item["id"], item["site_id"])
            if key not in seen:
                seen.add(key)
                results.append(item)
                if limit is not None and len(results) >= limit:
                    return results[:limit]
            if item["date"]:
                page_dates.append(item["date"][:10])

        if not raw_items or len(raw_items) < page_size:
            break
        is_descending = page_dates == sorted(page_dates, reverse=True)
        if since_date and page_dates and is_descending and page_dates[-1] < since_date:
            break
    return results


def fetch_notifications(session, **kwargs):
    """Compatibility name for the content feed used by the CLI command."""
    return fetch_feed(session, **kwargs)


def resolve_team_names(notifications, teams):
    """Resolve feed site IDs to the CLI team's display name and slug."""
    by_site_id = {
        _string_id(team.get("_site_id")): team
        for team in teams
        if team.get("_site_id") is not None
    }
    by_slug = {
        team.get("team_slug"): team
        for team in teams
        if team.get("team_slug")
    }
    for item in notifications:
        team = by_site_id.get(_string_id(item.get("site_id")))
        if team is None:
            team = by_slug.get(item.get("team_slug"))
        if team is not None:
            item["team"] = team.get("name")
            item["team_slug"] = team.get("team_slug")
    return notifications
