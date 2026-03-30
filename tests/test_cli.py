import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from laget_cli.cli import _mask_email, _progress, main


class TestMaskEmail:
    def test_masks_normal_email(self):
        assert _mask_email("user@example.com") == "use****@example.com"

    def test_masks_short_local(self):
        assert _mask_email("ab@test.com") == "a****@test.com"

    def test_returns_none_for_none(self):
        assert _mask_email(None) is None

    def test_returns_empty_for_empty(self):
        assert _mask_email("") == ""

    def test_no_at_sign_returns_as_is(self):
        assert _mask_email("noemail") == "noemail"


class TestProgress:
    def test_prints_to_stderr(self, capsys):
        _progress("hello")
        assert capsys.readouterr().err == "hello\n"

    def test_quiet_suppresses(self, capsys):
        _progress("hello", quiet=True)
        assert capsys.readouterr().err == ""


class TestMainNoCommand:
    def test_no_command_shows_help_and_exits(self, capsys):
        with patch("sys.argv", ["laget"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1


class TestMainVersion:
    def test_version(self, capsys):
        with patch("sys.argv", ["laget", "--version"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            assert "0.1.0" in capsys.readouterr().out



class TestStatusCommand:
    @patch("laget_cli.cli.fetch_children")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_status_json_outputs_json(self, mock_dotenv, mock_login, mock_fetch_teams, mock_fetch_children, capsys):
        mock_dotenv.return_value = {"EMAIL": "user@example.com", "PASSWORD": "pass", "CLUB": "Test FK"}
        mock_login.return_value = MagicMock()
        mock_fetch_teams.return_value = [{"name": "T1", "club": "Test FK", "team_slug": "a"}]
        mock_fetch_children.return_value = [{"name": "Alice", "id": "123"}]

        with patch("sys.argv", ["laget", "-q", "status", "--json"]):
            main()

        output = json.loads(capsys.readouterr().out)
        assert output["configured"] is True
        assert output["email"] == "use****@example.com"
        assert output["session"] == "valid"
        assert len(output["teams"]) == 1
        assert len(output["children"]) == 1

    @patch("laget_cli.cli.fetch_children")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_status_human_readable(self, mock_dotenv, mock_login, mock_fetch_teams, mock_fetch_children, capsys):
        mock_dotenv.return_value = {"EMAIL": "user@example.com", "PASSWORD": "pass", "CLUB": "Test FK"}
        mock_login.return_value = MagicMock()
        mock_fetch_teams.return_value = [{"name": "T1", "club": "Test FK", "team_slug": "a"}]
        mock_fetch_children.return_value = [{"name": "Alice", "id": "123"}]

        with patch("sys.argv", ["laget", "-q", "status"]):
            main()

        err = capsys.readouterr().err
        assert "Email: use****@example.com" in err
        assert "Session: valid" in err
        assert "T1 (Test FK)" in err
        assert "Alice" in err

    @patch("laget_cli.cli.dotenv_values")
    def test_status_not_configured(self, mock_dotenv, capsys):
        mock_dotenv.return_value = {}

        with patch("sys.argv", ["laget", "-q", "status"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 3


class TestNewsCommand:
    @patch("laget_cli.cli.fetch_article")
    @patch("laget_cli.cli.filter_teams_by_club")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_news_outputs_article_json(self, mock_dotenv, mock_login, mock_fetch_teams, mock_filter, mock_fetch_article, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.return_value = MagicMock()
        mock_filter.return_value = [{"team_slug": "TeamA-P2021", "name": "P2021", "club": "Team A"}]
        mock_fetch_teams.return_value = mock_filter.return_value
        mock_fetch_article.return_value = {
            "id": "123",
            "title": "Test Article",
            "author": "Author",
            "date": "2026-03-28T00:00:00",
            "body": "Article body",
            "view_count": 10,
            "comments": [],
            "team": None,
            "team_slug": None,
        }

        with patch("sys.argv", ["laget", "-q", "news", "TeamA-P2021", "123"]):
            main()

        output = json.loads(capsys.readouterr().out)
        assert output["id"] == "123"
        assert output["team"] == "P2021"
        assert output["team_slug"] == "TeamA-P2021"

    @patch("laget_cli.cli.filter_teams_by_club")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_news_unknown_team_emits_error(self, mock_dotenv, mock_login, mock_fetch_teams, mock_filter, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.return_value = MagicMock()
        mock_filter.return_value = [{"team_slug": "TeamA-P2021", "name": "P2021", "club": "A"}]
        mock_fetch_teams.return_value = mock_filter.return_value

        with patch("sys.argv", ["laget", "-q", "news", "nonexistent", "123"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 4


class TestErrorHandling:
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_auth_error_emits_json(self, mock_dotenv, mock_login, capsys):
        from laget_cli.errors import AuthError
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = AuthError("bad credentials")

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 3

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "auth_failed"

    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_timeout_emits_json(self, mock_dotenv, mock_login, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = requests.Timeout()

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 5

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "request_timeout"

    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_connection_error_emits_json(self, mock_dotenv, mock_login, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = requests.ConnectionError()

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 5

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "connection_failed"
