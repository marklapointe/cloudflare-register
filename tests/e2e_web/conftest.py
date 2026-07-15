"""E2E fixtures: live server + admin credentials.

The OS-level environment is configured here (not via monkeypatch) so the
uvicorn subprocess inherits it. Per-test isolation is provided by the
``isolated_data_dir`` fixture (a fresh ``tmp_path``-backed XDG root).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

# Sensible test defaults — overridden by CLI: ``make test-e2e`` sets the
# same values in the environment block.
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "test-token-1234567890abcdef")
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "very-secret-test-password")
os.environ.setdefault("HTTP_HOST", "127.0.0.1")
os.environ.setdefault("HTTP_PORT", "18099")
os.environ.setdefault("LOG_LEVEL", "WARNING")

_E2E_PORT = int(os.environ["HTTP_PORT"])
_SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "docs" / "screenshots"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_healthz(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = requests.get(url + "/healthz", timeout=2)
            if response.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="session")
def isolated_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data_dir = tmp_path_factory.mktemp("cfr-e2e-data")
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture(scope="session")
def live_server(isolated_data_dir: Path) -> str:
    """Start uvicorn in a subprocess and return the base URL."""
    port = _free_port()
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(isolated_data_dir / "data")
    env["XDG_CONFIG_HOME"] = str(isolated_data_dir / "config")
    env["XDG_CACHE_HOME"] = str(isolated_data_dir / "cache")
    env["HTTP_PORT"] = str(port)

    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "cloudflare_register.web.app:get_application",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        env=env,
        cwd=str(isolated_data_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        if not _wait_for_healthz(base_url, timeout_s=30.0):
            proc.terminate()
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"uvicorn never returned /healthz. stderr:\n{stderr}")
        yield base_url
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def screenshot_path():
    """Returns a Path under docs/screenshots for the test to use."""
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


@pytest.fixture
def admin_credentials() -> dict[str, str]:
    return {
        "username": os.environ["ADMIN_USERNAME"],
        "password": os.environ["ADMIN_PASSWORD"],
    }
