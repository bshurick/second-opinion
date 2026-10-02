from __future__ import annotations

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
    assert proxies.lookthrough_proxy_for("VANG INST 500 IDX TR") == "VOO"
    assert proxies.lookthrough_proxy_for("VG IS TOT BD MKT IDX") == "BND"
    assert proxies.lookthrough_proxy_for("VG IS TL INTL STK MK") == "VXUS"
    assert proxies.lookthrough_proxy_for("Fidelity 500 Index Fund") is None
    assert proxies.lookthrough_proxy_for(None) is None


def test_is_cash_like_by_symbol_or_name() -> None:
    assert proxies.is_cash_like("MVRXX")
    assert proxies.is_cash_like("SPAXX", "Fidelity Government Money Market Fund")
    assert proxies.is_cash_like("XYZ", "Some Cash Reserves Trust")
    assert not proxies.is_cash_like("BND", "Vanguard Total Bond Market ETF")
    assert not proxies.is_cash_like(None, None)


def test_asset_bucket_and_tracking_reference() -> None:
    assert proxies.asset_bucket("QBMZ", {"name": "VG IS TOT BD MKT IDX"}) == "bonds"
    assert proxies.asset_bucket("VEA", {"quote_type": "ETF", "category": "Foreign Large Blend"}) == "intl_equity"
    assert proxies.asset_bucket("PEP", {"quote_type": "EQUITY", "country": "United States"}) == "us_equity"
    assert proxies.asset_bucket("GLD", {"quote_type": "ETF", "category": "Commodities Focused", "name": "SPDR Gold Shares"}) == "other"
    assert proxies.tracking_reference("us_equity", "SPY") == "SPY"
    assert proxies.tracking_reference("bonds", "SPY") == "BND"
    assert proxies.tracking_reference("intl_equity", "SPY") == "VXUS"
    assert proxies.tracking_reference("other", "SPY") is None and proxies.tracking_reference(None, "SPY") is None
