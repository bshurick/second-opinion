"""Comparable-companies (trading multiples) cross-check.

This script reads a JSON object from stdin, computes peer-median multiples
and the implied per-share value each multiple suggests for the target
company, and writes a JSON object to stdout. It is invoked as:

    python comps.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "target": {
        "metric_values": {"pe": 25.0, "ev_ebitda": 14.0, "ps": 5.0}
        # the target's own trading multiples; each is optional. Present
        # values are used to compute premium_discount_vs_peers.
      },
      "peers": [
        {"name": "A", "pe": 22, "ev_ebitda": 12, "ps": 4.5},
        ...
        # each peer's metric fields are optional; a metric needs at least
        # 2 peers reporting it to produce a median.
      ],
      "target_financials": {
        "eps": 6.5,                 # needed for the "pe" metric
        "ebitda_per_share": 11.0,   # needed for the "ev_ebitda" metric
        "sales_per_share": 32.0,    # needed for the "ps" and "ev_sales" metrics
        "book_value_per_share": 40.0,  # needed for the "pb" metric
        "fcf_per_share": 2.5,       # needed for the "fcf_yield" metric
        "ffo_per_share": 3.1,       # needed for the "p_ffo" metric (REITs)
        "net_debt_per_share": 4.0   # used by "ev_ebitda" and "ev_sales"; defaults to 0.0
      }
    }

Supported metrics are "pe", "ev_ebitda", "ps", "pb", "ev_sales",
"fcf_yield" and "p_ffo" (price to funds from operations, for REITs).
An implied value that is not positive (a negative peer cash yield, net
debt larger than the implied enterprise value) is reported for the metric
but left out of the summary, and named in "excluded_from_summary". A metric appears in the output only when both (a) at least 2
peers report a value for it, and (b) the target financial it needs is
present. Metrics that don't clear that bar are silently omitted (this is
expected/normal, e.g. a peer set with sparse data) -- see "skipped_metrics"
below for the one case that IS flagged.

Output JSON contract (stdout)::

    {
      "metrics": {
        "pe": {
          "peer_median": ...,                  # 4dp
          "implied_value_per_share": ...,      # 2dp; eps * peer_median
          "premium_discount_vs_peers": ...      # 4dp; target_multiple/median - 1
                                                 # present only when target.metric_values.pe is set
        },
        "ev_ebitda": {
          "peer_median": ...,
          "implied_value_per_share": ...,      # ebitda_per_share*median - net_debt_per_share
          "premium_discount_vs_peers": ...
        },
        "ps": {
          "peer_median": ...,
          "implied_value_per_share": ...,      # sales_per_share * peer_median
          "premium_discount_vs_peers": ...
        },
        "pb": {
          "peer_median": ...,
          "implied_value_per_share": ...,      # book_value_per_share * peer_median
          "premium_discount_vs_peers": ...
        },
        "ev_sales": {
          "peer_median": ...,
          "implied_value_per_share": ...,      # sales_per_share*median - net_debt_per_share
          "premium_discount_vs_peers": ...
        },
        "fcf_yield": {
          "peer_median": ...,
          "implied_value_per_share": ...,      # fcf_per_share / peer_median (yield inverts)
          "premium_discount_vs_peers": ...      # same formula as the other metrics
                                                 # (target_multiple/median - 1), but fcf_yield
                                                 # is a yield, not a price multiple: a POSITIVE
                                                 # value here means the target's yield is higher
                                                 # than peers', i.e. CHEAPER than peers (the
                                                 # opposite reading from pe/ev_ebitda/ps/pb/
                                                 # ev_sales, where positive means pricier). The
                                                 # value itself is not negated for fcf_yield.
        }
        # any metric with peer_median == 0 is OMITTED from this dict (see
        # skipped_metrics) rather than producing a divide-by-zero premium.
        # A zero *target financial* (e.g. eps=0) is different and NOT a
        # zero-denominator case: it just yields implied_value_per_share=0.0,
        # a fine defined result.
      },
      "skipped_metrics": {
        # present only when at least one metric was skipped for this reason;
        # "pe": "peer median multiple is 0; premium/discount is undefined, metric omitted"
      },
      "summary": {"min": ..., "max": ..., "median": ...}  # over included implied values, 2dp
    }

Validation errors (non-object input, fewer than 2 peers, or no metric with
enough peer data and matching target financials) are reported as
``{"error": "..."}`` on stdout with exit code 2.
"""

from __future__ import annotations

import json
import statistics
import sys

_METRIC_TARGET_FIELD = {
    "pe": "eps",
    "ev_ebitda": "ebitda_per_share",
    "ps": "sales_per_share",
    "pb": "book_value_per_share",
    "ev_sales": "sales_per_share",
    "fcf_yield": "fcf_per_share",
    "p_ffo": "ffo_per_share",
}


def _implied_value(metric: str, peer_median: float, target_financials: dict) -> float:
    if metric == "pe":
        return float(target_financials["eps"]) * peer_median
    if metric == "ps":
        return float(target_financials["sales_per_share"]) * peer_median
    if metric == "pb":
        return float(target_financials["book_value_per_share"]) * peer_median
    if metric == "fcf_yield":
        return float(target_financials["fcf_per_share"]) / peer_median
    if metric == "p_ffo":
        return float(target_financials["ffo_per_share"]) * peer_median
    # ev_ebitda and ev_sales
    net_debt_per_share = float(target_financials.get("net_debt_per_share", 0.0))
    return float(target_financials[_METRIC_TARGET_FIELD[metric]]) * peer_median - net_debt_per_share


def run_comps(params: dict) -> dict:
    """Run the comparable-multiples cross-check described by ``params``.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    peers = params.get("peers")
    if not isinstance(peers, list):
        raise ValueError("peers must be a list")
    if len(peers) < 2:
        raise ValueError("at least 2 peers are required")
    for peer in peers:
        if not isinstance(peer, dict):
            raise ValueError("each peer must be an object")

    target = params.get("target", {})
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    target_metric_values = target.get("metric_values", {})
    if not isinstance(target_metric_values, dict):
        raise ValueError("target.metric_values must be an object")

    target_financials = params.get("target_financials", {})
    if not isinstance(target_financials, dict):
        raise ValueError("target_financials must be an object")

    metrics_out: dict[str, dict] = {}
    skipped_metrics: dict[str, str] = {}
    implied_values: list[float] = []
    excluded: list[str] = []

    for metric, target_field in _METRIC_TARGET_FIELD.items():
        peer_values = [
            float(peer[metric]) for peer in peers if metric in peer and peer[metric] is not None
        ]
        if len(peer_values) < 2:
            continue
        if target_financials.get(target_field) is None:
            continue

        peer_median = statistics.median(peer_values)

        if peer_median == 0:
            skipped_metrics[metric] = (
                "peer median multiple is 0; premium/discount is undefined, metric omitted"
            )
            continue

        implied_value = _implied_value(metric, peer_median, target_financials)

        metric_out = {
            "peer_median": round(peer_median, 4),
            "implied_value_per_share": round(implied_value, 2),
        }
        target_multiple = target_metric_values.get(metric)
        if target_multiple is not None:
            premium_discount = float(target_multiple) / peer_median - 1
            metric_out["premium_discount_vs_peers"] = round(premium_discount, 4)

        metrics_out[metric] = metric_out
        if implied_value > 0:
            implied_values.append(implied_value)
        else:
            excluded.append(metric)

    if not metrics_out:
        raise ValueError(
            "no metric could be computed: need at least 2 peer values and the "
            "matching target financial for pe, ev_ebitda, ps, pb, ev_sales, fcf_yield, or p_ffo"
        )

    result: dict = {
        "metrics": metrics_out,
        "summary": {
            "min": round(min(implied_values), 2),
            "max": round(max(implied_values), 2),
            "median": round(statistics.median(implied_values), 2),
        }
        if implied_values
        else {"min": None, "max": None, "median": None},
    }
    if excluded:
        result["excluded_from_summary"] = excluded
    if skipped_metrics:
        result["skipped_metrics"] = skipped_metrics
    return result


def main() -> None:
    """Read JSON params from stdin, write the comps result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_comps(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
