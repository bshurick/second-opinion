"""Portfolio risk and stress testing: volatility, beta, correlation, drawdown,
value at risk, tracking error, risk contributions, concentration, scenario
replays or beta-scaled shocks, and what-if shocks per position.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python risk.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "positions": [{"symbol": "AAPL", "value": 5000} |
                    {"symbol": "AAPL", "units": 50, "price": 100.0}, ...],
      "cash": 0,
      "prices": {"AAPL": [{"date": "YYYY-MM-DD", "close": 100.0, "adj_close": 99.0}, ...]},
                                            # daily; adj_close preferred when present
      "benchmark": {"symbol": "SPY", "prices": [...]},      # optional
      "scenarios": [{"name": "2020 COVID crash", "start": "2020-02-19", "end": "2020-03-23",
                     "benchmark_return": -0.339}, ...],    # each symbol replays when its own
                                            # history covers start..end, else beta x
                                            # benchmark_return
      "shocks": {"AAPL": -0.3},             # what-if returns per symbol
      "risk_free": 0.0,                     # annual, for Sharpe and Sortino
      "factors": {"IJR": [{"date", "close"}, ...]}  # optional, same shape as
                                            # prices; per-factor beta/R^2 on
                                            # the portfolio (additive; absent
                                            # -> no "factors" key at all)
      "tracking_references": {"BSBIX": "BND"},  # optional: per-position reference
                                            # for tracking error (a symbol with no
                                            # entry gets null); absent -> every
                                            # position tracks the benchmark
      "reference_prices": {"BND": [...]}    # optional, same shape as prices; a
                                            # reference may also be a held symbol
                                            # or the benchmark
    }

Output JSON contract (stdout)::

    {
      "portfolio": {total_value, cash_weight, coverage, observations, start, end,
                    volatility, beta, correlation_to_benchmark, tracking_error, sharpe,
                    max_drawdown, var_95, cvar_95, parametric_var_95, var_99,
                    diversification_ratio, avg_pairwise_correlation,
                    upside_capture, downside_capture, sortino, crisis_correlation},
      "positions": [{symbol, value, weight, observations, volatility, beta,
                     correlation_to_benchmark, tracking_error, tracking_benchmark,
                     sharpe, max_drawdown, var_95, cvar_95, upside_capture,
                     downside_capture, sortino, crisis_correlation}],
                                            # tracking_error is against
                                            # tracking_benchmark (the position's
                                            # reference, else the benchmark)
      "risk_contributions": [{symbol, weight, contribution, share}],
      "correlation": {symbols, matrix} | {pairs: [...]}   # matrix up to 15 symbols
      "concentration": {hhi, hhi_interpretation, top_5_concentration, largest_position,
                        position_count},
      "scenarios": [{name, mode: "replay"|"mixed"|"beta_scaled"|"skipped", start, end,
                     benchmark_return, positions: {symbol: return}, portfolio_return,
                     portfolio_loss, note, replayed: [symbols], beta_scaled: [symbols]}],
                                            # per symbol: replay from its own prices when its
                                            # history spans start..end, else beta x benchmark
      "what_if": {shocks, positions: {symbol: loss}, portfolio_return, portfolio_loss} | null,
      "missing_prices": [...], "flags": [{code, message}],
                                   # HIGH_BETA, HIGH_CORRELATION, CONCENTRATED,
                                   # SHORT_HISTORY, MISSING_PRICES
      "factors": {name: {beta, explained_variance}},        # only when input had factors
      "factors_total_explained_variance": 0.0                # sum over valid factors
    }

Method: simple daily returns aligned on the dates every covered symbol (and
the benchmark) share. Volatility, beta, correlation and tracking error use
sample statistics annualized with sqrt(252). Portfolio returns assume the
current weights held constant (weights over total value; cash earns 0).
Historical VaR is the nearest-rank 5th (1st) percentile of daily returns,
CVaR the mean beyond it, parametric VaR 1.645 x daily standard deviation.
Max drawdown is peak-to-trough of the cumulative return path. Risk
contribution_i = w_i (Sigma w)_i / (w' Sigma w). Diversification ratio =
weighted average volatility / portfolio volatility over covered positions.
Scenario replay uses each symbol's own price on or before start and end,
symbol by symbol: a position whose history spans the window is replayed
and every other covered position is beta-scaled against the benchmark's
own replayed return (or the scenario's given return when the benchmark
does not span the window), so the mode is "replay", "mixed" or
"beta_scaled" by how many replayed; the two symbol lists say which.
Upside/downside capture is the mean return on benchmark-up (down) days
divided by the benchmark's mean on those same days (>=20 such days
required, else null). Sortino is the mean daily excess return over
risk_free/252 divided by the downside deviation (root-mean-square of
negative returns only), annualized by sqrt(252) (null under 30
observations or with no negative days). Crisis correlation recomputes the
correlation to the benchmark on only the worst-quintile benchmark days
(bottom 20% of benchmark returns in the sample; >=25 such days required,
else null). Factor betas are single-factor regressions of the portfolio's
return series on each factor's own return series (same null convention as
beta: null when fewer than 3 aligned observations or the factor has no
variance); explained_variance is r^2. factors_total_explained_variance is
the plain sum of each factor's own (independent) r^2, not a joint
multi-factor R^2 -- it can exceed 1 when the factors are correlated with
each other, since their individual explained-variance shares then overlap.
Ratios 4 dp, money 2 dp. Past drawdowns and simulated shocks are not
forecasts.
"""

from __future__ import annotations

import json
import math
import sys
from bisect import bisect_right
from statistics import mean, stdev

_TRADING_DAYS = 252
_Z95 = 1.645
_HHI_MODERATE_MAX = 0.18


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


class _Series:
    def __init__(self, rows: object) -> None:
        if not isinstance(rows, list):
            raise ValueError("each price series must be a list")
        clean = []
        for r in rows:
            if isinstance(r, dict) and r.get("date") and r.get("close") is not None:
                c = _num(r["close"], "close")
                a = _num(r.get("adj_close"), "adj_close")
                clean.append((str(r["date"])[:10], a if a is not None else c))
        clean.sort()
        self.dates = [d for d, _ in clean]
        self.values = [v for _, v in clean]
        self.returns: dict[str, float] = {}
        for (d0, v0), (d1, v1) in zip(clean, clean[1:], strict=False):
            if v0 > 0:
                self.returns[d1] = v1 / v0 - 1

    def on(self, d: str) -> float | None:
        i = bisect_right(self.dates, d) - 1
        return self.values[i] if i >= 0 else None

    @property
    def empty(self) -> bool:
        return len(self.dates) < 2


def _cov(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (len(x) - 1)


def _percentile_var(rets: list[float], q: float) -> tuple[float, float]:
    s = sorted(rets)
    idx = min(int(q * len(s)), len(s) - 1)
    var = -s[idx]
    tail = s[: idx + 1]
    return var, -mean(tail) if tail else var


def _max_drawdown(rets: list[float]) -> float:
    peak, value, mdd = 1.0, 1.0, 0.0
    for r in rets:
        value *= 1 + r
        peak = max(peak, value)
        mdd = max(mdd, 1 - value / peak)
    return mdd


_STATS_KEYS = (
    "volatility",
    "beta",
    "correlation_to_benchmark",
    "tracking_error",
    "sharpe",
    "max_drawdown",
    "var_95",
    "cvar_95",
    "upside_capture",
    "downside_capture",
    "sortino",
    "crisis_correlation",
)

_MIN_CAPTURE_DAYS = 20
_MIN_CRISIS_DAYS = 25
_MIN_SORTINO_OBS = 30
_QUINTILE = 0.2


def _capture_ratio(rets: list[float], bench: list[float], idx: list[int]) -> float | None:
    if len(idx) < _MIN_CAPTURE_DAYS:
        return None
    bench_mean = mean(bench[i] for i in idx)
    if bench_mean == 0:
        return None
    return mean(rets[i] for i in idx) / bench_mean


def _sortino(rets: list[float], rf_daily: float) -> float | None:
    n = len(rets)
    neg = [r for r in rets if r < 0]
    if n < _MIN_SORTINO_OBS or not neg:
        return None
    downside_dev = math.sqrt(mean(r * r for r in neg))
    if downside_dev <= 0:
        return None
    return (mean(rets) - rf_daily) / downside_dev * math.sqrt(_TRADING_DAYS)


def _crisis_correlation(rets: list[float], bench: list[float]) -> float | None:
    n = len(rets)
    q = int(n * _QUINTILE)
    if q < _MIN_CRISIS_DAYS:
        return None
    order = sorted(range(n), key=lambda i: bench[i])[:q]
    rs = [rets[i] for i in order]
    bs = [bench[i] for i in order]
    sd_r, sd_b = stdev(rs), stdev(bs)
    if sd_r <= 0 or sd_b <= 0:
        return None
    return _cov(rs, bs) / (sd_r * sd_b)


def _stats(rets: list[float], bench: list[float] | None, rf_daily: float) -> dict:
    n = len(rets)
    if n < 3:
        return dict.fromkeys(_STATS_KEYS)
    sd = stdev(rets)
    vol = sd * math.sqrt(_TRADING_DAYS)
    beta = corr = te = upside_capture = downside_capture = crisis_correlation = None
    if bench is not None and len(bench) == n and stdev(bench) > 0:
        cov = _cov(rets, bench)
        vb = stdev(bench) ** 2
        beta = cov / vb
        corr = cov / (sd * stdev(bench)) if sd > 0 else None
        te = stdev([a - b for a, b in zip(rets, bench, strict=True)]) * math.sqrt(_TRADING_DAYS)
        up_idx = [i for i in range(n) if bench[i] > 0]
        down_idx = [i for i in range(n) if bench[i] < 0]
        upside_capture = _capture_ratio(rets, bench, up_idx)
        downside_capture = _capture_ratio(rets, bench, down_idx)
        crisis_correlation = _crisis_correlation(rets, bench)
    var95, cvar95 = _percentile_var(rets, 0.05)
    return {
        "volatility": _r4(vol),
        "beta": _r4(beta),
        "correlation_to_benchmark": _r4(corr),
        "tracking_error": _r4(te),
        "sharpe": _r4((mean(rets) - rf_daily) / sd * math.sqrt(_TRADING_DAYS)) if sd > 0 else None,
        "max_drawdown": _r4(_max_drawdown(rets)),
        "var_95": _r4(var95),
        "cvar_95": _r4(cvar95),
        "upside_capture": _r4(upside_capture),
        "downside_capture": _r4(downside_capture),
        "sortino": _r4(_sortino(rets, rf_daily)),
        "crisis_correlation": _r4(crisis_correlation),
    }


def run_risk(params: dict) -> dict:
    """Compute the risk view for ``params``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    raw_positions = params.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise ValueError("at least one position is required")
    if not isinstance(params.get("prices", {}), dict):
        raise ValueError("prices must be an object keyed by symbol")
    if "factors" in params and not isinstance(params.get("factors"), dict):
        raise ValueError("factors must be an object keyed by name")
    positions: dict[str, float] = {}
    for p in raw_positions:
        if not isinstance(p, dict) or not p.get("symbol"):
            raise ValueError("each position requires symbol and value (or units and price)")
        sym = str(p["symbol"]).upper()
        value = _num(p.get("value"), "value")
        if value is None:
            units, price = _num(p.get("units"), "units"), _num(p.get("price"), "price")
            if units is None or price is None:
                raise ValueError("each position requires symbol and value (or units and price)")
            value = units * price
        positions[sym] = positions.get(sym, 0.0) + value
    cash = _num(params.get("cash"), "cash") or 0.0
    total = sum(positions.values()) + cash
    if total <= 0:
        raise ValueError("portfolio has no value")
    weights = {s: v / total for s, v in positions.items()}
    rf_daily = (_num(params.get("risk_free"), "risk_free") or 0.0) / _TRADING_DAYS

    series = {str(k).upper(): _Series(v) for k, v in (params.get("prices") or {}).items()}
    series = {k: s for k, s in series.items() if not s.empty}
    bench_in = params.get("benchmark") if isinstance(params.get("benchmark"), dict) else None
    bench = _Series(bench_in.get("prices") or []) if bench_in else None
    bench = None if bench is None or bench.empty else bench
    bench_symbol = str(bench_in.get("symbol")).upper() if bench_in and bench else None

    covered = [s for s in positions if s in series]
    missing = sorted(s for s in positions if s not in series)
    common: set[str] | None = None
    for s in covered:
        common = set(series[s].returns) if common is None else common & set(series[s].returns)
    if bench is not None and common is not None:
        common &= set(bench.returns)
    dates = sorted(common) if common else []
    aligned = {s: [series[s].returns[d] for d in dates] for s in covered}
    bench_rets = [bench.returns[d] for d in dates] if bench is not None and dates else None
    n = len(dates)

    # --- per-position ---------------------------------------------------------------------
    position_rows = []
    for s, value in sorted(positions.items()):
        st = (
            _stats(aligned[s], bench_rets, rf_daily)
            if s in aligned and n >= 3
            else _stats([], None, rf_daily)
        )
        position_rows.append(
            {
                "symbol": s,
                "value": _r2(value),
                "weight": _r4(weights[s]),
                "observations": n if s in aligned else 0,
                **st,
            }
        )
    # Tracking error per position against its own reference (e.g. a bond fund against BND)
    # when ``tracking_references`` is given; otherwise every covered position tracks the benchmark.
    refs_in = params.get("tracking_references")
    if refs_in is not None and not isinstance(refs_in, dict):
        raise ValueError("tracking_references must be an object keyed by symbol")
    ref_prices_in = params.get("reference_prices") or {}
    if not isinstance(ref_prices_in, dict):
        raise ValueError("reference_prices must be an object keyed by symbol")
    if refs_in is None:
        for row in position_rows:
            row["tracking_benchmark"] = bench_symbol if row["tracking_error"] is not None else None
    else:
        ref_series: dict[str, _Series] = {}
        for sym, rows in ref_prices_in.items():
            ser = _Series(rows)
            if not ser.empty:
                ref_series[str(sym).upper()] = ser
        for sym, ser in series.items():
            ref_series.setdefault(sym, ser)
        if bench is not None and bench_symbol:
            ref_series.setdefault(bench_symbol, bench)
        for row in position_rows:
            sym = row["symbol"]
            ref = refs_in.get(sym)
            ref = str(ref).upper() if isinstance(ref, str) and ref.strip() else None
            te = None
            if ref and ref in ref_series and sym in series:
                own, other = series[sym].returns, ref_series[ref].returns
                shared = [d for d in dates if d in own and d in other]
                if len(shared) >= 3:
                    diffs = [own[d] - other[d] for d in shared]
                    te = stdev(diffs) * math.sqrt(_TRADING_DAYS)
            row["tracking_error"] = _r4(te)
            row["tracking_benchmark"] = ref if te is not None else None
    by_symbol = {r["symbol"]: r for r in position_rows}

    # --- portfolio -------------------------------------------------------------------------
    port_rets = [sum(weights[s] * aligned[s][i] for s in covered) for i in range(n)] if n else []
    pstats = _stats(port_rets, bench_rets, rf_daily) if n >= 3 else _stats([], None, rf_daily)

    # --- factor betas (optional, additive; absent input -> no "factors" key) ----------------
    factors_out = None
    factors_total_ev = None
    factors_in = params.get("factors")
    if isinstance(factors_in, dict) and factors_in:
        port_by_date = dict(zip(dates, port_rets, strict=True)) if dates else {}
        factors_out = {}
        evs = []
        for name, rows in factors_in.items():
            fseries = _Series(rows)
            common_f = sorted(set(port_by_date) & set(fseries.returns))
            beta = ev = None
            if len(common_f) >= 3:
                pr = [port_by_date[d] for d in common_f]
                fr = [fseries.returns[d] for d in common_f]
                sd_p, sd_f = stdev(pr), stdev(fr)
                if sd_p > 0 and sd_f > 0:
                    fcov = _cov(pr, fr)
                    beta = fcov / (sd_f**2)
                    ev = (fcov / (sd_p * sd_f)) ** 2
            factors_out[str(name)] = {"beta": _r4(beta), "explained_variance": _r4(ev)}
            if ev is not None:
                evs.append(ev)
        factors_total_ev = _r4(sum(evs)) if evs else None

    covered_value = sum(positions[s] for s in covered)
    contributions = []
    div_ratio = avg_corr = None
    corr_out: dict = {"symbols": [], "matrix": []}
    if n >= 3 and covered:
        sds = {s: stdev(aligned[s]) for s in covered}
        cov = {(a, b): _cov(aligned[a], aligned[b]) for a in covered for b in covered}
        port_var = sum(weights[a] * weights[b] * cov[(a, b)] for a in covered for b in covered)
        for s in sorted(covered):
            c = weights[s] * sum(cov[(s, b)] * weights[b] for b in covered)
            contributions.append(
                {
                    "symbol": s,
                    "weight": _r4(weights[s]),
                    "contribution": _r4(c * _TRADING_DAYS),
                    "share": _r4(c / port_var) if port_var > 0 else None,
                }
            )
        wavg = (
            sum(weights[s] / (covered_value / total) * sds[s] for s in covered)
            if covered_value > 0
            else 0.0
        )
        port_sd = (
            math.sqrt(port_var) / (covered_value / total)
            if covered_value > 0 and port_var > 0
            else None
        )
        div_ratio = wavg / port_sd if port_sd else None
        syms = sorted(covered)
        corrs = []
        matrix = []
        for a in syms:
            row = []
            for b in syms:
                if sds[a] > 0 and sds[b] > 0:
                    c = cov[(a, b)] / (sds[a] * sds[b])
                else:
                    c = 1.0 if a == b else 0.0
                row.append(_r4(c))
                if a < b:
                    corrs.append(c)
            matrix.append(row)
        avg_corr = mean(corrs) if corrs else None
        if len(syms) <= 15:
            corr_out = {"symbols": syms, "matrix": matrix}
        else:
            pairs = sorted(
                (
                    (syms[i], syms[j], matrix[i][j])
                    for i in range(len(syms))
                    for j in range(i + 1, len(syms))
                ),
                key=lambda x: -abs(x[2]),
            )[:20]
            corr_out = {"pairs": [{"a": a, "b": b, "correlation": c} for a, b, c in pairs]}
    var99 = _percentile_var(port_rets, 0.01)[0] if n >= 3 else None
    portfolio = {
        "total_value": _r2(total),
        "cash_weight": _r4(cash / total),
        "coverage": _r4(covered_value / (total - cash)) if total - cash > 0 else None,
        "observations": n,
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "benchmark": bench_symbol,
        **pstats,
        "parametric_var_95": _r4(_Z95 * stdev(port_rets)) if n >= 3 else None,
        "var_99": _r4(var99),
        "diversification_ratio": _r4(div_ratio),
        "avg_pairwise_correlation": _r4(avg_corr),
    }
    if pstats["beta"] is None and n >= 3 and bench_rets is None:
        portfolio["beta"] = None

    # --- concentration ---------------------------------------------------------------------
    w_pos = sorted(weights.values(), reverse=True)
    hhi = round(sum(w * w for w in w_pos), 4)
    concentration = {
        "hhi": hhi,
        "hhi_interpretation": "diversified"
        if hhi < 0.10
        else "moderate"
        if hhi <= _HHI_MODERATE_MAX
        else "concentrated",
        "top_5_concentration": _r4(sum(w_pos[:5])),
        "largest_position": _r4(w_pos[0]) if w_pos else None,
        "position_count": len(positions),
    }

    # --- scenarios -------------------------------------------------------------------------
    scenarios = []
    for sc in params.get("scenarios") or []:
        if not isinstance(sc, dict) or not sc.get("name"):
            continue
        start, end = sc.get("start"), sc.get("end")
        bench_ret_in = _num(sc.get("benchmark_return"), "benchmark_return")
        row: dict = {
            "name": str(sc["name"]),
            "start": start,
            "end": end,
            "mode": "skipped",
            "benchmark_return": None,
            "positions": {},
            "portfolio_return": None,
            "portfolio_loss": None,
            "note": None,
        }
        s_start, s_end = (str(start), str(end)) if start and end else (None, None)
        # Replay a symbol from its own prices whenever its own history spans the window, even if
        # the aligned window (the dates every covered symbol shares) starts later. The benchmark
        # return is replayed the same way when its history spans the window, else it is the
        # scenario's given figure; every other covered symbol is beta-scaled against it.
        bench_ret = bench_ret_in
        if s_start and bench is not None and bench.dates and bench.dates[0] <= s_start:
            b0, b1 = bench.on(s_start), bench.on(s_end)
            if b0 and b1 is not None:
                bench_ret = b1 / b0 - 1
        rets: dict[str, float] = {}
        replayed: list[str] = []
        scaled: list[str] = []
        no_beta: list[str] = []
        for sym in covered:
            ser = series[sym]
            if s_start and ser.dates and ser.dates[0] <= s_start:
                p0, p1 = ser.on(s_start), ser.on(s_end)
                if p0 and p1 is not None:
                    rets[sym] = p1 / p0 - 1
                    replayed.append(sym)
                    continue
            if bench_ret is None:
                continue
            beta_s = by_symbol[sym]["beta"]
            if beta_s is None:
                no_beta.append(sym)
                continue
            rets[sym] = beta_s * bench_ret
            scaled.append(sym)
        if replayed or scaled:
            port = sum(weights[sym] * r for sym, r in rets.items())
            row.update(
                {
                    "mode": "replay" if not scaled else ("mixed" if replayed else "beta_scaled"),
                    "benchmark_return": _r4(bench_ret),
                    "positions": {sym: _r4(r) for sym, r in sorted(rets.items())},
                    "portfolio_return": _r4(port),
                    "portfolio_loss": _r2(port * total),
                    "replayed": sorted(replayed),
                    "beta_scaled": sorted(scaled),
                }
            )
            notes = []
            if scaled and not replayed:
                notes.append(
                    "window is outside the price history; loss estimated as beta x benchmark return"
                    if s_start
                    else "loss estimated as beta x benchmark return"
                )
            elif scaled:
                notes.append(
                    f"loss estimated as beta x benchmark return for: {', '.join(sorted(scaled))}"
                )
            if no_beta:
                notes.append(f"no beta for: {', '.join(sorted(no_beta))}")
            if missing:
                notes.append(
                    f"positions without history are assumed unchanged: {', '.join(missing)}"
                )
            row["note"] = "; ".join(notes) if notes else None
        else:
            row.update({"replayed": [], "beta_scaled": []})
            row["note"] = (
                "window is outside the price history and no benchmark_return was given"
                if s_start
                else "no benchmark_return was given"
            )
        scenarios.append(row)

    # --- what-if -----------------------------------------------------------------------------
    what_if = None
    shocks = params.get("shocks") or {}
    if isinstance(shocks, dict) and shocks:
        losses = {
            str(s).upper(): positions.get(str(s).upper(), 0.0) * _num(v, "shock")
            for s, v in shocks.items()
        }
        total_loss = sum(losses.values())
        what_if = {
            "shocks": {str(s).upper(): _num(v, "shock") for s, v in shocks.items()},
            "positions": {s: _r2(v) for s, v in losses.items() if s in positions},
            "portfolio_return": _r4(total_loss / total),
            "portfolio_loss": _r2(total_loss),
        }

    # --- flags -------------------------------------------------------------------------------
    flags = []
    high = [
        f"{r['symbol']} ({r['beta']})"
        for r in position_rows
        if r["beta"] is not None and r["beta"] > 1.3
    ]
    high_txt = ", ".join(high) or "none"
    if high or (portfolio["beta"] is not None and portfolio["beta"] > 1.3):
        flags.append(
            {
                "code": "HIGH_BETA",
                "message": f"portfolio beta {portfolio['beta']}; high-beta positions: {high_txt}",
            }
        )
    if avg_corr is not None and avg_corr > 0.7:
        flags.append(
            {
                "code": "HIGH_CORRELATION",
                "message": f"average pairwise correlation {_r4(avg_corr)}: "
                "positions tend to move together",
            }
        )
    largest_pct = round((concentration["largest_position"] or 0) * 100, 1)
    if concentration["largest_position"] is not None and (
        concentration["largest_position"] > 0.25 or hhi > _HHI_MODERATE_MAX
    ):
        flags.append(
            {
                "code": "CONCENTRATED",
                "message": f"largest position {largest_pct}% of value, HHI {hhi}",
            }
        )
    if 0 < n < 250:
        flags.append(
            {
                "code": "SHORT_HISTORY",
                "message": f"only {n} aligned trading days of history; statistics are noisy",
            }
        )
    if missing:
        share = sum(positions[s] for s in missing) / (total - cash) if total - cash > 0 else 0.0
        flags.append(
            {
                "code": "MISSING_PRICES",
                "message": f"no price history for: {', '.join(missing)} ({round(share * 100, 1)}% "
                "of value); statistics cover the rest",
            }
        )

    result = {
        "portfolio": portfolio,
        "positions": position_rows,
        "risk_contributions": contributions,
        "correlation": corr_out,
        "concentration": concentration,
        "scenarios": scenarios,
        "what_if": what_if,
        "missing_prices": missing,
        "flags": flags,
    }
    if factors_out is not None:
        result["factors"] = factors_out
        result["factors_total_explained_variance"] = factors_total_ev
    return result


def main() -> None:
    """Read JSON params from stdin, write the risk view (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_risk(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
