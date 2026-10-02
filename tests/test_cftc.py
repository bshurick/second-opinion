"""CFTC Traders in Financial Futures rows via the public Socrata endpoint, cached for a day."""
from __future__ import annotations

import json

import pytest
from second_opinion import cftc
from second_opinion.errors import ApiError

ROWS = [
    {"report_date_as_yyyy_mm_dd": "2026-09-08T00:00:00.000", "cftc_contract_market_code": "13874A", "contract_market_name": "E-MINI S&P 500", "open_interest_all": "2000"},
    {"report_date_as_yyyy_mm_dd": "2026-09-08T00:00:00.000", "cftc_contract_market_code": "209742", "contract_market_name": "NASDAQ MINI", "open_interest_all": "300"},
    {"report_date_as_yyyy_mm_dd": "2026-09-01T00:00:00.000", "cftc_contract_market_code": "13874A", "contract_market_name": "E-MINI S&P 500", "open_interest_all": "1990"},
]


def test_positioning_groups_rows_by_contract_and_caches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(cftc, "_fetch", lambda url: (calls.append(url), json.dumps(ROWS).encode())[1])
    out = cftc.positioning(["13874A", "209742", "098662"], weeks=2)
    assert set(out) == {"13874A", "209742", "098662"} and len(out["13874A"]) == 2 and out["098662"] == []
    assert out["13874A"][0]["report_date_as_yyyy_mm_dd"].startswith("2026-09-08")
    assert len(calls) == 1 and calls[0].startswith(cftc.TFF_URL) and "13874A" in calls[0] and "$limit=" in calls[0]
    cftc.positioning(["13874A", "209742", "098662"], weeks=2)
    assert len(calls) == 1  # same request served from the cache


def test_positioning_requests_enough_rows_for_the_weeks_asked(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    seen: list[str] = []
    monkeypatch.setattr(cftc, "_fetch", lambda url: (seen.append(url), b"[]")[1])
    cftc.positioning(["13874A", "209742"], weeks=52)
    assert "$limit=" + str(52 * 2 + cftc.LIMIT_SLACK) in seen[0]


def test_positioning_rejects_bad_codes() -> None:
    with pytest.raises(ValueError):
        cftc.positioning(["13874A'; drop"], weeks=1)


def test_non_json_is_an_api_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(cftc, "_fetch", lambda url: b"<html>")
    with pytest.raises(ApiError) as excinfo:
        cftc.positioning(["13874A"], weeks=1)
    assert excinfo.value.code == "CFTC_HTTP"


def test_dropped_connection_is_an_api_error(monkeypatch, tmp_path) -> None:
    import urllib.request

    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))

    def boom(req, timeout=0):
        raise ConnectionResetError("closed")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ApiError) as excinfo:
        cftc.positioning(["13874A"], weeks=1)
    assert excinfo.value.code == "CFTC_HTTP"
