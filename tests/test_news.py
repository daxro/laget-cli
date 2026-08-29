from unittest.mock import MagicMock

import pytest

from laget_cli.api.news import _normalize_article, fetch_article
from laget_cli.errors import ParseError
from laget_cli.session import HTTP_TIMEOUT


ARTICLE = {
    "id": 9876,
    "title": "Cupen i Alvik",
    "content": "<p>Första raden.<br>Andra raden.</p>",
    "date": "2026-08-20T17:50:00.456+02:00",
    "type": "news",
    "url": "https://www.laget.se/ExampleFC-P2019/News/9876",
    "numComments": 1,
    "publisher": {"id": 9, "name": "Johan Andersson"},
    "showPublisher": True,
    "comments": [
        {
            "id": 1,
            "content": "<b>Bra</b>, vi kommer!",
            "date": "2026-08-21T09:00:00Z",
            "user": {"name": "Maria Nilsson"},
        }
    ],
    "site": {"id": 77, "name": "P2019"},
    "canComment": True,
    "image": {"large": "https://example.test/image.jpg"},
}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_normalize_live_article_contract():
    assert _normalize_article(ARTICLE, "ExampleFC-P2019") == {
        "id": "9876",
        "team": None,
        "team_slug": "ExampleFC-P2019",
        "title": "Cupen i Alvik",
        "author": "Johan Andersson",
        "date": "2026-08-20T17:50:00+02:00",
        "body": "Första raden.\nAndra raden.",
        "view_count": None,
        "comments": [
            {
                "author": "Maria Nilsson",
                "date": "2026-08-21T09:00:00Z",
                "text": "Bra, vi kommer!",
            }
        ],
    }


def test_hidden_publisher_has_no_author():
    assert _normalize_article({**ARTICLE, "showPublisher": False})["author"] is None


def test_fetch_article_uses_site_id_and_preserves_team_slug():
    session = MagicMock()
    session.get.return_value = _response({"data": ARTICLE})
    team = {"_site_id": "77", "team_slug": "ExampleFC-P2019"}

    result = fetch_article(session, team, "9876")

    assert result["team_slug"] == "ExampleFC-P2019"
    call = session.get.call_args
    assert "/v2/sites/77/news/9876" in call.args[0]
    assert call.kwargs["timeout"] == HTTP_TIMEOUT


def test_fetch_article_accepts_bare_site_id():
    session = MagicMock()
    session.get.return_value = _response({"data": ARTICLE})
    assert fetch_article(session, 77, 9876)["id"] == "9876"


def test_fetch_article_requires_site_id():
    with pytest.raises(ParseError):
        fetch_article(MagicMock(), {"team_slug": "slug"}, "1")


def test_fetch_article_rejects_wrong_envelope():
    session = MagicMock()
    session.get.return_value = _response({"article": ARTICLE})
    with pytest.raises(ParseError):
        fetch_article(session, 77, 9876)
