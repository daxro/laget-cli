from unittest.mock import MagicMock, patch

import pytest

from laget_cli.api.notifications import (
    _normalize_feed_item,
    fetch_feed,
    fetch_notifications,
    resolve_team_names,
)
from laget_cli.errors import ParseError
from laget_cli.session import HTTP_TIMEOUT


FEED_ITEM = {
    "id": 123,
    "type": "news",
    "title": "Cupnytt",
    "content": "<p>Vi är <b>anmälda</b>.</p>",
    "date": "2026-08-29T12:13:14.123Z",
    "numComments": 2,
    "url": "https://www.laget.se/ExampleFC-P2019/News/123",
    "publisher": {"name": "Anna Admin"},
    "showPublisher": True,
    "site": {
        "id": 77,
        "url": "https://www.laget.se/ExampleFC-P2019",
        "displayNames": {"long": "Example FC P2019"},
    },
}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_normalize_native_feed_item():
    assert _normalize_feed_item(FEED_ITEM) == {
        "id": "123",
        "type": "news",
        "title": "Cupnytt",
        "body": "Vi är anmälda.",
        "date": "2026-08-29T12:13:14Z",
        "author": "Anna Admin",
        "comment_count": 2,
        "site_id": "77",
        "site_name": "Example FC P2019",
        "team": None,
        "team_slug": "ExampleFC-P2019",
        "url": "https://www.laget.se/ExampleFC-P2019/News/123",
    }


def test_hidden_publisher_is_not_exposed():
    item = {**FEED_ITEM, "showPublisher": False}
    assert _normalize_feed_item(item)["author"] is None


def test_fetch_feed_uses_authenticated_mobile_endpoint_and_params():
    session = MagicMock(user_id="42")
    session.get.return_value = _response({"news": [FEED_ITEM]})

    result = fetch_feed(session)

    assert result[0]["id"] == "123"
    call = session.get.call_args
    assert "/v5/users/42/news" in call.args[0]
    assert call.kwargs["params"] == {
        "pageIndex": 0,
        "pageSize": 50,
        "excerptLength": 100,
    }
    assert call.kwargs["timeout"] == HTTP_TIMEOUT


def test_fetch_notifications_is_compatibility_wrapper():
    session = MagicMock()
    with patch("laget_cli.api.notifications.fetch_feed", return_value=[{"id": "1"}]) as feed:
        assert fetch_notifications(session) == [{"id": "1"}]
    feed.assert_called_once_with(session)


def test_fetch_feed_paginates_deduplicates_and_honors_limit():
    session = MagicMock(user_id="42")
    first = {**FEED_ITEM, "id": 1}
    second = {**FEED_ITEM, "id": 2}
    session.get.side_effect = [
        _response({"news": [first, second]}),
        _response({"news": [second, {**FEED_ITEM, "id": 3}]}),
    ]

    result = fetch_feed(session, limit=3, page_size=2)

    assert [item["id"] for item in result] == ["1", "2", "3"]
    assert session.get.call_count == 2
    assert session.get.call_args_list[1].kwargs["params"]["pageIndex"] == 1


def test_fetch_feed_stops_after_descending_page_passes_since():
    session = MagicMock(user_id="42")
    session.get.return_value = _response(
        {
            "news": [
                {**FEED_ITEM, "id": 1, "date": "2026-08-29T12:00:00Z"},
                {**FEED_ITEM, "id": 2, "date": "2026-08-20T12:00:00Z"},
            ]
        }
    )

    fetch_feed(session, page_size=2, since="2026-08-25")

    session.get.assert_called_once()


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": -1}, {"max_pages": 0}, {"page_size": 0}, {"page_size": 51}],
)
def test_fetch_feed_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError):
        fetch_feed(MagicMock(), **kwargs)


def test_fetch_feed_rejects_missing_news_envelope():
    session = MagicMock(user_id="42")
    session.get.return_value = _response({"items": []})
    with pytest.raises(ParseError):
        fetch_feed(session)


def test_resolve_team_names_prefers_site_id_and_falls_back_to_slug():
    items = [
        {"site_id": "77", "team": None, "team_slug": None},
        {"site_id": "999", "team": None, "team_slug": "Other-Team"},
    ]
    teams = [
        {"_site_id": "77", "name": "P2019", "team_slug": "ExampleFC-P2019"},
        {"_site_id": "88", "name": "Other", "team_slug": "Other-Team"},
    ]
    assert resolve_team_names(items, teams) == [
        {"site_id": "77", "team": "P2019", "team_slug": "ExampleFC-P2019"},
        {"site_id": "999", "team": "Other", "team_slug": "Other-Team"},
    ]
