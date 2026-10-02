"""FINRA consolidated daily short-sale volume files, one per trading day, cached forever."""
from __future__ import annotations

from datetime import date

import pytest
from second_opinion import finra
from second_opinion.errors import ApiError

FILE = b"Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260911|AAPL|400.5|1|1000|B,Q,N\n20260911|MSFT|10|0|20|Q\n"


def test_short_volume_walks_back_over_trading_days_and_skips_missing_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if "20260911" in url or "20260910" in url:
            return FILE.replace(b"20260911", url[-12:-4].encode())
        raise ApiError("no file", code="FINRA_HTTP", http_status=403)

    monkeypatch.setattr(finra, "_fetch", fetch)
    out = finra.short_volume(["aapl", "ZZZ"], days=2, today=date(2026, 9, 13))  # a Sunday
    assert out["AAPL"] == [{"date": "2026-09-10", "short": 400.5, "total": 1000.0}, {"date": "2026-09-11", "short": 400.5, "total": 1000.0}]
    assert out["ZZZ"] == []
    assert [u[-12:-4] for u in calls] == ["20260911", "20260910"]  # weekend skipped without a request
    assert (tmp_path / "finra-cache" / "CNMSshvol20260911.txt").is_file()


def test_short_volume_gives_up_after_the_lookback_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        raise ApiError("no file", code="FINRA_HTTP", http_status=404)

    monkeypatch.setattr(finra, "_fetch", fetch)
    out = finra.short_volume(["AAPL"], days=3, today=date(2026, 9, 11))
    assert out == {"AAPL": []} and len(calls) == 3 + finra.HOLIDAY_SLACK


def test_short_volume_uses_the_cache_before_the_network(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    (tmp_path / "finra-cache").mkdir()
    (tmp_path / "finra-cache" / "CNMSshvol20260911.txt").write_bytes(FILE)
    monkeypatch.setattr(finra, "_fetch", lambda url: (_ for _ in ()).throw(AssertionError("network used")))
    out = finra.short_volume(["MSFT"], days=1, today=date(2026, 9, 11))
    assert out == {"MSFT": [{"date": "2026-09-11", "short": 10.0, "total": 20.0}]}


def test_other_http_errors_propagate(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(finra, "_fetch", lambda url: (_ for _ in ()).throw(ApiError("boom", code="FINRA_HTTP", http_status=500)))
    with pytest.raises(ApiError):
        finra.short_volume(["AAPL"], days=1, today=date(2026, 9, 11))


def test_symbols_are_validated() -> None:
    with pytest.raises(ValueError):
        finra.short_volume(["AA PL"], days=1)
