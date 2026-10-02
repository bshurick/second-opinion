"""Public-ETF proxies for holdings Yahoo cannot describe, and the cash-like symbol test.

Institutional 401(k) share classes (e.g. "VANG INST 500 IDX TR") have no Yahoo quote type,
sector data or price history. ``lookthrough_proxy_for`` matches such a holding's broker
description to the retail ETF that tracks the same index so a script can borrow that ETF's
data. ``is_cash_like`` names money-market funds and cash placeholders that trade at a flat
$1.00 and belong with cash rather than among priced positions.

``asset_bucket`` places a holding in one of the snapshot's buckets (bonds, us_equity,
intl_equity, cash, other) from its quote type, fund category, country and name, and
``tracking_reference`` names the index fund a bucket's tracking error is measured against.

The tables and ``asset_bucket`` here are copies of the ones in the portfolio-snapshot skill's
``summary.py``, which must stay a stdlib-only script and
so cannot import this module; ``tests/test_proxies.py`` asserts the copies stay equal.
"""

from __future__ import annotations

import re

LOOKTHROUGH_PROXIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"INST(ITUTIONAL)?\b.*500 (IDX|INDEX)", re.I), "VOO"),
    (re.compile(r"500 INDEX TR", re.I), "VOO"),
    (re.compile(r"S&P 500 (ETF|INDEX)|500 INDEX (ETF|TR|TRUST)|PORTFOLIO S&P 500", re.I), "VOO"),
    (re.compile(r"T(OTA)?L INTL STK|TOTAL INTERNATIONAL STOCK", re.I), "VXUS"),
    (re.compile(r"TOT(AL)? BD MKT|TOTAL BOND MARKET", re.I), "BND"),
    (re.compile(r"TOT(AL)? STK MKT|TOTAL STOCK MARKET", re.I), "VTI"),
]

_CASH_SYMBOLS = CASH_SYMBOLS = {"FCASH", "SPAXX", "FDRXX", "MVRXX", "CASH", "USD"}
_CASH_RE = CASH_RE = re.compile(
    r"money market|liquidity fund|cash reserves|government portfolio|treasury only|cash mgmt", re.I
)
_BOND_RE = re.compile(
    r"\bbond|fixed income|treasur|\bmuni|municipal|\btips\b|inflation.protected|high yield"
    r"|bank loan|\bcredit\b|\bbd (mkt|idx|index)|aggregate|core.plus|short.term (bd|bond)"
    r"|government bond|mortgage.backed",
    re.I,
)
_INTL_RE = re.compile(
    r"foreign|international|\bintl\b|emerging|developed markets|\bex.?us\b|\bworld\b"
    r"|\bglobal\b|europe|pacific|japan|china|india|latin|\beafe\b|all.world|total intl|tl intl",
    re.I,
)
_OTHER_RE = re.compile(
    r"commodit|gold|silver|precious|bitcoin|crypto|currency|real estate|\breit\b|alternative"
    r"|managed futures|volatility",
    re.I,
)
_US_EQUITY_RE = re.compile(
    r"s&p|\b500\b|russell|total stock|total market|nasdaq|\bdow\b|mid.?cap|small.?cap"
    r"|large.?cap|blend|growth|value|\bidx\b|index (tr|fund)|equity|stock",
    re.I,
)


def asset_bucket(symbol: str, info: dict | None) -> str | None:
    """Bucket a holding as bonds, us_equity, intl_equity, cash or other; None when nothing fits.

    Uses, in order, the Yahoo quote type, the fund category, the issuer country and the name (the
    broker's description when Yahoo has nothing, e.g. institutional 401(k) share classes).
    """
    info = info or {}
    sym = str(symbol or "").upper()
    qt = str(info.get("quote_type") or "").upper()
    cat = str(info.get("category") or "")
    name = str(info.get("name") or "")
    text = f"{cat} {name}"
    if qt == "MONEYMARKET" or sym in _CASH_SYMBOLS or _CASH_RE.search(text):
        return "cash"
    if qt == "EQUITY":
        country = str(info.get("country") or "")
        if country and country not in ("United States", "USA", "US"):
            return "intl_equity"
        if _OTHER_RE.search(name) and "REIT" in name.upper():
            return "other"
        return "us_equity"
    if _OTHER_RE.search(text) and not _BOND_RE.search(text):
        return "other"
    if _BOND_RE.search(text):
        return "bonds"
    if _INTL_RE.search(text):
        return "intl_equity"
    if qt in ("ETF", "MUTUALFUND") or _US_EQUITY_RE.search(text):
        return "us_equity"
    return None


TRACKING_REFERENCES = {"intl_equity": "VXUS", "bonds": "BND"}


def tracking_reference(bucket: str | None, benchmark: str) -> str | None:
    """The index fund a bucket's tracking error is measured against: the run's benchmark for US
    equity, VXUS for international equity, BND for bonds; None for cash, other and unbucketed."""
    if bucket == "us_equity":
        return benchmark
    return TRACKING_REFERENCES.get(bucket or "")


def lookthrough_proxy_for(name: str | None) -> str | None:
    """The proxy ETF for a holding's name (e.g. "VANG INST 500 IDX TR" -> "VOO"); None when nothing matches."""
    if not name:
        return None
    for pattern, proxy in LOOKTHROUGH_PROXIES:
        if pattern.search(name):
            return proxy
    return None


def is_cash_like(symbol: str | None, name: str | None = None) -> bool:
    """True for money-market funds and cash placeholders (by symbol or by name)."""
    sym = str(symbol or "").upper()
    return sym in CASH_SYMBOLS or bool(CASH_RE.search(str(name or "")))
