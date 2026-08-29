import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from laget_cli.cli import _get_status, _notifications, _prepare_teams, _rsvp


def test_prepare_teams_attaches_private_site_mapping():
    session = SimpleNamespace()
    teams = [
        {
            "name": "P2021",
            "club": "Example FC",
            "team_slug": "ExampleFC-P2021",
            "_site_id": "42",
            "_page_url": "https://www.laget.se/ExampleFC-P2021",
        }
    ]
    with patch("laget_cli.cli.fetch_teams", return_value=teams):
        assert _prepare_teams(session, {}) == teams
    assert session.team_site_ids == {"ExampleFC-P2021": "42"}


def test_status_never_exposes_private_api_identifiers():
    session = SimpleNamespace()
    teams = [
        {
            "name": "P2021",
            "club": "Example FC",
            "team_slug": "ExampleFC-P2021",
            "_site_id": "42",
            "_page_url": "https://www.laget.se/ExampleFC-P2021",
        }
    ]
    config = {"LAGET_EMAIL": "person@example.com", "LAGET_PASSWORD": "secret"}
    status = _get_status(
        session=session,
        config=config,
        teams=teams,
        include_children=False,
    )
    assert status["teams"] == [
        {"name": "P2021", "club": "Example FC", "team_slug": "ExampleFC-P2021"}
    ]


def test_feed_outputs_native_mobile_api_shape(capsys):
    session = SimpleNamespace()
    args = SimpleNamespace(
        command="feed",
        fields=None,
        selected_fields=None,
        since="all",
        until=None,
        team=None,
        limit=5,
        quiet=True,
    )
    team = {
        "name": "P2021",
        "club": "Example FC",
        "team_slug": "ExampleFC-P2021",
        "_site_id": "42",
    }
    item = {
        "id": "7",
        "type": "news",
        "title": "Update",
        "body": "Body",
        "date": "2026-08-01T12:00:00",
        "author": "Coach",
        "comment_count": 2,
        "site_id": "42",
        "site_name": "P2021",
        "team": None,
        "team_slug": "ExampleFC-P2021",
        "url": "https://www.laget.se/ExampleFC-P2021/News/7",
    }
    with patch("laget_cli.cli._load_config", return_value={}), \
         patch("laget_cli.cli._get_session", return_value=session), \
         patch("laget_cli.cli._prepare_teams", return_value=[team]), \
         patch("laget_cli.cli.fetch_notifications", return_value=[item]) as fetch:
        _notifications(args)
    assert "limit" not in fetch.call_args.kwargs
    assert json.loads(capsys.readouterr().out) == [{**item, "team": "P2021"}]


def test_rsvp_forwards_explicit_member_id(capsys):
    args = SimpleNamespace(
        command="rsvp",
        fields=None,
        selected_fields=None,
        team="ExampleFC-P2021",
        id="99",
        response="yes",
        comment="Coming",
        member="123",
        quiet=True,
    )
    session = SimpleNamespace()
    team = {
        "name": "P2021",
        "club": "Example FC",
        "team_slug": "ExampleFC-P2021",
        "_site_id": "42",
    }
    before = {
        "id": "99",
        "team": None,
        "team_slug": "ExampleFC-P2021",
        "rsvp": {"my_response": "unanswered", "url": None},
        "responses": [{"id": "123", "name": "Child", "my_response": "unanswered"}],
    }
    after = {
        **before,
        "responses": [{"id": "123", "name": "Child", "my_response": "yes"}],
    }
    with patch("laget_cli.cli._get_session", return_value=session), \
         patch("laget_cli.cli._load_config", return_value={}), \
         patch("laget_cli.cli._prepare_teams", return_value=[team]), \
         patch("laget_cli.cli.fetch_event_detail", side_effect=[before, after]), \
         patch("laget_cli.cli.submit_rsvp") as submit:
        submit.return_value.laget_member_id = "123"
        _rsvp(args)
    assert submit.call_args.kwargs["member_id"] == "123"
    assert json.loads(capsys.readouterr().out)["responses"][0]["my_response"] == "yes"


def test_rsvp_verifies_authenticated_users_global_response(capsys):
    args = SimpleNamespace(
        command="rsvp",
        fields=None,
        selected_fields=None,
        team="ExampleFC-Seniors",
        id="100",
        response="yes",
        comment=None,
        member=None,
        quiet=True,
    )
    session = SimpleNamespace(user_id="77")
    team = {
        "name": "Seniors",
        "club": "Example FC",
        "team_slug": "ExampleFC-Seniors",
        "_site_id": "42",
    }
    before = {
        "id": "100",
        "team": None,
        "team_slug": team["team_slug"],
        "rsvp": {"my_response": "unanswered", "url": "https://www.laget.se/x/Rsvp/100/77"},
        "responses": [],
    }
    after = {
        **before,
        "rsvp": {"my_response": "yes", "url": "https://www.laget.se/x/Rsvp/100/77"},
    }
    with patch("laget_cli.cli._get_session", return_value=session), \
         patch("laget_cli.cli._load_config", return_value={}), \
         patch("laget_cli.cli._prepare_teams", return_value=[team]), \
         patch("laget_cli.cli.fetch_event_detail", side_effect=[before, after]), \
         patch("laget_cli.cli.submit_rsvp") as submit:
        submit.return_value.laget_member_id = "77"
        _rsvp(args)
    assert json.loads(capsys.readouterr().out)["rsvp"]["my_response"] == "yes"
