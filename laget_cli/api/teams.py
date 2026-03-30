"""laget.se teams and children API."""

import re
from html import unescape

from laget_cli.errors import ParseError
from laget_cli.session import AJAX_HEADERS, BASE_URL, HTTP_TIMEOUT


def fetch_teams(session):
    """Fetch the user's teams from /Common/UserMenu/Pages.

    Returns a list of dicts: [{"name": ..., "club": ..., "team_slug": ...}]
    """
    resp = session.get(
        f"{BASE_URL}/Common/UserMenu/Pages",
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_teams(resp.text)


def fetch_children(session):
    """Fetch the user's children from /User/Children.

    Returns a list of dicts: [{"name": ..., "id": ...}]
    """
    resp = session.get(
        f"{BASE_URL}/User/Children",
        params={"returnUrl": "http://www.laget.se/"},
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_children(resp.text)


def _parse_teams(html):
    """Parse team list HTML from /Common/UserMenu/Pages.

    Extracts team name, club name, and URL slug from the popover list HTML.
    """
    teams = []
    for match in re.finditer(
        r'<a\s+class="popoverList__contentWrapper"\s+href="([^"]*)">'
        r'[\s\S]*?'
        r'<p\s+class="popoverList__name"><b>(.*?)</b></p>'
        r'[\s\S]*?'
        r'<small\s+class="popoverList__club">(.*?)</small>',
        html,
    ):
        url = match.group(1).strip()
        url_slug = url.rstrip("/").rsplit("/", 1)[-1]
        name = unescape(match.group(2).strip())
        club = unescape(match.group(3).strip())
        teams.append({"name": name, "club": club, "team_slug": url_slug})

    if not teams and "popoverList" in html:
        raise ParseError("Found popoverList HTML but failed to parse any teams from /Common/UserMenu/Pages")

    return teams


def _parse_children(html):
    """Parse children list HTML from /User/Children.

    Extracts child ID from ShowChildProfileSettings('id') and
    child name from adjacent text content.
    """
    children = []
    for match in re.finditer(
        r"ShowChildProfileSettings\('(\d+)'\).*?>(.*?)</a>",
        html,
        re.DOTALL,
    ):
        child_id = match.group(1)
        raw_name = match.group(2)
        name = re.sub(r"<[^>]+>", "", raw_name).strip()
        if child_id and name:
            children.append({"name": name, "id": child_id})

    return children


def fetch_roster_member_ids(session, team_slug):
    """Fetch member IDs from a team's roster page.

    Returns a set of member ID strings extracted from /Troop/{memberId}/ links.
    """
    resp = session.get(
        f"{BASE_URL}/{team_slug}/Troop",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return set(re.findall(r"/Troop/(\d+)/", resp.text))


def sync_child_team_mapping(session, teams, children):
    """Build a child-to-team mapping by checking each team's roster.

    Returns a dict: {child_id: team_slug} for each child found on a team.
    """
    child_ids = {c["id"] for c in children}
    mapping = {}
    for team in teams:
        member_ids = fetch_roster_member_ids(session, team["team_slug"])
        for child_id in child_ids:
            if child_id in member_ids:
                mapping[child_id] = team["team_slug"]
    return mapping


def filter_teams_by_club(teams, club_filter):
    """Filter teams by club name (case-insensitive substring match)."""
    if not club_filter:
        return teams
    lower_filter = club_filter.lower()
    return [t for t in teams if lower_filter in t["club"].lower()]
