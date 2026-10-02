from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts_util import load_script, run_json
from second_opinion.brokers import etrade_auth as ea, router
from second_opinion.config import ETradeSettings, Settings
from test_brokers_router import StubDirect

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


class ScriptedAuth(ea.ETradeAuth):
    def __init__(self):
        super().__init__(ETradeSettings("ck", "cs"), now=lambda: NOW)
        self.log = []

    def start(self):
        self.log.append("start")
        return {"url": "https://us.etrade.com/e/t/etws/authorize?key=ck&token=rt", "sandbox": False, "created_at": "2026-09-08T15:00:00+00:00"}

    def complete(self, verifier):
        self.log.append(("complete", verifier))
        tok = ea.Token("at", "ats", NOW, False)
        ea.save_token(tok)
        return tok

    def revoke(self):
        self.log.append("revoke")
        ea.delete_token()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    auth = ScriptedAuth()
    direct = StubDirect()
    direct.auth = auth
    monkeypatch.setattr(router, "load", lambda settings=None: router.Hub([direct], account_types={}, registry=None))
    monkeypatch.setattr(ea, "ETradeAuth", lambda settings, **kw: auth)
    monkeypatch.setattr("second_opinion.config.load_settings", lambda *a, **k: Settings(etrade=ETradeSettings("ck", "cs")))
    return auth, tmp_path


def test_login_start_prints_url_and_pending(env, monkeypatch, capsys) -> None:
    auth, _ = env
    mod = load_script("connect/scripts/etrade-login.py")
    monkeypatch.setattr(mod, "open_url", lambda url: False)  # never touch the real browser
    rc, out = run_json(mod, [], capsys)
    assert rc == 0 and out == {"url": "https://us.etrade.com/e/t/etws/authorize?key=ck&token=rt", "pending": True, "sandbox": False, "opened": False}
    assert auth.log == ["start"]


def test_login_verifier_completes_and_lists_accounts(env, capsys) -> None:
    auth, _ = env
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--verifier", "abcde"], capsys)
    assert rc == 0 and out["authorized"] is True and [a["account_id"] for a in out["accounts"]] == ["KEY1", "KEY2"]
    assert ("complete", "abcde") in auth.log


def test_login_status_needs_no_network(env, capsys) -> None:
    auth, _ = env
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--status"], capsys)
    assert rc == 0 and out["token"] == "none" and out["configured"] is True and auth.log == []


def test_login_revoke(env, capsys) -> None:
    auth, _ = env
    ea.save_token(ea.Token("at", "ats", NOW, False))
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--revoke"], capsys)
    assert rc == 0 and out == {"revoked": True} and "revoke" in auth.log and ea.load_token() is None


def test_login_rejects_bad_arguments(env, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--verifier"], capsys)
    assert rc == 2
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--status", "--revoke"], capsys)
    assert rc == 2


def test_login_exit_4_when_etrade_not_configured(monkeypatch, capsys) -> None:
    monkeypatch.setattr("second_opinion.config.load_settings", lambda *a, **k: Settings())
    rc, out = run_json(load_script("connect/scripts/etrade-login.py"), ["--status"], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING"
