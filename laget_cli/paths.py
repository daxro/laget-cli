"""Platform-native paths and secure persistence helpers."""

import os
from pathlib import Path
import tempfile

import platformdirs

_APP = "laget"

CONFIG_DIR = Path(platformdirs.user_config_dir(_APP))
STATE_DIR = Path(platformdirs.user_state_dir(_APP))

CONFIG_FILE = CONFIG_DIR / "config.env"
SESSION_FILE = STATE_DIR / "session.json"
STATE_FILE = STATE_DIR / "state.json"


def atomic_write_text(path, text, mode=0o600):
    """Atomically replace a text file with restrictive permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            os.chmod(temp_path, mode)
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
        os.chmod(path, mode)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
