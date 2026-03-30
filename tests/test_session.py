import http.cookiejar
import json
import os
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import requests.cookies

from laget_cli.session import (
    follow_redirects,
    parse_hidden_fields,
    save_session,
    load_session,
    verify_authenticated,
    login,
)
from laget_cli.errors import AuthError


class TestFollowRedirects:
    def test_follows_302_chain(self):
        session = MagicMock()
        r1 = MagicMock(status_code=302, headers={"Location": "https://a.com/step2"}, url="https://a.com/step1")
        r2 = MagicMock(status_code=302, headers={"Location": "https://b.com/step3"}, url="https://a.com/step2")
        r3 = MagicMock(status_code=200, headers={}, url="https://b.com/step3")
        session.get.side_effect = [r2, r3]

        result = follow_redirects(session, r1)
        assert result.url == "https://b.com/step3"
        assert session.get.call_count == 2

    def test_stops_on_200(self):
        session = MagicMock()
        r1 = MagicMock(status_code=200, headers={}, url="https://a.com")
        result = follow_redirects(session, r1)
        assert result.url == "https://a.com"
        assert session.get.call_count == 0

    def test_resolves_relative_location(self):
        session = MagicMock()
        r1 = MagicMock(status_code=302, headers={"Location": "/next"}, url="https://a.com/page")
        r2 = MagicMock(status_code=200, headers={}, url="https://a.com/next")
        session.get.return_value = r2
        result = follow_redirects(session, r1)
        session.get.assert_called_with("https://a.com/next", allow_redirects=False, timeout=30)

    def test_stops_after_max_hops(self):
        session = MagicMock()
        redirect = MagicMock(status_code=302, headers={"Location": "https://a.com/loop"}, url="https://a.com/loop")
        session.get.return_value = redirect
        result = follow_redirects(session, redirect, max_hops=5)
        assert session.get.call_count == 5
        assert result.status_code == 302


class TestParseHiddenFields:
    def test_parses_multiple_fields(self):
        html = '''
        <form action="/Login" method="post">
            <input type="hidden" name="__RequestVerificationToken" value="abc123">
            <input type="hidden" name="Referer" value="aHR0cHM6Ly93d3cubGFnZXQuc2Uv">
        </form>
        '''
        fields = parse_hidden_fields(html)
        assert fields == {
            "__RequestVerificationToken": "abc123",
            "Referer": "aHR0cHM6Ly93d3cubGFnZXQuc2Uv",
        }

    def test_handles_html_entities(self):
        html = '<input type="hidden" name="token" value="a&amp;b">'
        fields = parse_hidden_fields(html)
        assert fields == {"token": "a&b"}

    def test_empty_value(self):
        html = '<input type="hidden" name="empty" value="">'
        fields = parse_hidden_fields(html)
        assert fields == {"empty": ""}

    def test_no_hidden_fields(self):
        html = '<input type="text" name="Email" value="foo">'
        fields = parse_hidden_fields(html)
        assert fields == {}


class TestVerifyAuthenticated:
    def test_authenticated_returns_normally(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"general": 0, "rsvp": 0, "unreadMessages": 0}
        session.get.return_value = resp

        verify_authenticated(session)
        assert session.get.call_count == 1

    def test_redirect_raises_auth_error(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 302
        resp.headers = {"Location": "https://www.laget.se/login"}
        session.get.return_value = resp

        try:
            verify_authenticated(session)
            assert False, "Should have raised AuthError"
        except AuthError as e:
            assert "expired" in str(e).lower() or "redirect" in str(e).lower()

    def test_non_200_raises_auth_error(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        session.get.return_value = resp

        try:
            verify_authenticated(session)
            assert False, "Should have raised AuthError"
        except AuthError:
            pass

    def test_non_json_raises_auth_error(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        session.get.return_value = resp

        try:
            verify_authenticated(session)
            assert False, "Should have raised AuthError"
        except AuthError:
            pass


class TestSessionPersistence:
    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "deep", "session.json")
            session = MagicMock()
            jar = __import__("requests").cookies.RequestsCookieJar()
            session.cookies = jar
            save_session(session, path)
            assert os.path.exists(path)

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            session = MagicMock()
            cookie = http.cookiejar.Cookie(
                version=0, name="laget_auth", value="abc123",
                port=None, port_specified=False,
                domain=".laget.se", domain_specified=True,
                domain_initial_dot=True,
                path="/", path_specified=True,
                secure=True, expires=None, discard=True,
                comment=None, comment_url=None,
                rest={"HttpOnly": "HttpOnly"},
            )
            jar = requests.cookies.RequestsCookieJar()
            jar.set_cookie(cookie)
            session.cookies = jar

            save_session(session, path)
            assert os.path.exists(path)

            # Verify file permissions
            stat = os.stat(path)
            assert stat.st_mode & 0o777 == 0o600

            new_sess = MagicMock()
            new_sess.cookies = requests.cookies.RequestsCookieJar()
            load_session(new_sess, path)
            assert any(c.name == "laget_auth" for c in new_sess.cookies)
        finally:
            os.unlink(path)

    def test_load_nonexistent_returns_false(self):
        session = MagicMock()
        result = load_session(session, "/nonexistent/path.json")
        assert result is False

    def test_load_corrupt_json_returns_false(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            session = MagicMock()
            result = load_session(session, path)
            assert result is False
        finally:
            os.unlink(path)


class TestLogin:
    def _mock_login_flow(self):
        """Build a mock session that simulates the laget.se login flow."""
        session = MagicMock()
        session.headers = {}

        # Step 1: GET /login -> login page with CSRF token
        login_page_resp = MagicMock()
        login_page_resp.status_code = 200
        login_page_resp.headers = {}
        login_page_resp.url = "https://www.laget.se/login"
        login_page_resp.text = '''
        <form action="/Login" method="post" id="login-form">
            <input type="hidden" name="__RequestVerificationToken" value="csrf_token_123">
            <input type="hidden" name="Referer" value="aHR0cHM6Ly93d3cubGFnZXQuc2Uv">
            <input type="text" name="Email" placeholder="E-postadress">
            <input type="password" name="Password" placeholder="Lösenord">
        </form>
        '''

        # Step 2: POST /Login -> redirect to home
        post_resp = MagicMock()
        post_resp.status_code = 302
        post_resp.headers = {"Location": "https://www.laget.se/"}
        post_resp.url = "https://www.laget.se/Login"

        home_resp = MagicMock()
        home_resp.status_code = 200
        home_resp.headers = {}
        home_resp.url = "https://www.laget.se/"
        home_resp.text = "<html>Home</html>"

        # Step 3: verify_authenticated -> notification count
        auth_check_resp = MagicMock()
        auth_check_resp.status_code = 200
        auth_check_resp.json.return_value = {"general": 0, "rsvp": 0, "unreadMessages": 0}

        session.get.side_effect = [
            login_page_resp,   # GET /login
            home_resp,         # follow_redirects after POST
            auth_check_resp,   # verify_authenticated
        ]
        session.post.return_value = post_resp

        return session

    def test_login_returns_session(self):
        session = self._mock_login_flow()
        result = login("test@example.com", "password123", session_path=None, _session=session)
        assert result is session

    def test_login_posts_credentials(self):
        session = self._mock_login_flow()
        login("test@example.com", "password123", session_path=None, _session=session)

        session.post.assert_called_once()
        call_args = session.post.call_args
        assert call_args[1]["data"]["Email"] == "test@example.com"
        assert call_args[1]["data"]["Password"] == "password123"
        assert call_args[1]["data"]["__RequestVerificationToken"] == "csrf_token_123"
        assert call_args[1]["data"]["KeepAlive"] == "true"

    def test_login_raises_on_missing_csrf(self):
        session = MagicMock()
        session.headers = {}
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.url = "https://www.laget.se/login"
        resp.text = "<html>No hidden fields</html>"
        session.get.return_value = resp

        try:
            login("test@example.com", "pass", session_path=None, _session=session)
            assert False, "Should have raised AuthError"
        except AuthError as e:
            assert "CSRF" in str(e)

    def test_login_reuses_saved_session(self):
        """If saved session is valid, skip login."""
        session = MagicMock()
        session.headers = {}

        auth_check_resp = MagicMock()
        auth_check_resp.status_code = 200
        auth_check_resp.json.return_value = {"general": 0}
        session.get.return_value = auth_check_resp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{
                "name": "auth",
                "value": "valid",
                "domain": ".laget.se",
                "path": "/",
                "secure": True,
                "httponly": True,
            }], f)
            path = f.name

        try:
            result = login("test@example.com", "pass", session_path=path, _session=session)
            assert result is session
            # Should NOT have called POST (no login needed)
            assert session.post.call_count == 0
        finally:
            os.unlink(path)
