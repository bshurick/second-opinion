"""Yahoo helpers used by the portfolio-snapshot skill: batched day changes, the
on-disk sector cache, and next earnings / ex-dividend dates."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from second_opinion import market


class _Ticker:
    def __init__(self, info: dict | None = None, calendar: object = None, fail: bool = False, funds_data: object = None) -> None:
        self.info, self.calendar, self.fail, self.funds_data = info or {}, calendar, fail, funds_data
        self.info_reads = 0

    def __getattribute__(self, name: str):
        if name == "info":
            object.__setattr__(self, "info_reads", object.__getattribute__(self, "info_reads") + 1)
            if object.__getattribute__(self, "fail"):
                raise RuntimeError("yahoo down")
        return object.__getattribute__(self, name)


class _FundsData:
    """Fake ``yfinance`` ``funds_data``: each property is fetched and can fail independently."""

    def __init__(self, sector_weightings: dict | None = None, asset_classes: dict | None = None, fail_sectors: bool = False, fail_classes: bool = False) -> None:
        self._sw, self._ac, self._fail_sectors, self._fail_classes = sector_weightings, asset_classes, fail_sectors, fail_classes
        self.sector_reads = self.classes_reads = 0

    @property
    def sector_weightings(self):
        self.sector_reads += 1
        if self._fail_sectors:
            raise RuntimeError("no sector data")
        return self._sw

    @property
    def asset_classes(self):
        self.classes_reads += 1
        if self._fail_classes:
            raise RuntimeError("no asset-class data")
        return self._ac


def _patch(monkeypatch, tickers: dict[str, _Ticker] | None = None, download=None) -> None:
    tickers = tickers or {}
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: tickers[s], download=download))


# --- day_changes -------------------------------------------------------------


def test_day_changes_batches_one_download_and_uses_last_two_closes(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    calls: list[dict] = []

    def download(tickers, **kw):
        calls.append({"tickers": tickers, **kw})
        idx = pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])
        cols = pd.MultiIndex.from_product([["AAPL", "MSFT", "NEW"], ["Open", "Close"]])
        df = pd.DataFrame(index=idx, columns=cols, dtype="float64")
        df[("AAPL", "Close")] = [95.0, 98.0, 100.0]
        df[("MSFT", "Close")] = [200.0, 200.0, 190.0]
        df[("NEW", "Close")] = [float("nan"), float("nan"), 10.0]  # listed yesterday: one close only
        return df

    _patch(monkeypatch, download=download)
    out = market.day_changes(["aapl", "MSFT", "NEW"])
    assert len(calls) == 1 and calls[0]["tickers"] == ["AAPL", "MSFT", "NEW"] and calls[0]["group_by"] == "ticker"
    assert out == {"AAPL": {"price": 100.0, "previous_close": 98.0, "source": "yahoo"}, "MSFT": {"price": 190.0, "previous_close": 200.0, "source": "yahoo"}}


def test_day_changes_single_symbol_flat_frame(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Open": [1.0, 1.0], "Close": [1.5, 2.0]}, index=pd.to_datetime(["2026-09-02", "2026-09-03"]))
    _patch(monkeypatch, download=lambda tickers, **kw: df)
    assert market.day_changes(["VTI"]) == {"VTI": {"price": 2.0, "previous_close": 1.5, "source": "yahoo"}}


def test_day_changes_empty_input_makes_no_call(monkeypatch) -> None:
    _patch(monkeypatch, download=lambda *a, **k: pytest.fail("download called"))
    assert market.day_changes([]) == {}


# --- sectors -----------------------------------------------------------------


def test_sectors_fills_cache_and_reuses_it(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    aapl = _Ticker({"sector": "Technology", "longName": "Apple Inc.", "quoteType": "EQUITY"})
    vti = _Ticker({"longName": "Vanguard Total Stock Market ETF", "quoteType": "ETF"})
    _patch(monkeypatch, {"AAPL": aapl, "VTI": vti})

    out = market.sectors(["aapl", "VTI"], cache_path=cache)
    assert out == {
        "AAPL": {"sector": "Technology", "name": "Apple Inc.", "quote_type": "EQUITY", "category": None, "country": None, "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None},
        # VTI is a fund but has no funds_data stub here, so the look-through fetch fails and
        # degrades to null -- but fund_fetched is still recorded (the attempt happened), so a
        # same-day rerun does not hammer it again (the 1-day retry window, see below)
        "VTI": {"sector": "ETF", "name": "Vanguard Total Stock Market ETF", "quote_type": "ETF", "category": None, "country": None, "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": date.today().isoformat()},
    }
    assert json.loads(cache.read_text()) == out
    assert aapl.info_reads == 1

    again = market.sectors(["AAPL", "VTI"], cache_path=cache)
    # served from cache -- including VTI, whose failed fund fetch is not retried within the
    # 1-day window, so its info is read only once across both calls
    assert again == out and aapl.info_reads == 1 and vti.info_reads == 1


def test_sectors_cache_entry_without_quote_type_defaults_to_none(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    cache.write_text(json.dumps({"AAPL": {"sector": "Technology", "name": "Apple Inc."}}))
    _patch(monkeypatch, {})
    out = market.sectors(["AAPL"], cache_path=cache)
    # an entry from before category/country existed is refreshed; when the refresh fails the cached fields survive
    assert out == {"AAPL": {"sector": "Technology", "name": "Apple Inc.", "quote_type": None, "category": None, "country": None, "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}}


def test_sectors_lookup_failure_is_not_cached(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    _patch(monkeypatch, {"BAD": _Ticker(fail=True)})
    assert market.sectors(["BAD"], cache_path=cache) == {"BAD": {"sector": None, "name": None, "quote_type": None, "category": None, "country": None, "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}}
    assert not cache.exists()


def test_sectors_survives_corrupt_cache(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    cache.write_text("{not json")
    _patch(monkeypatch, {"AAPL": _Ticker({"sector": "Technology", "longName": "Apple"})})
    assert market.sectors(["AAPL"], cache_path=cache)["AAPL"]["sector"] == "Technology"
    assert json.loads(cache.read_text())["AAPL"]["sector"] == "Technology"


def test_sector_cache_path_honours_plugin_data_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert market.sector_cache_path() == tmp_path / "sector-cache.json"


# --- sectors: fund sector look-through --------------------------------------


def test_sectors_fetches_fund_sector_weightings_and_asset_classes_for_etfs(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    vti_funds = _FundsData({"technology": 0.31, "healthcare": 0.10}, {"stockPosition": 0.99, "cashPosition": 0.01})
    bnd_funds = _FundsData({}, {"bondPosition": 0.98, "cashPosition": 0.02})  # bond funds: {} sectors, still a success
    aapl_funds = _FundsData(fail_sectors=True, fail_classes=True)  # a stock must never even try
    vti = _Ticker({"longName": "Vanguard Total Stock Market ETF", "quoteType": "ETF"}, funds_data=vti_funds)
    bnd = _Ticker({"longName": "Vanguard Total Bond Market ETF", "quoteType": "ETF"}, funds_data=bnd_funds)
    aapl = _Ticker({"sector": "Technology", "longName": "Apple Inc.", "quoteType": "EQUITY"}, funds_data=aapl_funds)
    _patch(monkeypatch, {"VTI": vti, "BND": bnd, "AAPL": aapl})

    out = market.sectors(["VTI", "BND", "AAPL"], cache_path=cache)
    assert out["VTI"]["fund_sectors"] == {"technology": 0.31, "healthcare": 0.10}
    assert out["VTI"]["fund_asset_classes"] == {"stockPosition": 0.99, "cashPosition": 0.01}
    assert out["VTI"]["fund_fetched"] == date.today().isoformat()
    assert out["BND"]["fund_sectors"] == {} and out["BND"]["fund_fetched"] == date.today().isoformat()
    assert out["AAPL"]["fund_sectors"] is None and out["AAPL"]["fund_asset_classes"] is None and out["AAPL"]["fund_fetched"] is None
    assert aapl_funds.sector_reads == 0 and aapl_funds.classes_reads == 0  # stocks never ask funds_data
    assert json.loads(cache.read_text())["VTI"]["fund_sectors"] == {"technology": 0.31, "healthcare": 0.10}


def test_sectors_fund_field_failures_are_independent(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    funds = _FundsData(asset_classes={"stockPosition": 1.0}, fail_sectors=True)  # sector_weightings fails, asset_classes succeeds
    xyz = _Ticker({"longName": "Some Equity ETF", "quoteType": "ETF"}, funds_data=funds)
    _patch(monkeypatch, {"XYZ": xyz})

    out = market.sectors(["XYZ"], cache_path=cache)
    assert out["XYZ"]["fund_sectors"] is None
    assert out["XYZ"]["fund_asset_classes"] == {"stockPosition": 1.0}
    # fund_fetched is recorded even though sector_weightings failed, so the entry is not retried
    # again today -- only after the 1-day (not 30-day) window for a null fund_sectors
    assert out["XYZ"]["fund_fetched"] == date.today().isoformat()


def test_sectors_refreshes_stale_fund_data_after_30_days(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    old_entry = {
        "sector": "ETF", "name": "Vanguard Total Stock Market ETF", "quote_type": "ETF",
        "category": None, "country": None, "summary": None, "website": None,
        "fund_sectors": {"technology": 0.20}, "fund_asset_classes": {"stockPosition": 0.99}, "fund_fetched": "2026-08-01",
    }
    cache.write_text(json.dumps({"VTI": old_entry}))
    fresh = _FundsData({"technology": 0.31, "healthcare": 0.10}, {"stockPosition": 0.99})
    vti = _Ticker({"longName": "Vanguard Total Stock Market ETF", "quoteType": "ETF"}, funds_data=fresh)
    _patch(monkeypatch, {"VTI": vti})

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 20)  # 80 days after 2026-08-01: past the 30-day window

    monkeypatch.setattr(market, "date", _FrozenDate)
    out = market.sectors(["VTI"], cache_path=cache)
    assert out["VTI"]["fund_sectors"] == {"technology": 0.31, "healthcare": 0.10}
    assert out["VTI"]["fund_fetched"] == "2026-10-20"
    assert vti.info_reads == 1  # the whole entry is refetched, not just the fund fields


def test_sectors_keeps_a_relabeled_etf_when_a_stale_refresh_retry_fails(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    # a symbol already correctly relabeled by an earlier fetch: cached as ETF with
    # real fund_sectors, 40 days old -- past the 30-day refresh window
    old_entry = {
        "sector": "ETF", "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "ETF",
        "category": "Some Category", "country": "United States", "summary": "A fund.", "website": "https://example.com",
        "fund_sectors": {"technology": 0.30, "financial_services": 0.70}, "fund_asset_classes": {"stockPosition": 0.99},
        "fund_fetched": "2026-08-05",  # 40 days before the frozen "today" below
    }
    cache.write_text(json.dumps({"SPYM": old_entry}))
    # Yahoo's own info still reports EQUITY (it never actually changes) and today's funds_data
    # retry fails outright -- a transient outage, not evidence the fund data was ever wrong
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData(fail_sectors=True, fail_classes=True),
    )
    _patch(monkeypatch, {"SPYM": spym})

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 14)  # 40 days after 2026-08-05: past the 30-day window

    monkeypatch.setattr(market, "date", _FrozenDate)
    out = market.sectors(["SPYM"], cache_path=cache)
    # kept, not demoted to a permanent sector-less EQUITY
    assert out["SPYM"]["quote_type"] == "ETF"
    assert out["SPYM"]["sector"] == "ETF"
    assert out["SPYM"]["fund_sectors"] == {"technology": 0.30, "financial_services": 0.70}
    assert out["SPYM"]["fund_asset_classes"] == {"stockPosition": 0.99}
    # only fund_fetched moves forward, so the 30-day cycle continues from today
    assert out["SPYM"]["fund_fetched"] == "2026-09-14"
    assert json.loads(cache.read_text())["SPYM"]["quote_type"] == "ETF"


def test_sectors_keeps_fresh_asset_classes_when_only_sectors_fails_on_a_stale_refresh(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    old_entry = {
        "sector": "ETF", "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "ETF",
        "category": "Some Category", "country": "United States", "summary": "A fund.", "website": "https://example.com",
        "fund_sectors": {"technology": 0.30, "financial_services": 0.70}, "fund_asset_classes": {"stockPosition": 0.90},
        "fund_fetched": "2026-08-05",  # 40 days before the frozen "today" below
    }
    cache.write_text(json.dumps({"SPYM": old_entry}))
    # sector_weightings fails again, but asset_classes succeeds this time with an updated value --
    # they are fetched independently, so today's real, fresh stockPosition must win over the
    # 40-day-old cached one, even though sector_weightings still failed
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData(asset_classes={"stockPosition": 0.97}, fail_sectors=True),
    )
    _patch(monkeypatch, {"SPYM": spym})

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 14)  # 40 days after 2026-08-05: past the 30-day window

    monkeypatch.setattr(market, "date", _FrozenDate)
    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["quote_type"] == "ETF"
    assert out["SPYM"]["fund_sectors"] == {"technology": 0.30, "financial_services": 0.70}  # kept from cache
    assert out["SPYM"]["fund_asset_classes"] == {"stockPosition": 0.97}  # the FRESH value, not 0.90
    assert out["SPYM"]["fund_fetched"] == "2026-09-14"


def test_sectors_keeps_cached_asset_classes_when_the_fresh_fetch_is_an_empty_dict(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    old_entry = {
        "sector": "ETF", "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "ETF",
        "category": "Some Category", "country": "United States", "summary": "A fund.", "website": "https://example.com",
        "fund_sectors": {"technology": 0.30, "financial_services": 0.70}, "fund_asset_classes": {"stockPosition": 0.90},
        "fund_fetched": "2026-08-05",  # 40 days before the frozen "today" below
    }
    cache.write_text(json.dumps({"SPYM": old_entry}))
    # today's asset_classes fetch "succeeds" but returns an empty dict -- not a real update, so
    # the cached stockPosition must be kept rather than being overwritten with nothing
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData(asset_classes={}, fail_sectors=True),
    )
    _patch(monkeypatch, {"SPYM": spym})

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 14)  # 40 days after 2026-08-05: past the 30-day window

    monkeypatch.setattr(market, "date", _FrozenDate)
    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["fund_asset_classes"] == {"stockPosition": 0.90}  # cached, not overwritten with {}


def test_sectors_null_fund_data_uses_a_one_day_not_thirty_day_retry_window(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    old_entry = {
        "sector": "ETF", "name": "XYZ Fund", "quote_type": "ETF",
        "category": None, "country": None, "summary": None, "website": None,
        "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": "2026-10-19",
    }
    cache.write_text(json.dumps({"XYZ": old_entry}))
    fresh = _FundsData({"technology": 1.0}, {"stockPosition": 1.0})
    xyz = _Ticker({"longName": "XYZ Fund", "quoteType": "ETF"}, funds_data=fresh)
    _patch(monkeypatch, {"XYZ": xyz})

    class _FrozenDateSameDay(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 19)  # same day as fund_fetched: well within the 30-day window
            # but the null-data entry would still be < 30 days old under the old rule -- the new
            # rule uses a 1-day window instead, so a stale-by-30-days check alone would wrongly
            # keep serving a null result for a month

    monkeypatch.setattr(market, "date", _FrozenDateSameDay)
    same_day = market.sectors(["XYZ"], cache_path=cache)
    assert same_day["XYZ"]["fund_sectors"] is None and xyz.info_reads == 0  # not yet stale (0 days old)

    class _FrozenDateOneDayLater(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 20)  # 1 day after fund_fetched: AT the 1-day retry threshold
            # (>=, not >) -- retried on this call, not only from the day after

    monkeypatch.setattr(market, "date", _FrozenDateOneDayLater)
    refreshed = market.sectors(["XYZ"], cache_path=cache)
    assert refreshed["XYZ"]["fund_sectors"] == {"technology": 1.0} and xyz.info_reads == 1


def test_sectors_refreshes_fund_entry_missing_fund_sectors_key(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    old_entry = {"sector": "ETF", "name": "VTI (before look-through)", "quote_type": "ETF", "category": None, "country": None, "summary": None, "website": None}
    cache.write_text(json.dumps({"VTI": old_entry}))
    vti = _Ticker({"longName": "Vanguard Total Stock Market ETF", "quoteType": "ETF"}, funds_data=_FundsData({"technology": 0.31}, {"stockPosition": 0.99}))
    _patch(monkeypatch, {"VTI": vti})

    out = market.sectors(["VTI"], cache_path=cache)
    assert out["VTI"]["fund_sectors"] == {"technology": 0.31}
    assert vti.info_reads == 1


def test_sectors_serves_fresh_fund_cache_without_refetching(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    entry = {
        "sector": "ETF", "name": "Vanguard Total Stock Market ETF", "quote_type": "ETF",
        "category": None, "country": None, "summary": None, "website": None,
        "fund_sectors": {"technology": 0.31}, "fund_asset_classes": {"stockPosition": 0.99}, "fund_fetched": date.today().isoformat(),
    }
    cache.write_text(json.dumps({"VTI": entry}))
    _patch(monkeypatch, {})  # no ticker registered: a refetch attempt would raise KeyError

    out = market.sectors(["VTI"], cache_path=cache)
    assert out["VTI"]["fund_sectors"] == {"technology": 0.31}


def test_sectors_stocks_get_null_fund_fields_without_attempting_funds_data(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    aapl = _Ticker({"sector": "Technology", "longName": "Apple Inc.", "quoteType": "EQUITY"})  # funds_data left unset (None)
    _patch(monkeypatch, {"AAPL": aapl})
    out = market.sectors(["AAPL"], cache_path=cache)
    assert out["AAPL"]["fund_sectors"] is None and out["AAPL"]["fund_asset_classes"] is None and out["AAPL"]["fund_fetched"] is None


def test_sectors_relabels_an_equity_mislabeled_fund_with_real_sector_weightings(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    # Yahoo's real-world bug: SPYM comes back quoteType EQUITY with no sector at all
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData({"technology": 0.30, "financial_services": 0.70}, {"stockPosition": 0.99}),
    )
    _patch(monkeypatch, {"SPYM": spym})
    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["quote_type"] == "ETF"  # corrected from Yahoo's wrong "EQUITY"
    assert out["SPYM"]["sector"] == "ETF"
    assert out["SPYM"]["fund_sectors"] == {"technology": 0.30, "financial_services": 0.70}
    assert out["SPYM"]["fund_asset_classes"] == {"stockPosition": 0.99}
    assert out["SPYM"]["fund_fetched"] == date.today().isoformat()


def test_sectors_leaves_a_mislabel_candidate_alone_when_funds_data_has_no_sectors(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    # Name matches the fund pattern too, but the retried funds_data fetch finds nothing real --
    # this is a genuine no-sector equity, not a mislabeled fund, so it must stay untouched
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData({}, None),
    )
    _patch(monkeypatch, {"SPYM": spym})
    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["quote_type"] == "EQUITY"
    assert out["SPYM"]["sector"] is None
    assert out["SPYM"]["fund_sectors"] is None
    assert out["SPYM"]["fund_asset_classes"] is None
    # fund_fetched IS recorded even though the retry found nothing -- the attempt happened, so
    # this exact cache entry is never re-tried as a mislabeled fund again (see the cache-hit tests
    # below); it would still refresh through the ordinary "category missing" rule some other way,
    # but never through the mislabel-candidate path a second time.
    assert out["SPYM"]["fund_fetched"] == date.today().isoformat()


def test_sectors_never_retries_a_stock_whose_name_does_not_look_like_a_fund(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    funds = _FundsData({"technology": 1.0}, {"stockPosition": 1.0})
    aaa = _Ticker({"longName": "Some Mystery Trust", "quoteType": "EQUITY"}, funds_data=funds)
    _patch(monkeypatch, {"AAA": aaa})
    out = market.sectors(["AAA"], cache_path=cache)
    assert out["AAA"]["quote_type"] == "EQUITY" and out["AAA"]["sector"] is None
    assert funds.sector_reads == 0  # the name doesn't match a fund pattern: never even attempted


def test_sectors_retries_a_cached_pre_mislabel_fix_equity_entry(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    # a cache entry written before this retry existed: EQUITY, no
    # sector, a fund-shaped name, and fund_fetched never set (the key wasn't even written yet)
    old_entry = {
        "sector": None, "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "EQUITY",
        "category": "Some Category", "country": "United States", "summary": "A fund.", "website": "https://example.com",
        "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None,
    }
    cache.write_text(json.dumps({"SPYM": old_entry}))
    spym = _Ticker(
        {"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"},
        funds_data=_FundsData({"technology": 0.30, "financial_services": 0.70}, {"stockPosition": 0.99}),
    )
    _patch(monkeypatch, {"SPYM": spym})

    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["quote_type"] == "ETF"
    assert out["SPYM"]["fund_sectors"] == {"technology": 0.30, "financial_services": 0.70}
    assert out["SPYM"]["fund_fetched"] == date.today().isoformat()
    assert spym.info_reads == 1  # the cache entry did not short-circuit the retry
    # the corrected entry is written back to the cache file too, not just returned
    assert json.loads(cache.read_text())["SPYM"]["quote_type"] == "ETF"


def test_sectors_does_not_retry_a_mislabel_candidate_once_fund_fetched_is_set(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "sector-cache.json"
    # the same shape as above, but fund_fetched is already set: the one retry already happened
    # (and found nothing), so this must be served straight from cache with no ticker read at all
    old_entry = {
        "sector": None, "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "EQUITY",
        "category": "Some Category", "country": "United States", "summary": "A fund.", "website": "https://example.com",
        "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": date.today().isoformat(),
    }
    cache.write_text(json.dumps({"SPYM": old_entry}))
    # A real, live ticker registered (not an empty registry): if sectors() wrongly attempted a
    # refetch here, the exception path would silently swallow a KeyError and fall back to
    # returning the cached values anyway, making the assertions below pass for the wrong reason.
    # Registering a real stub instead lets us assert directly that no read happened at all.
    funds = _FundsData({"technology": 1.0}, {"stockPosition": 1.0})
    spym = _Ticker({"longName": "State Street SPDR Portfolio S&P 500 ETF", "quoteType": "EQUITY"}, funds_data=funds)
    _patch(monkeypatch, {"SPYM": spym})

    out = market.sectors(["SPYM"], cache_path=cache)
    assert out["SPYM"]["quote_type"] == "EQUITY" and out["SPYM"]["fund_sectors"] is None
    assert spym.info_reads == 0  # no refetch of Yahoo info at all
    assert funds.sector_reads == 0 and funds.classes_reads == 0  # and no funds_data access either


# --- next_events -------------------------------------------------------------


def test_next_events_from_calendar_dict(monkeypatch) -> None:
    cal = {"Earnings Date": [date(2026, 10, 29), date(2026, 11, 2)], "Ex-Dividend Date": date(2026, 11, 7)}
    _patch(monkeypatch, {"AAPL": _Ticker(calendar=cal)})
    assert market.next_events("aapl") == {"next_earnings": "2026-10-29", "next_ex_dividend": "2026-11-07"}


def test_next_events_missing_or_broken_calendar(monkeypatch) -> None:
    class Broken:
        @property
        def calendar(self):
            raise RuntimeError("no calendar")

    _patch(monkeypatch, {"VTI": _Ticker(calendar={}), "BRK": Broken()})
    assert market.next_events("VTI") == {"next_earnings": None, "next_ex_dividend": None}
    assert market.next_events("BRK") == {"next_earnings": None, "next_ex_dividend": None}


def test_next_events_drops_dates_before_today(monkeypatch) -> None:
    # Yahoo's calendar reports the LAST ex-dividend date once it has passed; only future dates count.
    cal = {"Earnings Date": [date(2026, 7, 30), date(2026, 10, 29)], "Ex-Dividend Date": date(2026, 8, 9)}
    _patch(monkeypatch, {"AAPL": _Ticker(calendar=cal)})
    assert market.next_events("AAPL", today=date(2026, 9, 4)) == {"next_earnings": "2026-10-29", "next_ex_dividend": None}
    assert market.next_events("AAPL", today=date(2026, 8, 9))["next_ex_dividend"] == "2026-08-09"  # today still counts
