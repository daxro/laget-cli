from unittest.mock import MagicMock

import pytest

from laget_cli.api.teams import (
    _slug_from_page_url,
    fetch_children,
    fetch_teams,
    filter_teams_by_club,
    sync_child_team_mapping,
)
from laget_cli.errors import ParseError
from laget_cli.session import HTTP_TIMEOUT


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_fetch_teams_joins_mobile_team_and_page_resources():
    session = MagicMock(user_id="42")
    session.get.side_effect = [
        _response(
            {
                "teams": [
                    {
                        "id": 10,
                        "displayName": "P2019",
                        "parentSite": {"displayName": "Example FC"},
                    },
                    {"id": 11, "displayName": "Standalone"},
                ]
            }
        ),
        _response(
            {
                "pages": [
                    {"id": 10, "url": "https://www.laget.se/ExampleFC-P2019"},
                    {"id": 11, "url": "/Standalone/"},
                ]
            }
        ),
    ]

    teams = fetch_teams(session)

    assert teams == [
        {
            "name": "P2019",
            "club": "Example FC",
            "team_slug": "ExampleFC-P2019",
            "_site_id": "10",
            "_page_url": "https://www.laget.se/ExampleFC-P2019",
        },
        {
            "name": "Standalone",
            "club": "Standalone",
            "team_slug": "Standalone",
            "_site_id": "11",
            "_page_url": "/Standalone/",
        },
    ]
    assert "/v4/users/42/teams" in session.get.call_args_list[0].args[0]
    assert "/v4/users/42/pages" in session.get.call_args_list[1].args[0]
    for call in session.get.call_args_list:
        assert call.kwargs["timeout"] == HTTP_TIMEOUT


def test_fetch_teams_keeps_unjoined_team_with_no_slug():
    session = MagicMock(user_id=7)
    session.get.side_effect = [
        _response({"teams": [{"id": 1, "displayName": "Team"}]}),
        _response({"pages": []}),
    ]
    assert fetch_teams(session)[0]["team_slug"] is None


def test_fetch_teams_rejects_wrong_envelope():
    session = MagicMock(user_id=7)
    session.get.side_effect = [_response([]), _response({"pages": []})]
    with pytest.raises(ParseError):
        fetch_teams(session)


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://www.laget.se/Club-Team?x=1", "Club-Team"),
        ("/Club-Team/News", "Club-Team"),
        (None, None),
    ],
)
def test_slug_from_page_url(url, slug):
    assert _slug_from_page_url(url) == slug


def test_children_and_mapping_do_not_make_html_requests():
    session = MagicMock()
    assert fetch_children(session) == []
    assert sync_child_team_mapping(session, [{"team_slug": "a"}], [{"id": "1"}]) == {}
    session.get.assert_not_called()


def test_filter_teams_by_club_is_case_insensitive_and_null_safe():
    teams = [
        {"club": "Example FC"},
        {"club": "Other"},
        {"club": None},
    ]
    assert filter_teams_by_club(teams, "EXAMPLE") == [teams[0]]
    assert filter_teams_by_club(teams, None) is teams
