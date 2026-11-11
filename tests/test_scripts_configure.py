"""get-started/scripts/configure.py keys: hidden-input key entry without Node."""
from __future__ import annotations

import stat

import pytest
from scripts_util import load_script

C = "get-started/scripts/configure.py"


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _answers(mod, monkeypatch, values: list[str], tty: bool = True) -> list[str]:
    asked: list[str] = []
    it = iter(values)

    def fake(prompt: str = "") -> str:
        asked.append(prompt)
        return next(it)

    monkeypatch.setattr(mod.getpass, "getpass", fake)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: tty)
    return asked


def test_keys_written_at_0600_keeping_other_lines(data, monkeypatch, capsys) -> None:
    env = data / ".env"
    env.write_text('# my keys\nEDGAR_USER_AGENT="app me@example.com"\nSNAPTRADE_CLIENT_ID=old-id\n')
    env.chmod(0o644)
    mod = load_script(C)
    asked = _answers(mod, monkeypatch, ["new-id", "new-secret"])
    assert mod.main(["keys"]) == 0
    assert [a.split(" ")[0] for a in asked] == ["SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"]
    assert env.read_text() == ('# my keys\nEDGAR_USER_AGENT="app me@example.com"\nSNAPTRADE_CLIENT_ID=new-id\n'
                               'SNAPTRADE_CONSUMER_KEY=new-secret\n')
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    out = capsys.readouterr().out
    assert "new-secret" not in out and "SNAPTRADE_CONSUMER_KEY" in out


def test_blank_input_keeps_the_saved_key(data, monkeypatch, capsys) -> None:
    env = data / ".env"
    env.write_text("SNAPTRADE_CLIENT_ID=keep-me\nSNAPTRADE_CONSUMER_KEY=old-secret\n")
    mod = load_script(C)
    _answers(mod, monkeypatch, ["", "  "])
    assert mod.main(["keys"]) == 0
    assert env.read_text() == "SNAPTRADE_CLIENT_ID=keep-me\nSNAPTRADE_CONSUMER_KEY=old-secret\n"
    assert "kept" in capsys.readouterr().out


def test_etrade_keys(data, monkeypatch) -> None:
    mod = load_script(C)
    asked = _answers(mod, monkeypatch, ["ek", "es"])
    assert mod.main(["keys", "--broker", "etrade"]) == 0
    assert [a.split(" ")[0] for a in asked] == ["ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET"]
    assert (data / ".env").read_text() == "ETRADE_CONSUMER_KEY=ek\nETRADE_CONSUMER_SECRET=es\n"


def test_no_tty_exits_2(data, monkeypatch, capsys) -> None:
    mod = load_script(C)
    asked = _answers(mod, monkeypatch, [], tty=False)
    assert mod.main(["keys"]) == 2
    assert asked == [] and not (data / ".env").exists()
    assert "configure.py keys" in capsys.readouterr().err


def test_bad_arguments_exit_2(data, monkeypatch, capsys) -> None:
    mod = load_script(C)
    _answers(mod, monkeypatch, [])
    assert mod.main([]) == 2 and mod.main(["keys", "--broker", "robinhood"]) == 2
