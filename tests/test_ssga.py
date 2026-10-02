"""SPDR fund-finder snapshot (NAV, AUM, derived shares outstanding) and the local daily series it feeds."""
from __future__ import annotations

import json

import pytest
from second_opinion import ssga
from second_opinion.errors import ApiError

FINDER = {"data": {"funds": {"etfs": {"datas": [
    {"fundTicker": "XLK®", "fundName": "Technology Select Sector SPDR", "nav": ["$187.73", 187.73], "aum": ["$121,839.35 M", 121839.35], "asOfDate": ["Sep 11 2026", "2026-09-11"]},
    {"fundTicker": "SPY", "fundName": "SPDR S&P 500 ETF Trust", "nav": ["$764.35", 764.35], "aum": ["$810,275.04 M", 810275.04], "asOfDate": ["Sep 11 2026", "2026-09-11"]},
    {"fundTicker": "GLD", "fundName": "SPDR Gold Shares", "nav": ["-", None], "aum": ["$1 M", 1.0], "asOfDate": ["Sep 11 2026", "2026-09-11"]},
]}}}}


@pytest.fixture
def finder(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(ssga, "_fetch", lambda url: (calls.append(url), json.dumps(FINDER).encode())[1])
    return calls


def test_snapshot_derives_shares_from_aum_and_nav(finder) -> None:
    out = ssga.snapshot(["XLK", "SPY", "GLD", "XLE"])
    assert out["XLK"] == {"date": "2026-09-11", "nav": 187.73, "aum_usd": 121_839_350_000.0, "shares": round(121_839_350_000.0 / 187.73)}
    assert out["SPY"]["shares"] == round(810_275_040_000.0 / 764.35)
    assert out["GLD"] is None and out["XLE"] is None  # no NAV; not in the finder
    assert len(finder) == 1 and finder[0] == ssga.FINDER_URL


def test_snapshot_is_cached_for_a_day(finder) -> None:
    ssga.snapshot(["XLK"])
    ssga.snapshot(["XLK"])
    assert len(finder) == 1


def test_record_appends_one_observation_per_date_and_returns_the_series(finder, tmp_path) -> None:
    snap = ssga.snapshot(["XLK", "SPY", "GLD"])
    series = ssga.record(snap)
    assert series["XLK"] == [{"date": "2026-09-11", "nav": 187.73, "aum_usd": 121_839_350_000.0, "shares": round(121_839_350_000.0 / 187.73)}]
    assert "GLD" not in series
    path = tmp_path / "etf-shares.json"
    assert path.is_file()
    # same date again replaces rather than duplicates; an older date sorts first
    series = ssga.record({"XLK": {"date": "2026-09-11", "nav": 188.0, "aum_usd": 1.0, "shares": 5}, "SPY": {"date": "2026-09-10", "nav": 760.0, "aum_usd": 2.0, "shares": 6}})
    assert series["XLK"] == [{"date": "2026-09-11", "nav": 188.0, "aum_usd": 1.0, "shares": 5}]
    assert [o["date"] for o in series["SPY"]] == ["2026-09-10", "2026-09-11"]
    assert json.loads(path.read_text())["XLK"][0]["shares"] == 5


def test_record_survives_a_corrupt_series_file(finder, tmp_path) -> None:
    (tmp_path / "etf-shares.json").write_text("{not json")
    series = ssga.record({"XLK": {"date": "2026-09-11", "nav": 1.0, "aum_usd": 1.0, "shares": 1}})
    assert series == {"XLK": [{"date": "2026-09-11", "nav": 1.0, "aum_usd": 1.0, "shares": 1}]}


def test_unexpected_payload_is_an_api_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(ssga, "_fetch", lambda url: b'{"data": {}}')
    with pytest.raises(ApiError) as excinfo:
        ssga.snapshot(["XLK"])
    assert excinfo.value.code == "SSGA_HTTP"
