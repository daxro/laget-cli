import json
import sys


EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_NETWORK = 5


class AuthError(Exception):
    """Login failed, session expired, or credentials missing."""


class NetworkError(Exception):
    """Connection or timeout error."""


class ParseError(Exception):
    """Unexpected HTML structure from a web endpoint."""


def emit_error(code, message, exit_code=EXIT_ERROR):
    """Write structured JSON error to stderr and exit."""
    error = {"error": code, "message": message}
    print(json.dumps(error), file=sys.stderr)
    sys.exit(exit_code)
