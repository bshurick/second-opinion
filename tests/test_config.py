from __future__ import annotations

from pathlib import Path

import pytest

from second_opinion import config
from second_opinion.errors import ConfigError, InvalidInput


def test_parse_env_file_handles_comments_quotes_and_export(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# comment\n"
        "\n"
        "SNAPTRADE_CLIENT_ID=abc\n"
        "export SNAPTRADE_CONSUMER_KEY='s3cr=t'\n"
        'OTHER="quoted value"\n'
        'EDGAR_USER_AGENT="my-app-name me@example.com"\r\n'
        "UNQUOTED_WITH_SPACE=my-app-name me@example.com\n"
        "BROKEN LINE WITHOUT EQUALS\n"
    )
    assert config.parse_env_file(p) == {
        "SNAPTRADE_CLIENT_ID": "abc",
        "SNAPTRADE_CONSUMER_KEY": "s3cr=t",
        "OTHER": "quoted value",
        "EDGAR_USER_AGENT": "my-app-name me@example.com",  # the installer's quoted form, CR tolerated
        "UNQUOTED_WITH_SPACE": "my-app-name me@example.com",  # the older unquoted form still parses
    }


def test_load_settings_prefers_process_env(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("SNAPTRADE_CLIENT_ID=file\nSNAPTRADE_CONSUMER_KEY=filekey\n")
    s = config.load_settings(env={"SNAPTRADE_CLIENT_ID": "env", "SNAPTRADE_CONSUMER_KEY": "envkey"}, env_file=p)
    assert (s.snaptrade.client_id, s.snaptrade.consumer_key) == ("env", "envkey")
    assert s.client_id == "env"  # compatibility property


def test_load_settings_falls_back_to_env_file(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("SNAPTRADE_CLIENT_ID=file\nSNAPTRADE_CONSUMER_KEY=filekey\nETRADE_CONSUMER_KEY=ek\nETRADE_CONSUMER_SECRET=es\nETRADE_SANDBOX=1\n")
    s = config.load_settings(env={}, env_file=p)
    assert (s.snaptrade.client_id, s.snaptrade.consumer_key) == ("file", "filekey")
    assert (s.etrade.consumer_key, s.etrade.consumer_secret, s.etrade.sandbox) == ("ek", "es", True)
    assert s.configured


def test_load_settings_without_credentials_is_unconfigured(tmp_path: Path) -> None:
    s = config.load_settings(env={}, env_file=tmp_path / "absent")
    assert s.snaptrade is None and s.etrade is None and not s.configured
    with pytest.raises(ConfigError) as ei:
        s.require_snaptrade()
    assert ei.value.exit_code == 4 and ei.value.code == "CONFIG_MISSING" and ei.value.extra["hint"] == config.SETUP_HINT
    with pytest.raises(ConfigError) as ei2:
        s.require_etrade()
    assert ei2.value.extra["hint"] == config.ETRADE_SETUP_HINT


def test_load_settings_half_pair_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as ei:
        config.load_settings(env={"SNAPTRADE_CLIENT_ID": "x"}, env_file=tmp_path / "absent")
    assert "SNAPTRADE_CONSUMER_KEY" in str(ei.value)
    with pytest.raises(ConfigError) as ei2:
        config.load_settings(env={"ETRADE_CONSUMER_SECRET": "x"}, env_file=tmp_path / "absent")
    assert "ETRADE_CONSUMER_KEY" in str(ei2.value)


def test_account_types_alias(tmp_path: Path) -> None:
    s = config.load_settings(env={"BROKER_ACCOUNT_TYPES": "a=margin"}, env_file=tmp_path / "absent")
    assert s.account_types == {"a": "margin"}
    s2 = config.load_settings(env={"SNAPTRADE_ACCOUNT_TYPES": "b=margin"}, env_file=tmp_path / "absent")
    assert s2.account_types == {"b": "margin"}


def test_data_dir_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_data_dir_ignores_host_claude_plugin_data(monkeypatch, tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_DATA is set by Claude Code, per load path, in hook processes only; honouring it
    would split the data between the hooks' directory and the scripts' directory."""
    _fresh_home(monkeypatch, tmp_path)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "host"))
    assert config.data_dir() == tmp_path / ".claude" / "plugins" / "data" / "second-opinion"


def _fresh_home(monkeypatch, home: Path) -> Path:
    for var in ("SECOND_OPINION_DATA", "FINANCE_ANALYST_DATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(home))
    return home / ".claude" / "plugins" / "data"


def test_data_dir_accepts_the_old_override_name(monkeypatch, tmp_path: Path) -> None:
    _fresh_home(monkeypatch, tmp_path)
    monkeypatch.setenv("FINANCE_ANALYST_DATA", str(tmp_path / "old"))
    assert config.data_dir() == tmp_path / "old"
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "new"))
    assert config.data_dir() == tmp_path / "new"  # the new name wins


def test_data_dir_reads_through_to_the_pre_rename_dir(monkeypatch, tmp_path: Path) -> None:
    base = _fresh_home(monkeypatch, tmp_path)
    (base / "finance-analyst").mkdir(parents=True)
    assert config.data_dir() == base / "finance-analyst"  # not migrated yet
    (base / "second-opinion" / "edgar-cache").mkdir(parents=True)
    assert config.data_dir() == base / "finance-analyst"  # a dir of regenerable caches does not count
    (base / "second-opinion" / "profile.json").write_text("{}")
    assert config.data_dir() == base / "second-opinion"


def test_data_dir_defaults_to_the_new_name(monkeypatch, tmp_path: Path) -> None:
    base = _fresh_home(monkeypatch, tmp_path)
    assert config.data_dir() == base / "second-opinion"


def test_env_precedence_process_then_data_dir_then_plugin_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".env").write_text("SNAPTRADE_CLIENT_ID=data\nSNAPTRADE_CONSUMER_KEY=datakey\nETRADE_CONSUMER_KEY=\n")
    root = tmp_path / "root"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".env").write_text("SNAPTRADE_CLIENT_ID=root\nETRADE_CONSUMER_KEY=rootkey\nETRADE_CONSUMER_SECRET=rootsecret\n")
    monkeypatch.setattr(config, "PLUGIN_ROOT", root)
    assert config.env_files() == [tmp_path / "data" / ".env", root / ".env"]
    s = config.load_settings(env={"SNAPTRADE_CONSUMER_KEY": "envkey"})
    assert s.snaptrade == config.SnapTradeSettings("data", "envkey")
    assert s.etrade is not None and s.etrade.consumer_key == "rootkey"  # an empty value never shadows a later file


@pytest.mark.parametrize(
    ("data_rec", "root_rec", "on"),
    [
        (None, None, False),  # no record: extras are opt-in
        ('{"extras": {"follow_ups": true}}', None, True),
        ('{"extras": {"follow_ups": false}}', '{"extras": {"follow_ups": true}}', False),  # the data dir wins
        (None, '{"extras": {"follow_ups": true}}', True),  # an older copy install
        ('{"skills": []}', None, False),  # a record from before extras: off
        ("not json", None, False),
    ],
)
def test_extra_enabled_follows_the_record(monkeypatch, tmp_path: Path, data_rec, root_rec, on) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "root").mkdir()
    monkeypatch.setattr(config, "PLUGIN_ROOT", tmp_path / "root")
    if data_rec is not None:
        (tmp_path / "data" / "installed.json").write_text(data_rec)
    if root_rec is not None:
        (tmp_path / "root" / "installed.json").write_text(root_rec)
    assert config.extra_enabled("follow_ups") is on


def test_skill_extras_fall_back_to_the_skills_list() -> None:
    assert config.extra_enabled("trade-journal", {"skills": ["trade-journal"], "extras": {"follow_ups": False}}) is True
    assert config.extra_enabled("trade-journal", {"skills": ["trade-journal"], "extras": {"trade-journal": False}}) is False
    assert config.extra_enabled("trade-journal", {"skills": [], "extras": {}}) is False


def test_parse_account_types() -> None:
    assert config.parse_account_types("a1=cash, b2=margin") == {"a1": "cash", "b2": "margin"}
    assert config.parse_account_types("") == {}
    with pytest.raises(InvalidInput):
        config.parse_account_types("a1=savings")


def test_find_env_file_walks_up_to_plugin_root(tmp_path: Path) -> None:
    root = tmp_path / "plug"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".env").write_text("X=1\n")
    deep = root / "skills" / "s" / "scripts"
    deep.mkdir(parents=True)
    assert config.find_env_file(deep) == root / ".env"
    assert config.find_env_file(tmp_path) is None


def test_env_value_reads_the_data_dir_env_when_the_process_env_lacks_it(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text('EDGAR_USER_AGENT="my-app me@example.com"\n')
    monkeypatch.setenv("SECOND_OPINION_DATA", str(data))
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    assert config.env_value("EDGAR_USER_AGENT") == "my-app me@example.com"
    monkeypatch.setenv("EDGAR_USER_AGENT", "env-wins you@example.com")
    assert config.env_value("EDGAR_USER_AGENT") == "env-wins you@example.com"
