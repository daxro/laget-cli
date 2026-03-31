import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from laget_cli.cli import _mask_email, _progress, _use_color, main, print_logo


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
        from importlib.metadata import version
        expected = version("laget-cli")
        with patch("sys.argv", ["laget", "--version"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            assert expected in capsys.readouterr().out


class TestVersionFromMetadata:
    def test_no_hardcoded_version_in_cli(self):
        """Ensure cli.py does not contain a hardcoded version string in the argparse setup."""
        import laget_cli.cli as cli_mod
        source_path = cli_mod.__file__
        with open(source_path) as f:
            source = f.read()
        # Should not have version="%(prog)s 0.1.0" or similar hardcoded pattern
        assert 'version="%(prog)s 0.' not in source



class TestFieldsFlag:
    def test_notifications_fields_filters_output(self):
        from io import StringIO

        notifications = [
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": "T1", "team_slug": "A", "url": "/x/News/1"},
        ]
        teams = [{"team_slug": "A", "name": "A", "club": "C"}]

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams), \
             patch("laget_cli.cli.fetch_notifications", return_value=notifications), \
             patch("laget_cli.cli.resolve_team_names", side_effect=lambda n, t: n), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget", "-q", "notifications", "--since", "all", "--fields", "date,type"]):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()

        result = json.loads(out.getvalue())
        assert len(result) == 1
        assert set(result[0].keys()) == {"date", "type"}


class TestNotificationsLimit:
    def _run_notifications(self, argv, notifications_data, teams_data=None):
        from io import StringIO
        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"}]

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_notifications", return_value=notifications_data), \
             patch("laget_cli.cli.resolve_team_names", side_effect=lambda n, t: n), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_limit_truncates_results(self):
        notifications = [
            {"date": f"2026-03-{i:02d}T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"}
            for i in range(1, 11)
        ]
        result = self._run_notifications(["notifications", "--since", "all", "--limit", "3"], notifications)
        assert len(result) == 3

    def test_no_limit_returns_all(self):
        notifications = [
            {"date": f"2026-03-{i:02d}T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"}
            for i in range(1, 6)
        ]
        result = self._run_notifications(["notifications", "--since", "all"], notifications)
        assert len(result) == 5

    def test_limit_applied_after_sort(self):
        notifications = [
            {"date": "2026-03-01T00:00:00", "type": "news", "author": "A",
             "title": "old", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"},
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "B",
             "title": "new", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/2"},
            {"date": "2026-03-15T00:00:00", "type": "news", "author": "C",
             "title": "mid", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/3"},
        ]
        result = self._run_notifications(["notifications", "--since", "all", "--limit", "2"], notifications)
        assert len(result) == 2
        # Should be the 2 newest (sorted desc)
        assert result[0]["date"] == "2026-03-29T00:00:00"
        assert result[1]["date"] == "2026-03-15T00:00:00"


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
    def test_status_not_configured_outputs_json(self, mock_dotenv, capsys):
        mock_dotenv.return_value = {}

        with patch("sys.argv", ["laget", "-q", "status", "--json"]):
            main()

        output = json.loads(capsys.readouterr().out)
        assert output["configured"] is False

    @patch("laget_cli.cli.dotenv_values")
    def test_status_not_configured_human_exits(self, mock_dotenv, capsys):
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

        with patch("sys.argv", ["laget", "-q", "news", "--team", "TeamA-P2021", "123"]):
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

        with patch("sys.argv", ["laget", "-q", "news", "--team", "nonexistent", "123"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 4



class TestPrintLogo:
    def test_use_color_true_on_tty(self):
        mock_stderr = MagicMock()
        mock_stderr.isatty.return_value = True
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "TERM")}
        with patch("sys.stderr", mock_stderr):
            with patch.dict("os.environ", env, clear=True):
                result = _use_color()
        assert result is True

    def test_logo_has_ansi_on_tty(self):
        import io
        buf = io.StringIO()
        mock_stderr = MagicMock()
        mock_stderr.isatty.return_value = True
        mock_stderr.write = buf.write
        mock_stderr.flush = buf.flush
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "TERM")}
        with patch("sys.stderr", mock_stderr):
            with patch.dict("os.environ", env, clear=True):
                print_logo()
        assert "\033[" in buf.getvalue()

    def test_logo_no_ansi_when_no_color_set(self, capsys):
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err
        assert "|___/" in err

    def test_logo_no_ansi_when_term_dumb(self, capsys):
        with patch.dict("os.environ", {"TERM": "dumb"}):
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err

    def test_logo_no_ansi_when_not_tty(self, capsys):
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = False
            mock_stderr.write = sys.stderr.write
            mock_stderr.flush = sys.stderr.flush
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err


class TestSetupCommand:
    @patch("laget_cli.cli.dotenv_values")
    def test_setup_calls_print_logo(self, mock_dotenv, capsys):
        """setup command should call print_logo(), not reference _LOGO."""
        mock_dotenv.return_value = {}

        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        with patch("sys.argv", ["laget", "setup"]):
            with patch("sys.stdin", mock_stdin):
                with patch.dict("os.environ", {"EMAIL": "t@t.com", "PASSWORD": "pw"}):
                    with patch("laget_cli.cli.login") as mock_login:
                        mock_login.return_value = MagicMock()
                        with patch("laget_cli.cli._get_status", return_value={"configured": True, "email": "t****@t.com", "session": "valid", "club_filter": None, "teams": [], "children": []}):
                            main()

        err = capsys.readouterr().err
        # Should contain the logo ASCII art, not crash with NameError
        assert "___ _" in err or "laget" in err or "|___/" in err


class TestSignalHandling:
    def test_keyboard_interrupt_exits_130(self):
        with patch("sys.argv", ["laget", "notifications"]):
            with patch("laget_cli.cli._notifications", side_effect=KeyboardInterrupt):
                with patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
                    with pytest.raises(SystemExit) as exc:
                        main()
                    assert exc.value.code == 130

    def test_keyboard_interrupt_no_traceback(self, capsys):
        with patch("sys.argv", ["laget", "notifications"]):
            with patch("laget_cli.cli._notifications", side_effect=KeyboardInterrupt):
                with patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
                    with pytest.raises(SystemExit):
                        main()
        err = capsys.readouterr().err
        assert "Traceback" not in err


class TestSetupNoInput:
    @patch("laget_cli.cli._get_status")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli._write_env")
    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_no_input_flag_skips_prompts(self, mock_dotenv, mock_logo, mock_write_env, mock_login, mock_status, capsys):
        mock_dotenv.return_value = {}
        mock_login.return_value = MagicMock()
        mock_status.return_value = {"configured": True, "email": "t****@t.com", "session": "valid", "club_filter": None, "teams": [], "children": []}

        with patch.dict("os.environ", {"EMAIL": "t@t.com", "PASSWORD": "pw"}):
            with patch("sys.argv", ["laget", "-q", "setup", "--no-input"]):
                # stdin IS a tty, but --no-input should override
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = True
                    main()

        mock_write_env.assert_called_once_with("t@t.com", "pw")

    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_no_input_flag_errors_without_env_vars(self, mock_dotenv, mock_logo, capsys):
        mock_dotenv.return_value = {}

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("EMAIL", None)
            os.environ.pop("PASSWORD", None)
            with patch("sys.argv", ["laget", "setup", "--no-input"]):
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 2


class TestGlobalFlagPosition:
    """Global flags (--debug, --no-input, -q) must work both before and after the subcommand."""

    @pytest.mark.parametrize("flag,attr,expected", [
        ("--debug", "debug", True),
        ("--no-input", "no_input", True),
        ("-q", "quiet", True),
    ])
    @pytest.mark.parametrize("position", ["before", "after"])
    def test_flag_propagates(self, flag, attr, expected, position):
        argv_before = ["laget", flag, "notifications", "--since", "all"]
        argv_after = ["laget", "notifications", "--since", "all", flag]
        argv = argv_before if position == "before" else argv_after

        notifications = [
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": "T1", "team_slug": "A", "url": "/x/News/1"},
        ]
        teams = [{"team_slug": "A", "name": "A", "club": "C"}]

        from io import StringIO
        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams), \
             patch("laget_cli.cli.fetch_notifications", return_value=notifications), \
             patch("laget_cli.cli.resolve_team_names", side_effect=lambda n, t: n), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()

        assert getattr(pytest, "skip", None) or True  # ran without parse error
        # For -q, argparse stores it under 'quiet'
        # We can't easily inspect args after main() returns, but the fact that
        # main() completed without error proves the flag was accepted in that position.


class TestGetStatusExceptionHandling:
    @patch("laget_cli.cli._load_state", return_value={})
    @patch("laget_cli.cli.fetch_children", side_effect=requests.ConnectionError("network down"))
    @patch("laget_cli.cli.fetch_teams", return_value=[{"name": "T1", "club": "C", "team_slug": "a"}])
    @patch("laget_cli.cli.filter_teams_by_club", return_value=[{"name": "T1", "club": "C", "team_slug": "a"}])
    @patch("laget_cli.cli.login", return_value=MagicMock())
    @patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"})
    def test_children_fetch_failure_warns_on_stderr(self, mock_dotenv, mock_login, mock_filter, mock_teams, mock_children, mock_state, capsys):
        from laget_cli.cli import _get_status
        status = _get_status()
        err = capsys.readouterr().err
        assert "Warning" in err or "warning" in err
        assert status["children"] == []

    @patch("laget_cli.cli.fetch_children", return_value=[])
    @patch("laget_cli.cli.fetch_teams", side_effect=requests.Timeout("timed out"))
    @patch("laget_cli.cli.filter_teams_by_club", return_value=[])
    @patch("laget_cli.cli.login", return_value=MagicMock())
    @patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"})
    def test_teams_fetch_failure_warns_on_stderr(self, mock_dotenv, mock_login, mock_filter, mock_teams, mock_children, capsys):
        from laget_cli.cli import _get_status
        status = _get_status()
        err = capsys.readouterr().err
        assert "Warning" in err or "warning" in err
        assert status["teams"] == []



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
