from __future__ import annotations

import pytest

from fakes import FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client
from second_opinion.brokers import router

FAKE_BROKERAGES = [
    {"name": "E*TRADE", "slug": "ETRADE", "enabled": True, "maintenance_mode": False, "allows_trading": True, "allows_fractional_units": True},
    {"name": "Fidelity", "slug": "FIDELITY", "enabled": True, "maintenance_mode": False, "allows_trading": False, "allows_fractional_units": False},
    {"name": "Acme Test Broker", "slug": "ACME", "enabled": False, "maintenance_mode": True, "allows_trading": None, "allows_fractional_units": None},
]


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_all_brokerages=FAKE_BROKERAGES)
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_brokers_lists_sorted_with_mapped_fields(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), [], capsys)
    assert rc == 0
    assert out["count"] == 3
    assert "query" not in out
    assert out["brokerages"] == [
        {"name": "Acme Test Broker", "slug": "ACME", "supports_trade": None, "supports_read": False, "maintenance_mode": True},
        {"name": "E*TRADE", "slug": "ETRADE", "supports_trade": True, "supports_read": True, "maintenance_mode": False},
        {"name": "Fidelity", "slug": "FIDELITY", "supports_trade": False, "supports_read": True, "maintenance_mode": False},
    ]


def test_brokers_query_filters_case_insensitively_on_name_or_slug(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), ["--query", "fide"], capsys)
    assert rc == 0
    assert out["query"] == "fide"
    assert out["count"] == 1
    assert [b["name"] for b in out["brokerages"]] == ["Fidelity"]


def test_brokers_query_matches_slug(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), ["--query", "acme"], capsys)
    assert rc == 0
    assert out["count"] == 1
    assert out["brokerages"][0]["slug"] == "ACME"


def test_brokers_query_no_match_is_empty_not_an_error(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), ["--query", "nonexistent"], capsys)
    assert rc == 0
    assert out["count"] == 0
    assert out["brokerages"] == []
    assert out["query"] == "nonexistent"


def test_brokers_missing_query_value_is_invalid_input(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), ["--query"], capsys)
    assert rc == 2


def test_brokers_unknown_flag_is_invalid_input(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/brokers.py"), ["--bogus"], capsys)
    assert rc == 2
