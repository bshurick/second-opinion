from __future__ import annotations

import pytest

import inspect

from scripts_util import load_script

from second_opinion import proxies


def test_proxy_and_cash_tables_match_the_snapshot_summary_script() -> None:
    summary = load_script("portfolio-snapshot/scripts/summary.py")
    assert [(p.pattern, p.flags, proxy) for p, proxy in proxies.LOOKTHROUGH_PROXIES] == [
        (p.pattern, p.flags, proxy) for p, proxy in summary.LOOKTHROUGH_PROXIES
    ]
    assert proxies.CASH_SYMBOLS == summary._CASH_SYMBOLS  # noqa: SLF001
    assert (proxies.CASH_RE.pattern, proxies.CASH_RE.flags) == (summary._CASH_RE.pattern, summary._CASH_RE.flags)  # noqa: SLF001
    for name in ("_BOND_RE", "_INTL_RE", "_OTHER_RE", "_US_EQUITY_RE"):
        assert (getattr(proxies, name).pattern, getattr(proxies, name).flags) == (getattr(summary, name).pattern, getattr(summary, name).flags)
    assert inspect.getsource(proxies.asset_bucket) == inspect.getsource(summary.asset_bucket)


def test_lookthrough_proxy_for_matches_institutional_names() -> None:
    assert proxies.lookthrough_proxy_for("ACME INST 500 IDX TR") == "VOO"
    assert proxies.lookthrough_proxy_for("ACME TOT BD MKT IDX") == "BND"
    assert proxies.lookthrough_proxy_for("ACME TL INTL STK MK") == "VXUS"
    assert proxies.lookthrough_proxy_for(None) is None


@pytest.mark.parametrize("name, proxy", [
    ("Fidelity 500 Index Fund", "VOO"),
    ("STATE ST S&P 500 INDEX FD", "VOO"),
    ("BLK EQUITY INDEX S&P 500 FUND", "VOO"),
    ("ACME 500 IDX CL R", "VOO"),
    ("Schwab US Aggregate Bond Index", "BND"),
    ("ACME BOND IDX", "BND"),
    ("ACME US BD IDX", "BND"),
    ("ACME INTL EQUITY INDEX", "VXUS"),
    ("ACME INTERNATIONAL STOCK IDX", "VXUS"),
    ("ACME TOTAL MARKET INDEX", "VTI"),
    ("ACME TOT US STK MKT", "VTI"),
])
def test_lookthrough_proxy_for_reads_the_index_from_any_provider(name, proxy) -> None:
    assert proxies.lookthrough_proxy_for(name) == proxy


@pytest.mark.parametrize("name", [
    "ACME RUSSELL 2500 INDEX",      # not the 500
    "ACME INTL BOND INDEX",         # neither a US bond fund nor a stock fund
    "ACME TARGET DATE 2045",
    "PLAN STABLE VALUE",
    "S&P GLOBAL INC",               # a company, not an index fund
])
def test_lookthrough_proxy_for_leaves_other_funds_unmatched(name) -> None:
    assert proxies.lookthrough_proxy_for(name) is None


def test_is_cash_like_by_symbol_or_name() -> None:
    assert proxies.is_cash_like("MVRXX")
    assert proxies.is_cash_like("SPAXX", "Fidelity Government Money Market Fund")
    assert proxies.is_cash_like("XYZ", "Some Cash Reserves Trust")
    assert not proxies.is_cash_like("BND", "Vanguard Total Bond Market ETF")
    assert not proxies.is_cash_like(None, None)


def test_asset_bucket_and_tracking_reference() -> None:
    assert proxies.asset_bucket("QBMZ", {"name": "ACME TOT BD MKT IDX"}) == "bonds"
    assert proxies.asset_bucket("VEA", {"quote_type": "ETF", "category": "Foreign Large Blend"}) == "intl_equity"
    assert proxies.asset_bucket("PEP", {"quote_type": "EQUITY", "country": "United States"}) == "us_equity"
    assert proxies.asset_bucket("GLD", {"quote_type": "ETF", "category": "Commodities Focused", "name": "SPDR Gold Shares"}) == "other"
    assert proxies.tracking_reference("us_equity", "SPY") == "SPY"
    assert proxies.tracking_reference("bonds", "SPY") == "BND"
    assert proxies.tracking_reference("intl_equity", "SPY") == "VXUS"
    assert proxies.tracking_reference("other", "SPY") is None and proxies.tracking_reference(None, "SPY") is None
