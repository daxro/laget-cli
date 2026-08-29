"""laget.se team resources from the mobile JSON API."""

from urllib.parse import urlparse

from laget_cli.errors import ParseError
from laget_cli.session import API_URL, HTTP_TIMEOUT


def _resource_id(value):
    """Return a stable string ID, or ``None`` for a missing value."""
    return None if value is None else str(value)


def _slug_from_page_url(url):
    """Extract the first path segment from a laget.se page URL."""
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlparse(url.strip())
    path = parsed.path if parsed.scheme or parsed.netloc else url.strip().split("?", 1)[0]
    parts = [part for part in path.split("/") if part]
    return parts[0] if parts else None


def _json_object(response, resource):
    try:
        payload = response.json()
    except ValueError as exc:
        raise ParseError(f"Invalid JSON returned for {resource}") from exc
    if not isinstance(payload, dict):
        raise ParseError(f"Expected a JSON object for {resource}")
    return payload


def fetch_teams(session):
    """Fetch and join the authenticated user's teams and pages.

    The mobile API exposes display metadata and page URLs separately. Internal
    keys prefixed with ``_`` are retained so command handlers can address other
    API resources without exposing them in the public CLI contract.
    """
    user_id = session.user_id
    teams_response = session.get(
        f"{API_URL}/v4/users/{user_id}/teams",
        timeout=HTTP_TIMEOUT,
    )
    teams_response.raise_for_status()
    pages_response = session.get(
        f"{API_URL}/v4/users/{user_id}/pages",
        timeout=HTTP_TIMEOUT,
    )
    pages_response.raise_for_status()

    teams_payload = _json_object(teams_response, "teams")
    pages_payload = _json_object(pages_response, "pages")
    raw_teams = teams_payload.get("teams")
    raw_pages = pages_payload.get("pages")
    if not isinstance(raw_teams, list) or not isinstance(raw_pages, list):
        raise ParseError("Team API response is missing teams or pages")

    pages_by_id = {
        _resource_id(page.get("id")): page
        for page in raw_pages
        if isinstance(page, dict) and page.get("id") is not None
    }
    teams = []
    for raw_team in raw_teams:
        if not isinstance(raw_team, dict):
            continue
        site_id = _resource_id(raw_team.get("id"))
        page = pages_by_id.get(site_id, {})
        page_url = page.get("url") if isinstance(page, dict) else None
        parent_site = raw_team.get("parentSite")
        club = (
            parent_site.get("displayName")
            if isinstance(parent_site, dict)
            else raw_team.get("displayName")
        )
        teams.append(
            {
                "name": raw_team.get("displayName"),
                "club": club,
                "team_slug": _slug_from_page_url(page_url),
                "_site_id": site_id,
                "_page_url": page_url,
            }
        )
    return teams


def fetch_children(session):
    """Return no children because the mobile API has no child-list resource."""
    return []


def sync_child_team_mapping(session, teams, children):
    """Return an empty mapping; roster HTML is deliberately not consulted."""
    return {}


def filter_teams_by_club(teams, club_filter):
    """Filter teams by club name using a case-insensitive substring match."""
    if not club_filter:
        return teams
    lower_filter = club_filter.casefold()
    return [
        team
        for team in teams
        if isinstance(team.get("club"), str)
        and lower_filter in team["club"].casefold()
    ]
