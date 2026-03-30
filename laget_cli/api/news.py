"""laget.se news article API."""

import re
from html import unescape

from laget_cli.api.normalize import _normalize_datetime, _strip_html
from laget_cli.session import AJAX_HEADERS, BASE_URL, HTTP_TIMEOUT


def fetch_article(session, team_slug, article_id):
    """Fetch and parse a news article.

    GET /{team_slug}/News/{article_id}

    Returns a dict with article fields and comments list.
    """
    resp = session.get(
        f"{BASE_URL}/{team_slug}/News/{article_id}",
        headers=AJAX_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_article(resp.text, team_slug, article_id)


def _parse_article(html, team_slug, article_id):
    """Parse a full article page into a structured dict."""
    title = _parse_title(html)
    author = _parse_author(html)
    date = _parse_date(html)
    view_count = _parse_view_count(html)
    body = _parse_body(html)
    comments = _parse_comments(html)

    return {
        "id": str(article_id),
        "team": None,
        "team_slug": team_slug,
        "title": title,
        "author": author,
        "date": date,
        "body": body,
        "view_count": view_count,
        "comments": comments,
    }


def _parse_title(html):
    m = re.search(r'<h3 class="headline">(.*?)</h3>', html)
    if m:
        return unescape(m.group(1).strip())
    return None


def _parse_author(html):
    m = re.search(r'<span class="author__name">(.*?)</span>', html)
    if m:
        return unescape(m.group(1).strip())
    return None


def _parse_date(html):
    # Try tooltip title first (e.g. title="den 9 februari 2026 17:50")
    m = re.search(
        r'<span[^>]*title="den\s+(\d{1,2}\s+\w+\s+\d{4})[^"]*"[^>]*class="meta__item[^"]*"',
        html,
    )
    if m:
        return _normalize_datetime(m.group(1).strip())
    # Fallback: visible text after icon-time (DD month YYYY)
    m = re.search(
        r'<i class="icon-time[^"]*"[^>]*></i>\s*([\d]+ \w+ \d{4})',
        html,
    )
    if m:
        return _normalize_datetime(m.group(1).strip())
    return None


def _parse_view_count(html):
    m = re.search(
        r'<i class="icon-eye-open[^"]*"[^>]*></i>\s*(\d+)',
        html,
    )
    if m:
        return int(m.group(1))
    return None


def _parse_body(html):
    # Try to extract content between anchor-comments div and author/socialShare block
    m = re.search(
        r'<div id="anchor-comments"></div>\s*([\s\S]*?)\s*'
        r'(?:<div class="author">|<div class="socialShare__outer--borderTop">)',
        html,
    )
    if m and _strip_html(m.group(1)):
        return _strip_html(m.group(1))
    # Fallback: single link-color--underline paragraph
    m = re.search(r'<p class="link-color--underline">([\s\S]*?)</p>', html)
    if m:
        return _strip_html(m.group(1))
    return None


def _parse_comments(html):
    """Parse the comment list from the page HTML.

    Returns a list of dicts: [{"author": ..., "date": ..., "text": ...}]
    Sorted ascending by position in HTML (which is natural chronological order).
    """
    # Find the comment list block first to avoid false positives
    list_match = re.search(
        r'<ul[^>]*id="news-comment-list"[^>]*>([\s\S]*?)</ul>',
        html,
    )
    if not list_match:
        return []

    list_html = list_match.group(1)
    comments = []

    for item in re.finditer(
        r'<li[^>]*class="[^"]*commentList__itemInner[^"]*"[^>]*>([\s\S]*?)</li>',
        list_html,
    ):
        item_html = item.group(1)

        author_m = re.search(r'<b class="commentList__name">([^<]+)</b>', item_html)
        author = unescape(author_m.group(1).strip()) if author_m else None

        date_m = re.search(r'<span class="commentList__time[^"]*">([^<]+)</span>', item_html)
        date = _normalize_datetime(date_m.group(1).strip()) if date_m else None

        text_m = re.search(r'<p class="commentList__text">([\s\S]*?)</p>', item_html)
        text = _strip_html(text_m.group(1)) if text_m else None

        comments.append({"author": author, "date": date, "text": text})

    return comments
