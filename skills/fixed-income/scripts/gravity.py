#!/usr/bin/env python3
"""Usage: gravity.py [--tenor YEARS] [--proxy SYMBOL] — what a bond costs against what stocks cost.

A bond yielding ``y`` with no growth costs ``1/y`` per unit of coupon, which is a
P/E. That is the sense in which interest rates are the hurdle every other asset is
priced against. This script prints that figure beside an equity proxy's trailing
P/E, and the gap between the two earnings yields.

Reads nothing from stdin. Exit codes follow the plugin convention (0 ok, 2 invalid
input, 5 on an upstream API error or any other uncaught exception, 6 if yfinance is
not installed). Exit 4 is unreachable from here: the only ConfigError raise sites are
config.py's SnapTrade and E*Trade credential loaders, which this script never calls,
and FRED's CSV endpoint is keyless.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
# The plugin's shared package lives in lib/ at the plugin root.
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

# The tenors rates.py maps in its own PAR_SERIES table. Duplicated rather than imported:
# the fixed-income scripts do not import each other, and importing rates.py to read a constant would also drag
# in its FRED calls at import time.
TENOR_SERIES: dict[float, str] = {
    0.0833: "DGS1MO",
    0.25: "DGS3MO",
    0.5: "DGS6MO",
    1.0: "DGS1",
    2.0: "DGS2",
    3.0: "DGS3",
    5.0: "DGS5",
    7.0: "DGS7",
    10.0: "DGS10",
    20.0: "DGS20",
    30.0: "DGS30",
}


ARITHMETIC_MEANING = (
    "A bond yielding y with no growth costs 1/y per unit of coupon, which is a price-earnings "
    "ratio: at 5% a bond costs 20 times its coupon, at 4% it costs 25 times. That identity holds "
    "because a bond's price and its coupon are both observable, so it is arithmetic rather than "
    "a forecast. It is the sense in which a risk-free yield is the hurdle every other asset is "
    "priced against."
)

NOT_RANKED_BECAUSE = (
    "The equity earnings yield is reported for today only and is deliberately not ranked against "
    "history. Today's figure is derived from the proxy's own holdings, while the long history "
    "available for S&P earnings is as-reported index earnings, and the two measure different "
    "things. A percentile computed across that boundary would look precise and would not be, so "
    "none is given. The Treasury side is ranked, because its history comes from the same series "
    "as today's figure."
)

IMPLIED_PE_PERCENTILE_NOTE = (
    "This percentile is approximately the yield's percentile inverted, because 100/y is a "
    "monotone decreasing transform: a lower yield percentile is a higher implied-P/E percentile. "
    "The two are exact complements whenever no history value ties today's yield and every "
    "history value is strictly positive. Percentiles here count values strictly below, so a tie "
    "is counted on neither side, and non-positive yields are excluded from the P/E side but kept "
    "on the yield side, so the two percentiles can be computed over different denominators."
)

# No {proxy} slot. If this sentence interpolated the symbol, `--proxy sell-stocks`
# (11 characters, a shape _PROXY_RE accepts) would put an imperative inside a
# pinned disclosure at exit 0, the one place a reader trusts most. The symbol is already
# reported in its own field, equity.proxy, so the disclosure can name that field and stay
# fixed. A constant with no slot cannot carry anyone's text.
UNAVAILABLE_BECAUSE = (
    "the data source reported no usable trailing P/E for the symbol in this block's proxy "
    "field, so its earnings yield is not computed. It is reported as null rather than zero, "
    "because a zero P/E would render as an infinite earnings yield and a gap that looks like "
    "a signal. A fund that tracks the index, such as SPY or VOO, commonly carries a trailing "
    "P/E; an index symbol, such as ^GSPC, commonly does not."
)

# ONE RULE: a message this script emits never quotes back what the reader typed.
#
# Validating --proxy's shape alone relocates an injected sentence from exit 0 to
# exit 2 rather than removing it -- and a 12-character [A-Z0-9.^-] budget still spells
# SELL-STOCKS. Three routes existed at once (--tenor's raw value, an
# unrecognised argument, and the rejected --proxy value), which is the tell that per-flag
# validators are the wrong remedy: the next flag would need its own, and the one after that.
# Name the field, state the shape it wants, and report the value's LENGTH in place of the
# value. A count of characters cannot be read as a call to act.
_VALUE_NOT_ECHOED = (
    "It is not repeated back here, because a message this script emits is never a place to "
    "carry words of someone else's choosing; it was {length} long."
)

ERR_TENOR_MISSING_VALUE = "--tenor needs a value in years"
ERR_TENOR_NOT_A_NUMBER = (
    "--tenor must be a number in years, such as 10 or 0.25, and what was given is not one. "
) + _VALUE_NOT_ECHOED
# {tenor:g} is the one runtime value still emitted, and it is not the reader's text: float()
# has already rejected everything that is not a number, and :g renders a canonical short form
# of the parsed value rather than the bytes typed. It cannot carry prose.
ERR_TENOR_NO_SERIES = "no Treasury series for a tenor of {tenor:g} years: {choices}"
ERR_PROXY_MISSING_VALUE = "--proxy needs a symbol"
ERR_PROXY_INVALID_SHAPE = (
    "--proxy must look like a ticker symbol (letters, digits, '.', '^', or '-', 1-12 "
    "characters), and what was given is not one. "
) + _VALUE_NOT_ECHOED
ERR_UNRECOGNISED_ARGUMENT = (
    "unrecognised argument: this script accepts --tenor and --proxy only. "
) + _VALUE_NOT_ECHOED

# \A and \Z, not ^ and $: Python's $ also matches immediately before a trailing newline, so
# `--proxy $'spy\n'` was accepted and the newline reached the payload. The test file already
# says the same of _ISO_DATE.
_PROXY_RE = re.compile(r"\A[A-Z0-9.^-]{1,12}\Z")

FED_MODEL_CAVEAT = (
    "Setting a nominal bond yield beside an equity earnings yield is the comparison usually "
    "called the Fed Model, and it is contested. The bond yield is nominal while corporate "
    "earnings tend to grow with inflation, so the two are not measured on the same footing; "
    "Asness (2003), Fight the Fed Model, is the standard critique, and the comparison's record "
    "as a predictor of returns is weak. The arithmetic above holds regardless: what is contested "
    "is reading a gap between the two as a signal about what to own. Nothing here is a fair "
    "value, a target, or a view on whether either asset is cheap or expensive."
)


ERR_YIELD_NOT_POSITIVE = "yield must be positive to have an implied P/E, got {yield_pct:g}"
ERR_PE_NOT_POSITIVE = "P/E must be positive to have an earnings yield, got {trailing_pe:g}"
ERR_EMPTY_HISTORY = "empty history"


def implied_pe(yield_pct: float) -> float:
    """What a bond costs per unit of coupon, at zero growth: ``100 / yield_pct``.

    Reachable in production, not just by construction: DGS1MO (a tenor this script offers)
    printed 0.00 on FRED on real days in 2020-21, and this is called from build() with the raw
    fetched value, so ``--tenor 0.0833`` can take this path with no malformed input at all.
    """
    if yield_pct <= 0:
        raise ValueError(ERR_YIELD_NOT_POSITIVE.format(yield_pct=yield_pct))
    return 100.0 / yield_pct


def earnings_yield_pct(trailing_pe: float) -> float:
    """The reciprocal of a P/E, as a percentage.

    Unlike implied_pe's, this guard is unreachable through main(): build() only calls this
    inside its ``equity_pe is None or equity_pe <= 0`` else-branch, so a non-positive P/E
    takes the null path instead. Pinned anyway, like percentile_of's, so the message cannot
    grow prose if a future caller does reach it.
    """
    if trailing_pe <= 0:
        raise ValueError(ERR_PE_NOT_POSITIVE.format(trailing_pe=trailing_pe))
    return 100.0 / trailing_pe


def percentile_of(value: float, history: list[dict[str, Any]]) -> float:
    """Share of ``history`` strictly below ``value``, as a percentage.

    The same definition rates.py uses, duplicated for the reason TENOR_SERIES is. The empty-
    history guard is unreachable through this module's only caller, _ranked, which raises
    IndexError computing the median first -- left as-is; not an emission site.
    """
    values = [row["value"] for row in history]
    if not values:
        raise ValueError(ERR_EMPTY_HISTORY)
    return 100.0 * sum(1 for v in values if v < value) / len(values)


def _ranked(value: float, history: list[dict[str, Any]]) -> dict[str, Any]:
    """One percentile block, shaped like rates.py's."""
    values = sorted(row["value"] for row in history)
    midpoint = len(values) // 2
    median = (
        values[midpoint] if len(values) % 2 else (values[midpoint - 1] + values[midpoint]) / 2.0
    )
    return {
        "value": round(value, 4),
        "percentile": round(percentile_of(value, history), 1),
        "median": round(median, 4),
        "history_from": history[0]["date"],
        "observations": len(values),
    }


def _length(value: str) -> str:
    """How long the value was, and nothing of what it said. See _VALUE_NOT_ECHOED."""
    count = len(value)
    return "1 character" if count == 1 else f"{count} characters"


def read_args(argv: list[str]) -> tuple[float, str]:
    """``--tenor YEARS`` and ``--proxy SYMBOL``, both optional."""
    tenor, proxy = 10.0, "SPY"
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag == "--tenor":
            if not rest:
                raise InvalidInput(ERR_TENOR_MISSING_VALUE)
            raw = rest.pop(0)
            try:
                tenor = float(raw)
            except ValueError as exc:
                raise InvalidInput(ERR_TENOR_NOT_A_NUMBER.format(length=_length(raw))) from exc
            if tenor not in TENOR_SERIES:
                raise InvalidInput(
                    ERR_TENOR_NO_SERIES.format(
                        tenor=tenor,
                        choices=", ".join(f"{t:g}" for t in sorted(TENOR_SERIES)),
                    )
                )
        elif flag == "--proxy":
            if not rest:
                raise InvalidInput(ERR_PROXY_MISSING_VALUE)
            candidate = rest.pop(0)
            if not _PROXY_RE.match(candidate.upper()):
                raise InvalidInput(ERR_PROXY_INVALID_SHAPE.format(length=_length(candidate)))
            proxy = candidate.upper()
        else:
            raise InvalidInput(ERR_UNRECOGNISED_ARGUMENT.format(length=_length(flag)))
    return tenor, proxy


def build(
    tenor_years: float,
    proxy: str,
    treasury: dict[str, Any],
    history: list[dict[str, Any]],
    equity_pe: float | None,
) -> dict[str, Any]:
    """The whole payload from already-fetched values, so every figure is testable offline."""
    yield_pct = treasury["value"]
    pe = implied_pe(yield_pct)

    if equity_pe is None or equity_pe <= 0:
        equity: dict[str, Any] = {
            "proxy": proxy,
            "trailing_pe": None,
            "earnings_yield_pct": None,
            "percentile": None,
            "not_ranked_because": NOT_RANKED_BECAUSE,
            "unavailable_because": UNAVAILABLE_BECAUSE,
        }
        gap: dict[str, Any] = {"equity_earnings_yield_minus_treasury_pp": None, "percentile": None}
    else:
        ey = earnings_yield_pct(equity_pe)
        equity = {
            "proxy": proxy,
            "trailing_pe": round(equity_pe, 4),
            "earnings_yield_pct": round(ey, 4),
            "percentile": None,
            "not_ranked_because": NOT_RANKED_BECAUSE,
        }
        gap = {
            "equity_earnings_yield_minus_treasury_pp": round(ey - yield_pct, 4),
            "percentile": None,
        }

    return {
        "as_of": {"treasury": treasury["date"], "equity": None},
        "treasury": {
            "tenor_years": tenor_years,
            "series_id": TENOR_SERIES[tenor_years],
            "yield_pct": round(yield_pct, 4),
            "implied_pe": round(pe, 4),
            "percentiles": {
                "yield_pct": _ranked(yield_pct, history),
                "implied_pe": {
                    **_ranked(
                        pe,
                        [
                            {"value": implied_pe(r["value"]), "date": r["date"]}
                            for r in history
                            if r["value"] > 0
                        ],
                    ),
                    "note": IMPLIED_PE_PERCENTILE_NOTE,
                },
            },
        },
        "equity": equity,
        "gap": gap,
        "assumptions": {
            "arithmetic": ARITHMETIC_MEANING,
            "fed_model_caveat": FED_MODEL_CAVEAT,
        },
    }


def main(argv: list[str]) -> dict[str, Any]:
    """Fetch both sides and build the payload."""
    tenor, proxy = read_args(argv)
    from second_opinion import (  # noqa: PLC0415 — lazy, so --tenor errors need no network
        fred,
        market,
    )

    series = TENOR_SERIES[tenor]
    treasury = fred.latest(series)
    history = fred.observations(series, 100_000)
    # company_info, not quote: quote() carries price fields only and no P/E. Read ONE key off
    # it -- company_info also returns a field literally called "recommendation" (yfinance's
    # analyst call, values like "buy"), which this skill may never emit. Nothing here passes
    # that dict through; only pe_ratio is taken, by name.
    equity_pe = market.company_info(proxy).get("pe_ratio")
    result = build(tenor, proxy, treasury, history, equity_pe)
    result["as_of"]["equity"] = date.today().isoformat()
    return result


if __name__ == "__main__":
    raise SystemExit(output.run(main))
