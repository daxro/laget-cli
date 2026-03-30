"""laget.se notifications API."""

import re
from html import unescape

from laget_cli.api.normalize import _infer_notification_type
from laget_cli.session import AJAX_HEADERS, BASE_URL, HTTP_TIMEOUT

# Full Swedish month names to numbers, as used in tooltip title attributes
_SWEDISH_MONTH_NAMES = {
    "januari": 1,
    "februari": 2,
    "mars": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}


def fetch_notifications(session):
    """Fetch the user's notifications from /Common/Notification/GetNotifications.

    Returns a list of notification dicts.
    """
    resp = session.get(
        f"{BASE_URL}/Common/Notification/GetNotifications",
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_notifications(resp.text)


def _parse_date_from_tooltip(title_attr):
    """Parse date from tooltip title attribute like 'den 25 mars 2026 21:43'.

    Returns ISO datetime string 'YYYY-MM-DDTHH:MM:SS' or None.
    """
    if not title_attr:
        return None
    m = re.search(
        r"den\s+(\d{1,2})\s+([a-zåäö]+)\s+(\d{4})\s+(\d{1,2}:\d{2})",
        title_attr.strip(),
        re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        time_str = m.group(4)
        month = _SWEDISH_MONTH_NAMES.get(month_name)
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}T{time_str}:00"
    return None


def _extract_team_slug_from_url(href):
    """Extract team slug from a full or relative laget.se URL.

    https://www.laget.se/TeamSlug/... -> 'TeamSlug'
    /TeamSlug/... -> 'TeamSlug'
    """
    # Strip base URL if present
    path = href
    if "laget.se/" in href:
        path = href.split("laget.se", 1)[1]
    path = path.lstrip("/")
    parts = path.split("/")
    if parts:
        return parts[0]
    return None


def _extract_relative_url(href):
    """Convert absolute laget.se URL to relative path.

    https://www.laget.se/TeamSlug/News/1234 -> /TeamSlug/News/1234
    /TeamSlug/... -> /TeamSlug/...
    """
    if "laget.se" in href:
        path = href.split("laget.se", 1)[1]
        if not path.startswith("/"):
            path = "/" + path
        return path
    return href


def _parse_notifications(html):
    """Parse notification HTML fragment from /Common/Notification/GetNotifications.

    Expects HTML with the structure:
      <ul class="popoverList">
        <li class="popoverList__itemOuter">
          <a ... href="https://www.laget.se/{team_slug}/...">
            <img ... alt="Author Name">
            <b>Author Name</b> action text
            <small class="popoverList__info">
              ...
              <span class="tooltip" title="den DD month YYYY HH:MM">...</span>
              ...
            </small>
          </a>
        </li>
      </ul>

    Returns a list of notification dicts.
    """
    notifications = []

    for li_match in re.finditer(
        r'<li\s+class="popoverList__itemOuter"[^>]*>([\s\S]*?)</li>',
        html,
    ):
        li_html = li_match.group(1)

        # Extract href from <a> tag
        href_match = re.search(r'<a\b[^>]+href="([^"]+)"', li_html)
        if not href_match:
            continue
        href = href_match.group(1).strip()

        # Extract author from <b> tag
        author_match = re.search(r"<b>([^<]+)</b>", li_html)
        author = unescape(author_match.group(1).strip()) if author_match else None

        # Extract action title text (between </b> and <small)
        title_match = re.search(r"</b>([\s\S]*?)<small", li_html)
        title = None
        if title_match:
            raw_title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            title = unescape(raw_title) if raw_title else None

        # Extract date from tooltip title attribute
        tooltip_match = re.search(
            r'<span\s+class="tooltip"\s+title="([^"]+)"',
            li_html,
        )
        date_str = _parse_date_from_tooltip(
            tooltip_match.group(1) if tooltip_match else None
        )

        relative_url = _extract_relative_url(href)
        team_slug = _extract_team_slug_from_url(href)

        # Infer type from URL; refine news -> news_comment if action text says "kommenterade"
        notification_type = _infer_notification_type(relative_url)
        if notification_type == "news" and title and "kommentera" in title.lower():
            notification_type = "news_comment"

        notifications.append(
            {
                "date": date_str,
                "type": notification_type,
                "author": author,
                "title": title,
                "team": None,  # resolved by caller using teams list
                "team_slug": team_slug,
                "url": relative_url,
            }
        )

    return notifications


def resolve_team_names(notifications, teams):
    """Fill in the 'team' field for each notification using a teams list.

    Args:
        notifications: list of notification dicts (team field is None)
        teams: list of team dicts with 'team_slug' and 'name' keys

    Returns the same list with 'team' fields populated where possible.
    """
    slug_to_name = {t["team_slug"]: t["name"] for t in teams}
    for n in notifications:
        n["team"] = slug_to_name.get(n["team_slug"])
    return notifications
