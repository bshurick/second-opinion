"""FRED keyless CSV series: latest observation with a daily cache."""

from __future__ import annotations

import pytest
from second_opinion import fred
from second_opinion.errors import ApiError

CSV = b"observation_date,DGS10\n2026-09-05,4.21\n2026-09-08,.\n2026-09-09,4.18\n"


def test_latest_skips_missing_observations_and_caches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(fred, "_fetch", lambda url: (calls.append(url), CSV)[1])
    out = fred.latest("DGS10")
    assert out == {"series": "DGS10", "date": "2026-09-09", "value": 4.18}
    assert calls == ["https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"]
    assert (tmp_path / "fred-cache" / "DGS10.csv").is_file()
    fred.latest("DGS10")
    assert len(calls) == 1  # served from the cache


def test_latest_with_no_numeric_rows_is_an_api_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(fred, "_fetch", lambda url: b"observation_date,AAA\n2026-08-01,.\n")
    with pytest.raises(ApiError) as excinfo:
        fred.latest("AAA")
    assert excinfo.value.code == "FRED_HTTP"


def test_series_id_is_validated() -> None:
    with pytest.raises(ValueError):
        fred.latest("../etc/passwd")


def test_dropped_connection_is_an_api_error(monkeypatch, tmp_path) -> None:
    """FRED closes the socket on some clients; that must degrade like an HTTP error, not crash."""
    import urllib.request

    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))

    def boom(req, timeout=0):
        raise ConnectionResetError("Remote end closed connection without response")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ApiError) as excinfo:
        fred.latest("DGS10")
    assert excinfo.value.code == "FRED_HTTP"


def test_observations_returns_the_last_n_numeric_rows_oldest_first(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(fred, "_fetch", lambda url: b"observation_date,WRMFNS\n2026-06-01,2900.0\n2026-07-01,.\n2026-08-01,3009.1\n2026-09-01,3020.5\n")
    assert fred.observations("WRMFNS", 2) == [{"date": "2026-08-01", "value": 3009.1}, {"date": "2026-09-01", "value": 3020.5}]
    assert len(fred.observations("WRMFNS", 10)) == 3
    assert fred.SERIES_NAMES["WRMFNS"] == "Retail Money Market Funds"
