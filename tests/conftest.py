"""Put lib/ on sys.path so tests import second_opinion without installing it."""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIB = PLUGIN_ROOT / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

_REAL_RUN = subprocess.run
_BROWSER_COMMANDS = ("open", "xdg-open")


@pytest.fixture(autouse=True)
def no_real_data_dir(monkeypatch, tmp_path_factory):
    """No test may read the developer's own data directory (its .env, records or caches).
    Tests that need a data directory set SECOND_OPINION_DATA themselves, which overrides this."""
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path_factory.mktemp("no-data")))
    monkeypatch.delenv("FINANCE_ANALYST_DATA", raising=False)


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """No test may reach the user's browser: the connect scripts auto-open URLs."""
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: False)

    def guarded_run(cmd, *args, **kwargs):
        first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else None
        if isinstance(first, str) and first in _BROWSER_COMMANDS:
            raise AssertionError("test tried to open a browser")
        return _REAL_RUN(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
