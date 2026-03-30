"""laget.se session management - login, cookie persistence, auth verification."""

import http.cookiejar
import json
import os
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

from laget_cli.errors import AuthError

AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
BASE_URL = "https://www.laget.se"
HTTP_TIMEOUT = 30
REDIRECT_CODES = (301, 302, 307, 308)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def new_session():
    """Create a requests.Session with browser User-Agent."""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def follow_redirects(session, resp, max_hops=20):
    """Manually follow HTTP redirects, resolving relative URLs."""
    for _ in range(max_hops):
        if resp.status_code not in REDIRECT_CODES:
            break
        location = resp.headers.get("Location", "")
        if not location:
            break
        location = urljoin(resp.url, location)
        resp = session.get(location, allow_redirects=False, timeout=HTTP_TIMEOUT)
    return resp


def parse_hidden_fields(html):
    """Extract all <input type="hidden"> name/value pairs from HTML."""
    fields = {}
    for match in re.finditer(
        r'<input\b[^>]*\btype="hidden"[^>]*/?>',
        html,
        re.IGNORECASE,
    ):
        tag = match.group()
        name = re.search(r'\bname="([^"]+)"', tag)
        value = re.search(r'\bvalue="([^"]*)"', tag)
        if name and value:
            fields[name.group(1)] = unescape(value.group(1))
    return fields


def save_session(session, path="session.json"):
    """Save session cookies to a JSON file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cookies = []
    for c in session.cookies:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "secure": c.secure,
            "httponly": "HttpOnly" in c._rest,
        })
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)
    os.chmod(path, 0o600)


def load_session(session, path="session.json"):
    """Load cookies from a JSON file into the session.

    Returns True if cookies were loaded, False if file missing or corrupt.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    for c in cookies:
        cookie = http.cookiejar.Cookie(
            version=0,
            name=c["name"],
            value=c["value"],
            port=None,
            port_specified=False,
            domain=c["domain"],
            domain_specified=bool(c["domain"]),
            domain_initial_dot=c["domain"].startswith("."),
            path=c.get("path", "/"),
            path_specified=bool(c.get("path")),
            secure=c.get("secure", False),
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": "HttpOnly"} if c.get("httponly") else {},
        )
        session.cookies.set_cookie(cookie)
    return True


def verify_authenticated(session):
    """Check if the session is authenticated using a lightweight endpoint.

    GET /common/Notification/notificationcount returns JSON when authenticated,
    or redirects to login when not.

    Raises AuthError if not authenticated.
    """
    resp = session.get(
        f"{BASE_URL}/common/Notification/notificationcount",
        allow_redirects=False,
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code in REDIRECT_CODES:
        raise AuthError("Session expired - redirected to login")
    if resp.status_code != 200:
        raise AuthError(f"Auth check failed with status {resp.status_code}")
    try:
        resp.json()
    except ValueError:
        raise AuthError("Auth check returned unexpected response")


def login(email, password, session_path="session.json", _session=None):
    """Log into laget.se with email and password.

    Creates a requests.Session, POSTs credentials to the login form,
    follows redirects, and verifies authentication.

    Checks session_path for a saved session first. If valid, skips login.
    On successful login, saves the session to session_path.

    Args:
        email: User's email address.
        password: User's password.
        session_path: Path to session.json for persistence. None to disable.
        _session: Inject a session for testing. Created if not provided.

    Returns:
        Authenticated requests.Session.

    Raises:
        AuthError: If login fails or session cannot be verified.
    """
    session = _session or new_session()

    # Try saved session first
    if session_path and load_session(session, session_path):
        try:
            verify_authenticated(session)
            return session
        except AuthError:
            session = _session or new_session()

    # Step 1: GET login page to extract CSRF token and hidden fields
    resp = session.get(
        f"{BASE_URL}/login",
        allow_redirects=False,
        timeout=HTTP_TIMEOUT,
    )
    resp = follow_redirects(session, resp)
    fields = parse_hidden_fields(resp.text)

    token = fields.get("__RequestVerificationToken")
    if not token:
        raise AuthError("Failed to extract CSRF token from login page")

    # Step 2: POST login form
    form_data = {
        "__RequestVerificationToken": token,
        "Referer": fields.get("Referer", ""),
        "Email": email,
        "Password": password,
        "KeepAlive": "true",
    }
    resp = session.post(
        f"{BASE_URL}/Login",
        data=form_data,
        allow_redirects=False,
        timeout=HTTP_TIMEOUT,
    )
    resp = follow_redirects(session, resp)

    # Step 3: Verify authentication
    verify_authenticated(session)

    # Save session for reuse
    if session_path:
        save_session(session, session_path)

    return session
