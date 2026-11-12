#!/usr/bin/env python3
"""Usage: deep_prep.py SYMBOL --case DIR [--plan valuation|valuation-picker] [--industry FILE ...]

Everything a deep valuation needs before its research subagents start, in one call:

- makes the case folder ``DIR`` with ``baseline/``, ``research/``, ``threads/`` and ``custom/``;
- builds the deep research pack into ``baseline/`` (``second_opinion.pack``: SEC financials, the
  10-K and 10-Q text, earnings releases, analyst consensus, the quick value, red-flag passages, the
  forensic checks, and ``INDEX.md`` naming every file and the resolved script commands);
- copies each ``--industry`` file (the deep picker's industry object and notes) to
  ``baseline/picker-industry-<name>`` and lists it in ``INDEX.md``;
- starts ``budget.json`` on the plan (default ``valuation``; ``budget.py`` holds the caps). A
  budget.json already there is kept with what it has used, flagged BUDGET_KEPT;
- writes ``model.skeleton.json``, a ``model.py`` input with the mechanical fields filled.

Output::

    {"symbol", "case", "summary": <the pack's summary>, "missing": [pack files not built],
     "budget": <budget.py's status>, "index": "<DIR>/baseline/INDEX.md",
     "skeleton": "<DIR>/model.skeleton.json", "flags": [{"code", "message"}]}

``symbol`` is the form everything was fetched by: upper case, a share-class dot as a dash
(``BRK.B`` is prepared as ``BRK-B``, which the SEC list and Yahoo both use).

``flags`` carries inputs.py's flags with their messages (ERP_DEFAULT, CYCLICAL,
DCF_NOT_MEANINGFUL_FOR_…, CURRENCY_MISMATCH), DEFAULT_USER_AGENT when EDGAR has no contact set,
PACK_INCOMPLETE when ``missing`` is not empty, SKELETON_INCOMPLETE naming the fields left null,
BUDGET_KEPT, and:

- THIN_EDGAR_HISTORY: ``baseline/edgar.json`` has no annual rows, or its filing index has no
  10-K. The filings may sit under a predecessor registrant (a successor's new CIK has no 10-K
  yet) or the company files a 20-F; the pack's figures then come from Yahoo alone. The message
  is the pack's (``summary.flag_notes``), is at the top of ``INDEX.md`` and in ``_notes``.
- DILUTION_UNRELIABLE: EDGAR's ``diluted_shares_cagr`` is more than 10% a year in size, or the
  annual table's diluted share count changed more than 25% in one year (a split, a reverse
  split, an IPO): ``annual_dilution`` is written as 0 and the message gives the raw figure.

``model.skeleton.json``: ``symbol``, ``price``, ``shares_outstanding`` (MILLIONS; inputs.py's
count / 1e6), ``years`` 10, ``horizon`` 5, ``base_discount_rate`` (inputs.py's ``wacc``),
``tax_rate``, ``cost_of_debt``, ``payout`` 1, ``annual_dilution`` (EDGAR's
``diluted_shares_cagr``; 0 when null or DILUTION_UNRELIABLE, since model.py compounds the share
count by it every year), ``hurdle`` 0.10, ``claims`` {}, ``segments`` [],
``scenarios`` [], and ``_notes``: the source of each filled value, the ERP flags, debt and cash in
millions for the claims, and what the analyst still fills. Money in the model is in millions.
Copy it to ``model.json`` and fill it; ``deep_run.py`` ignores keys that start with ``_``.

A pack source that fails is named in ``missing`` and the run goes on, except SEC EDGAR itself.
Exit 5 (``code`` EDGAR_UNREADABLE): the pack came back without ``edgar.json``, so the SEC refused
the requests or is down and the pack is near-empty. The ``error`` gives the reason and names
DEFAULT_USER_AGENT when no EDGAR contact is set; the output also carries ``missing`` and
``flags``. The folders stay; no budget.json or model.skeleton.json is written. Exit 2: a bad or unknown
ticker (not in the SEC's list), a bad flag, an ``--industry`` file that does not exist; nothing
but the empty folders is written. Exit 4: SEC EDGAR or the fundamental-research skill is not set
up (``code`` SKILL_MISSING or CONFIG_MISSING, passed through from the script that said so).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import edgar, output, pack  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

HERE = Path(__file__).resolve().parent
PLANS = ("valuation", "valuation-picker")
FOLDERS = ("baseline", "research", "threads", "custom")
INDUSTRY_PREFIX = "picker-industry-"
_ERP_FLAGS = ("ERP_DEFAULT", "ERP_STALE")
MAX_DILUTION_RATE = 0.10  # a diluted-share CAGR larger than this in size is a split or an IPO, not a rate to project
MAX_SHARE_STEP = 0.25  # the same for one year's change in the annual table's diluted share count
_UA_FLAG = {"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT to 'app-name contact@email' as the SEC requires; the default placeholder may be blocked"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"deep_prep.py: {message}")


def _budget_module():
    spec = importlib.util.spec_from_file_location("budget", HERE / "budget.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _value(inputs: dict, key: str) -> tuple[float | None, str]:
    entry = (inputs.get("assumptions") or {}).get(key) or {}
    value = entry.get("value")
    return (value if isinstance(value, (int, float)) and not isinstance(value, bool) else None), str(entry.get("source") or "no source given")


def _millions(v: object) -> float | None:
    return round(float(v) / 1e6, 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def dilution(edgar_out: dict) -> tuple[float, float | None, str | None]:
    """(annual_dilution for the model, EDGAR's raw diluted_shares_cagr, why the raw figure was not
    used or None). The raw rate is dropped for 0 when it is more than MAX_DILUTION_RATE in size or
    when any one year's diluted share count in the annual table moved more than MAX_SHARE_STEP:
    a split or an IPO in the window, which model.py would compound into every future year."""
    raw = (edgar_out.get("growth") or {}).get("diluted_shares_cagr")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return 0, None, None
    reasons = []
    if abs(raw) > MAX_DILUTION_RATE:
        reasons.append(f"it is more than {MAX_DILUTION_RATE:.0%} a year in size")
    rows = [(r.get("fiscal_year"), r.get("diluted_shares")) for r in edgar_out.get("annual") or [] if isinstance(r, dict)]
    rows = [(fy, float(n)) for fy, n in rows if isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0]
    steps = [(fy, new / old - 1, old, new) for (_, old), (fy, new) in zip(rows, rows[1:])]
    big = [step for step in steps if abs(step[1]) > MAX_SHARE_STEP]
    if big:
        shown = "; ".join(f"{change:+.0%} in fiscal {fy} ({old / 1e6:,.1f} to {new / 1e6:,.1f} million)" for fy, change, old, new in big[-3:])
        reasons.append(f"the diluted share count changed more than {MAX_SHARE_STEP:.0%} in one year: {shown}")
    if not reasons:
        return raw, raw, None
    return 0, raw, " and ".join(reasons) + ": a split, a reverse split, an IPO or a large one-off issue, not a yearly rate"


def skeleton(symbol: str, summary: dict, inputs: dict, edgar_out: dict, fundamentals: dict) -> tuple[dict, list[str]]:
    """(the model.py input with the mechanical fields filled, the names of the fields left null)."""
    wacc, wacc_source = _value(inputs, "wacc")
    tax, tax_source = _value(inputs, "tax_rate")
    cost_of_debt, debt_source = _value(inputs, "cost_of_debt")
    cost_of_equity, _ = _value(inputs, "cost_of_equity")
    shares_raw, shares_source = _value(inputs, "shares_outstanding")
    shares = round(shares_raw / 1e6, 4) if shares_raw else None
    dilution_used, dilution_raw, dilution_why = dilution(edgar_out)
    growth_years = (edgar_out.get("growth") or {}).get("years")
    info = fundamentals.get("info") or {}
    debt, cash = _millions(info.get("total_debt")), _millions(info.get("total_cash"))
    codes = [f.get("code") for f in inputs.get("flags") or [] if isinstance(f, dict)]

    notes = [
        "Units: money in MILLIONS and shares in millions throughout the model. The pack's JSON files are in absolute currency: divide by 1,000,000.",
        f"price: {summary.get('price')} (Yahoo quote, baseline/inputs.json dcf_input.current_share_price)",
        f"shares_outstanding: {shares} million = {shares_raw} / 1e6 ({shares_source}; baseline/inputs.json assumptions.shares_outstanding)",
        f"base_discount_rate: inputs.py wacc {wacc} ({wacc_source})",
        f"tax_rate: {tax} ({tax_source})",
        f"cost_of_debt: {cost_of_debt} ({debt_source})",
        (f"annual_dilution: 0, NOT EDGAR's diluted_shares_cagr of {dilution_raw} over {growth_years} years (DILUTION_UNRELIABLE): {dilution_why}. "
         "model.py compounds the share count by this rate every year. Set it by hand from the buybacks or issuance of the last two or three years (baseline/edgar.json annual, diluted_shares)."
         if dilution_why else
         f"annual_dilution: {dilution_raw} = EDGAR diluted_shares_cagr over {growth_years} years (baseline/edgar.json growth); negative is a shrinking count from buybacks. "
         "Keep it only if the buybacks are expected to go on and are not also counted in payout."
         if dilution_raw is not None else "annual_dilution: 0, because EDGAR's diluted_shares_cagr is null"),
        "years 10, horizon 5, payout 1 and hurdle 0.10 are the stated defaults: set payout from the company's dividends and buybacks against free cash flow.",
    ]
    for code in _ERP_FLAGS:
        flag = next((f for f in inputs.get("flags") or [] if isinstance(f, dict) and f.get("code") == code), None)
        if flag:
            notes.append(f"{code}: {str(flag.get('message')).rstrip('.')}. The discount rate above rests on it.")
    if cost_of_equity is not None:
        notes.append(f"cost of equity {cost_of_equity} (CAPM, baseline/inputs.json): use it as cost_of_equity for a residual_income segment (a bank or insurer).")
    for code, message in ((summary.get("flag_notes") or {}).items() if isinstance(summary.get("flag_notes"), dict) else ()):
        notes.append(f"{code}: {message}")
    special = [c for c in codes if c and (c.startswith("DCF_NOT_MEANINGFUL_FOR_") or c in ("NEGATIVE_FCF", "CYCLICAL", "CYCLE_BASE_SPLIT", "LARGE_MINORITY_INTEREST", "CORPORATE_ACTION_SUSPECTED", "SHARE_CLASSES_COMBINED", "CURRENCY_MISMATCH"))]
    if special:
        notes.append(f"inputs.py flags that shape the model: {', '.join(special)} (messages in baseline/inputs.json flags; the quick value's basis is {((summary.get('quick_value') or {}).get('basis'))!r}).")
    notes += [
        f"claims is empty for you to fill, in millions. Yahoo has total debt {debt} and cash {cash} (baseline/fundamentals.json info): confirm both against the balance sheet in "
        "baseline/filings/10k-item8.txt and add leases, minority_interest, pension_deficit, preferred and options from the notes.",
        "Still to fill: segments (from research/segments.md, plus a cost segment for unallocated corporate cost when it is reported), claims, "
        "scenarios (named, each with summary, must_be_true and overrides), history (max_margin per segment) and sensitivity.",
        "Keys that start with _ are dropped by deep_run.py. Save the filled model as model.json; leave this file as it is.",
    ]
    model = {
        "symbol": symbol, "price": summary.get("price"), "shares_outstanding": shares, "years": 10, "horizon": 5,
        "base_discount_rate": wacc, "tax_rate": tax, "cost_of_debt": cost_of_debt, "payout": 1,
        "annual_dilution": dilution_used,
        "hurdle": 0.10, "claims": {}, "segments": [], "scenarios": [], "_notes": notes,
    }
    empty = [k for k in ("price", "shares_outstanding", "base_discount_rate", "tax_rate", "cost_of_debt") if model[k] is None]
    return model, empty


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="deep_prep.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--case", required=True)
        p.add_argument("--plan", default="valuation")
        p.add_argument("--industry", action="append", default=[])
        ns = p.parse_args(args)
        symbol = pack.canonical_symbol(ns.symbol)  # BRK.B -> BRK-B, the form the SEC list and Yahoo use
        if ns.plan not in PLANS:
            raise InvalidInput(f"--plan must be one of {', '.join(PLANS)}, got {ns.plan!r}")
        industry = [Path(f).expanduser() for f in ns.industry]
        for f in industry:
            if not f.is_file():
                raise InvalidInput(f"--industry file not found: {f}")
        case = Path(ns.case).expanduser()
        baseline = case / "baseline"
        for sub in FOLDERS:
            (case / sub).mkdir(parents=True, exist_ok=True)

        built = pack.build(symbol, baseline, level="deep")  # InvalidInput (2) and ConfigError (4) pass through
        summary, missing = built.get("summary") or {}, list(built.get("missing") or [])
        if "edgar.json" in missing and not (baseline / "edgar.json").is_file():
            # Not even the filing index came back: every research role would start from an empty pack.
            reason = ((built.get("files") or {}).get("edgar.json") or {}).get("error") or "edgar.py returned nothing"
            ua = [_UA_FLAG] if edgar.user_agent_is_default() else []
            message = f"SEC EDGAR could not be read for {symbol} ({reason}), so there is no research pack to work from."
            if ua:
                message += f" DEFAULT_USER_AGENT: {_UA_FLAG['message']}."
            raise ApiError(message, code="EDGAR_UNREADABLE", missing=missing, flags=ua)

        copied = []
        for f in industry:
            name = f"{INDUSTRY_PREFIX}{f.name}"
            shutil.copyfile(f, baseline / name)
            copied.append(name)
        index = baseline / "INDEX.md"
        if copied:
            lines = ["", "## From the deep picker", "", "The finalist's industry object and notes. Take the sector outlook from them and spend searches on the company.", ""]
            lines += [f"- `{name}`" for name in copied]
            with open(index, "a") as fh:
                fh.write("\n".join(lines) + "\n")

        flags: list[dict] = []
        budget = _budget_module()
        if (case / budget.FILE).exists():
            status = budget.show(case)
            flags.append({"code": "BUDGET_KEPT", "message": f"budget.json was already there (plan {status.get('plan')}, {status.get('used_total')} searches used) and is kept; "
                                                            f"`budget.py DIR init --plan {ns.plan} --force` starts it again"})
        else:
            status = budget.init(case, ns.plan)

        inputs, edgar_out = _read(baseline / "inputs.json"), _read(baseline / "edgar.json")
        thin = (summary.get("flag_notes") or {}).get(pack.THIN_FLAG) if isinstance(summary.get("flag_notes"), dict) else None
        if not thin and (baseline / "edgar.json").is_file():  # a pack from before the flag: the same test on the file
            thin = pack.thin_edgar_note(edgar_out)
            if thin:
                summary = {**summary, "flag_notes": {**(summary.get("flag_notes") or {}), pack.THIN_FLAG: thin}}
        model, empty = skeleton(symbol, summary, inputs, edgar_out, _read(baseline / "fundamentals.json"))
        skeleton_path = case / "model.skeleton.json"
        skeleton_path.write_text(json.dumps(model, indent=2) + "\n")

        flags += [f for f in inputs.get("flags") or [] if isinstance(f, dict) and f.get("code")]
        flags += [f for f in edgar_out.get("flags") or [] if isinstance(f, dict) and f.get("code") == "DEFAULT_USER_AGENT"]
        if thin:
            flags.append({"code": pack.THIN_FLAG, "message": thin})
        _, raw_rate, why = dilution(edgar_out)
        if why:
            flags.append({"code": "DILUTION_UNRELIABLE", "message": f"annual_dilution in model.skeleton.json is 0, not EDGAR's diluted_shares_cagr of {raw_rate}: {why}. Set it by hand from recent buybacks or issuance."})
        if missing:
            flags.append({"code": "PACK_INCOMPLETE", "message": f"not built: {', '.join(missing)}; the reasons are under Missing in {index}"})
        if empty:
            flags.append({"code": "SKELETON_INCOMPLETE", "message": f"model.skeleton.json has null for {', '.join(empty)} (inputs.json is missing or could not fill them); set them by hand"})
        return {"symbol": symbol, "case": str(case), "summary": summary, "missing": missing, "budget": status,
                "index": str(index), "skeleton": str(skeleton_path), "flags": flags}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
