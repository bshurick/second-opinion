from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone

import pytest

from second_opinion.brokers import etrade_auth as ea
from second_opinion.config import ETradeSettings
from second_opinion.errors import ConfigError

SETTINGS = ETradeSettings("ck", "cs", sandbox=False)


class FakeSession:
    """Stands in for requests_oauthlib.OAuth1Session."""

    def __init__(self, log: list, **kw) -> None:
        self.kw = kw
        self.log = log
        log.append(("session", kw))

    def fetch_request_token(self, url):
        self.log.append(("request_token", url, self.kw.get("callback_uri")))
        return {"oauth_token": "rt", "oauth_token_secret": "rts"}

    def fetch_access_token(self, url):
        self.log.append(("access_token", url, self.kw.get("verifier")))
        return {"oauth_token": "at", "oauth_token_secret": "ats"}

    def get(self, url, **kw):
        self.log.append(("get", url))
        code = 200 if "renew" in url and self.kw.get("resource_owner_key") == "at" else 401
        return type("R", (), {"status_code": code, "text": ""})()


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture
def auth(data):
    log: list = []
    clock = {"now": datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)}  # 11:00 ET
    a = ea.ETradeAuth(SETTINGS, now=lambda: clock["now"], session_factory=lambda **kw: FakeSession(log, **kw))
    a.log, a.clock = log, clock  # test handles
    return a


def test_start_writes_pending_and_returns_authorize_url(auth, data) -> None:
    out = auth.start()
    assert out["url"] == ea.AUTHORIZE_URL.format(key="ck", token="rt") and out["sandbox"] is False
    pending = json.loads((data / "etrade-pending.json").read_text())
    assert pending["request_token"] == "rt" and pending["request_token_secret"] == "rts"
    assert stat.S_IMODE(os.stat(data / "etrade-pending.json").st_mode) == 0o600
    assert ("request_token", ea.OAUTH_BASE + "/oauth/request_token", "oob") in auth.log


def test_start_reuses_fresh_pending_and_replaces_stale(auth, data) -> None:
    first = auth.start()
    auth.clock["now"] += timedelta(minutes=2)
    assert auth.start()["url"] == first["url"] and auth.log.count(("request_token", ea.OAUTH_BASE + "/oauth/request_token", "oob")) == 1
    auth.clock["now"] += timedelta(minutes=4)
    auth.start()
    assert auth.log.count(("request_token", ea.OAUTH_BASE + "/oauth/request_token", "oob")) == 2


def test_complete_exchanges_verifier_and_writes_token_0600(auth, data) -> None:
    auth.start()
    tok = auth.complete("ABCDE")
    assert (tok.oauth_token, tok.oauth_token_secret, tok.sandbox) == ("at", "ats", False)
    assert ("access_token", ea.OAUTH_BASE + "/oauth/access_token", "ABCDE") in auth.log
    assert stat.S_IMODE(os.stat(data / "etrade-token.json").st_mode) == 0o600
    assert not (data / "etrade-pending.json").exists()
    assert ea.load_token().oauth_token == "at"


def test_start_missing_package_propagates_as_import_error(monkeypatch, data) -> None:
    monkeypatch.setitem(sys.modules, "requests_oauthlib", None)
    auth = ea.ETradeAuth(SETTINGS)
    with pytest.raises(ImportError):
        auth.start()


def test_complete_without_pending_raises(auth) -> None:
    with pytest.raises(ConfigError) as ei:
        auth.complete("ABCDE")
    assert ei.value.code == "ETRADE_NO_PENDING"


def test_token_state_rules() -> None:
    now = datetime(2026, 9, 8, 3, 30, tzinfo=timezone.utc)  # 23:30 ET on Sep 7
    same_day = ea.Token("a", "b", created_at=datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc), sandbox=False)
    assert ea.token_state(same_day, sandbox=False, now=now) == "usable"
    after_midnight = now + timedelta(hours=1)  # 00:30 ET on Sep 8
    assert ea.token_state(same_day, sandbox=False, now=after_midnight) == "expired"
    assert ea.token_state(same_day, sandbox=True, now=now) == "expired"  # environment mismatch
    assert ea.token_state(None, sandbox=False, now=now) == "none"


def test_token_state_handles_dst_boundary() -> None:
    # Nov 2 03:30 UTC is still Nov 1 in New York (EST after the Nov 1 DST end); 05:30 UTC is Nov 2.
    tok = ea.Token("a", "b", created_at=datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc), sandbox=False)
    assert ea.token_state(tok, sandbox=False, now=datetime(2026, 11, 2, 3, 30, tzinfo=timezone.utc)) == "usable"
    assert ea.token_state(tok, sandbox=False, now=datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)) == "expired"


def test_usable_token_raises_reauth_with_url_when_expired(auth, data) -> None:
    ea.save_token(ea.Token("at", "ats", created_at=auth.clock["now"] - timedelta(days=1), sandbox=False))
    with pytest.raises(ConfigError) as ei:
        auth.usable_token()
    e = ei.value
    assert e.code == "ETRADE_REAUTH" and e.exit_code == 4 and e.extra["url"].startswith("https://us.etrade.com/") and "etrade-login.py --verifier" in e.extra["hint"]
    assert (data / "etrade-pending.json").exists()


def test_renew_true_on_200_false_on_401(auth) -> None:
    assert auth.renew(ea.Token("at", "ats", created_at=auth.clock["now"], sandbox=False)) is True
    assert auth.renew(ea.Token("old", "x", created_at=auth.clock["now"], sandbox=False)) is False


def test_revoke_deletes_token(auth, data) -> None:
    ea.save_token(ea.Token("at", "ats", created_at=auth.clock["now"], sandbox=False))
    auth.revoke()
    assert ("get", ea.OAUTH_BASE + "/oauth/revoke_access_token") in auth.log and ea.load_token() is None


def test_status_reports_without_network(auth) -> None:
    assert auth.status()["token"] == "none"
    ea.save_token(ea.Token("at", "ats", created_at=auth.clock["now"], sandbox=False))
    s = auth.status()
    assert s == {"configured": True, "token": "usable", "created_at": auth.clock["now"].isoformat(timespec="seconds"), "sandbox": False}
    assert auth.log == []  # no session was ever created
