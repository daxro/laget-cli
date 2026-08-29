"""laget.se news article resource from the mobile JSON API."""

from laget_cli.api.normalize import _normalize_json_datetime, _strip_html
from laget_cli.errors import ParseError
from laget_cli.session import API_URL, HTTP_TIMEOUT


def _string_id(value):
    return None if value is None else str(value)


def _person_name(value):
    if not isinstance(value, dict):
        return None
    return value.get("name") or value.get("displayName") or value.get("fullName")


def _normalize_comment(comment):
    if not isinstance(comment, dict):
        return None
    author = comment.get("publisher") or comment.get("user") or comment.get("author")
    return {
        "author": _person_name(author),
        "date": _normalize_json_datetime(comment.get("date") or comment.get("createdDate")),
        "text": _strip_html(comment.get("content") or comment.get("text")),
    }


def _normalize_article(article, team_slug=None):
    if not isinstance(article, dict):
        raise ParseError("News detail response contains no article")
    publisher = article.get("publisher")
    comments = article.get("comments")
    if not isinstance(comments, list):
        comments = []
    return {
        "id": _string_id(article.get("id")),
        "team": None,
        "team_slug": team_slug,
        "title": article.get("title"),
        "author": (
            _person_name(publisher)
            if article.get("showPublisher") is not False
            else None
        ),
        "date": _normalize_json_datetime(article.get("date")),
        "body": _strip_html(article.get("content")),
        "view_count": None,
        "comments": [
            normalized
            for comment in comments
            if (normalized := _normalize_comment(comment)) is not None
        ],
    }


def fetch_article(session, team, article_id):
    """Fetch an article using a team mapping or a mobile API site ID.

    A team mapping returned by :func:`laget_cli.api.teams.fetch_teams` is the
    preferred argument because it preserves the public slug in the result.
    """
    if isinstance(team, dict):
        site_id = team.get("_site_id") or team.get("site_id")
        team_slug = team.get("team_slug")
    else:
        site_id = team
        team_slug = None
    if site_id is None:
        raise ParseError("A site ID is required to fetch a news article")

    response = session.get(
        f"{API_URL}/v2/sites/{site_id}/news/{article_id}",
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ParseError("Invalid JSON returned for news detail") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise ParseError("News detail response is missing data")
    return _normalize_article(payload["data"], team_slug=team_slug)
