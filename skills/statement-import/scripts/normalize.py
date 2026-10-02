"""Normalize brokerage statement rows (CSV exports) or SnapTrade activity
objects into one canonical transaction ledger.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python normalize.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "source": "csv" | "snaptrade",      # required
      "account_id": "acc-1",              # optional, stamped on every entry
      "rows": [ {...}, ... ],             # required, non-empty:
                                          #   csv       -> one object per data row,
                                          #                keyed by the header text
                                          #   snaptrade -> raw activity objects from
                                          #                list_brokerage_transactions /
                                          #                transactions.py
      "mapping": {"date": "Run Date", "action": "Action", "symbol": "Symbol",
                  "description": "Description", "units": "Quantity",
                  "price": "Price ($)", "amount": "Amount ($)",
                  "fee": ["Commission ($)", "Fees ($)"]}   # optional, csv only;
                                          # any key given overrides auto-detection
    }

Output JSON contract (stdout)::

    {
      "source": ..., "account_id": ...,
      "columns": {date, action, symbol, description, units, price, amount,
                  fee: [...]} | null,     # detected/used CSV columns (null for snaptrade)
      "transactions": [                   # sorted by date, then input order
        {"date": "YYYY-MM-DD",
         "type": "BUY" | "SELL" | "DIVIDEND" | "INTEREST" | "FEE" | "DEPOSIT" |
                 "WITHDRAWAL" | "SPLIT" | "TRANSFER_IN" | "TRANSFER_OUT" | "OTHER",
         "symbol": "AAPL" | null,
         "units": 10.0 | null,            # always positive
         "price": 100.0 | null,
         "amount": -1000.02 | null,       # signed net cash flow to the account:
                                          #   BUY/FEE/WITHDRAWAL/TRANSFER_OUT <= 0,
                                          #   SELL/DIVIDEND/INTEREST/DEPOSIT/TRANSFER_IN >= 0
         "fee": 0.02,                     # commissions + fees, >= 0
         "reinvested": false,             # BUY funded by a dividend reinvestment
         "description": "...",            # broker's action text
         "security_name": "..." | null,   # CSV description column, when separate
         "split_ratio": 2.0 | null,       # SPLIT entries only: a/b from the action text
                                          #   ("2:1" -> 2.0, "3-for-2" -> 1.5, "1:10" -> 0.1);
                                          #   null when no ratio parses; absent on other types
         "account_id": ..., "source_id": "row:1" | "<activity id>"}
      ],
      "count": N,
      "skipped": [{"row": 7, "reason": "blank row"}],   # 1-based data-row numbers
      "types": {"BUY": 2, ...},
      "date_range": {"start": ..., "end": ...} | null
    }

CSV column detection is case- and punctuation-insensitive over common
header aliases (Run Date / Trade Date / Date, Action / Transaction Type /
Activity, Symbol / Ticker, Quantity / Shares, Price, Amount / Net Amount,
Commission / Fees / Fees & Comm ...). Types are classified from keywords in
the action and description text ("reinvest" -> BUY reinvested, "dividend",
"interest", "sold", "bought", "fee", "withdraw"/"sent", "deposit"/
"received"/"journal" ...); the sign of ``amount`` is then forced by type so
exports that print buys as positive numbers still come out right. Dates
accept YYYY-MM-DD, MM/DD/YYYY, YYYY/MM/DD, "Aug 10, 2026", 10-Aug-2026,
MM-DD-YYYY and ISO timestamps; Schwab's "MM/DD/YYYY as of MM/DD/YYYY" keeps
the first date. Money accepts "$1,234.56", "-$12", "(1,234.56)".
SPLIT entries additionally carry ``split_ratio``: the ratio is parsed from
the combined action/description text ("2:1", "3-for-2", "10 FOR 1",
"1:10" for a reverse split); date-like tokens ("08/01/2026") are excluded
so they never read as a ratio, and a SPLIT row with no ratio gets null.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime

_TYPES = (
    "BUY",
    "SELL",
    "DIVIDEND",
    "INTEREST",
    "FEE",
    "DEPOSIT",
    "WITHDRAWAL",
    "SPLIT",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "OTHER",
)
_NEGATIVE = {"BUY", "FEE", "WITHDRAWAL", "TRANSFER_OUT"}
_POSITIVE = {"SELL", "DIVIDEND", "INTEREST", "DEPOSIT", "TRANSFER_IN"}

# alias lists are in priority order; headers are compared after _norm()
_ALIASES: dict[str, list[str]] = {
    "date": [
        "run date",
        "trade date",
        "transaction date",
        "activity date",
        "process date",
        "posted date",
        "date",
    ],
    "action": [
        "action",
        "transaction type",
        "trans type",
        "activity type",
        "activity",
        "transaction",
        "type",
    ],
    "symbol": ["symbol", "ticker symbol", "ticker", "security"],
    "description": ["description", "security description", "security name", "name", "memo"],
    "units": ["quantity", "shares", "units", "qty"],
    "price": ["price", "unit price", "price per share", "share price"],
    "amount": ["amount", "net amount", "net cash", "cash amount", "total", "value"],
}
_FEE_ALIASES = {
    "commission",
    "commissions",
    "fees",
    "fee",
    "fees comm",
    "commissions fees",
    "commission fees",
    "fees and commissions",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
)
_DATE_TOKEN = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4}/\d{2}/\d{2}"
    r"|\d{1,2}-[A-Za-z]{3}-\d{4}|\d{2}-\d{2}-\d{4}|[A-Za-z]{3,9} \d{1,2}, \d{4}"
)

_SNAPTRADE_TYPES: dict[str, tuple[str, bool]] = {
    "BUY": ("BUY", False),
    "SELL": ("SELL", False),
    "REI": ("BUY", True),
    "DIVIDEND": ("DIVIDEND", False),
    "STOCK_DIVIDEND": ("DIVIDEND", False),
    "CONTRIBUTION": ("DEPOSIT", False),
    "WITHDRAWAL": ("WITHDRAWAL", False),
    "INTEREST": ("INTEREST", False),
    "FEE": ("FEE", False),
    "SPLIT": ("SPLIT", False),
    "STOCK_SPLIT": ("SPLIT", False),
    "EXTERNAL_ASSET_TRANSFER_IN": ("TRANSFER_IN", False),
    "EXTERNAL_ASSET_TRANSFER_OUT": ("TRANSFER_OUT", False),
    "INTERNAL_ASSET_TRANSFER_IN": ("TRANSFER_IN", False),
    "INTERNAL_ASSET_TRANSFER_OUT": ("TRANSFER_OUT", False),
    "EXTERNAL_CASH_TRANSFER_IN": ("DEPOSIT", False),
    "EXTERNAL_CASH_TRANSFER_OUT": ("WITHDRAWAL", False),
    "INTERNAL_CASH_TRANSFER_IN": ("DEPOSIT", False),
    "INTERNAL_CASH_TRANSFER_OUT": ("WITHDRAWAL", False),
}


def _norm(header: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(header).lower()).strip()


def parse_date(raw: object) -> str | None:
    """ISO date from a broker date string, or None when nothing parses."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})[T ]", text)
    candidates = [text, text.split(" as of ")[0].strip(), *([iso.group(1)] if iso else [])]
    m = _DATE_TOKEN.match(text)  # only a leading date counts: trailer lines mention dates too
    if m:
        candidates.append(m.group(0))
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def parse_money(raw: object) -> float | None:
    """Float from '$1,234.56', '-$12', '(1,234.56)', numbers; None when blank/non-numeric."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text or text.lower() in {"n/a", "na", "--", "-", "none", "null"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("$", "").replace(",", "").replace(" ", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return -abs(value) if negative else value


def classify(text: str, units: float | None, amount: float | None) -> tuple[str, bool]:
    """Ledger type and reinvested flag from the broker's action/description text."""
    t = " ".join(text.lower().split())
    if "reinvest" in t:
        return "BUY", True
    if "split" in t:
        return "SPLIT", False
    if any(k in t for k in ("dividend", "distribution", "cap gain", "capital gain")):
        return "DIVIDEND", False
    if "interest" in t:
        return "INTEREST", False
    if any(k in t for k in ("sold", "sell")):
        return "SELL", False
    if any(k in t for k in ("bought", "buy", "purchase")):
        return "BUY", False
    if any(k in t for k in ("fee", "commission")):
        return "FEE", False
    if (
        units
        and units > 0
        and any(k in t for k in ("transfer", "acat", "journal", "receive", "deliver"))
    ):
        return (
            "TRANSFER_OUT" if any(k in t for k in ("out", "deliver", "sent")) else "TRANSFER_IN"
        ), False
    if any(
        k in t
        for k in ("withdraw", "wire sent", "wire out", "eft out", "transfer out", "sent", "debit")
    ):
        return "WITHDRAWAL", False
    if any(
        k in t
        for k in (
            "deposit",
            "contribution",
            "received",
            "eft in",
            "transfer in",
            "journal",
            "wire in",
            "funds transfer",
            "credit",
            "transfer",
        )
    ):
        return ("WITHDRAWAL" if amount is not None and amount < 0 else "DEPOSIT"), False
    return "OTHER", False


_RATIO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[:\-/]|for)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def split_ratio(text: object) -> float | None:
    """Split ratio (a/b) from a split row's combined action/description text, or None.

    Date-like tokens are blanked first ("08/01/2026" must not read as 8:1);
    a second pass spaces out hyphen-glued "3-for-2" wording the first cannot
    see. "2:1" -> 2.0, "3-for-2" -> 1.5, "1:10" (reverse) -> 0.1.
    """
    t = _DATE_TOKEN.sub(" ", " ".join(str(text or "").lower().split()))
    m = _RATIO_RE.search(t)
    if m is None:
        m = _RATIO_RE.search(t.replace("-", " "))
    if m is None:
        return None
    return round(float(m.group(1)) / float(m.group(2)), 6)


def _signed(kind: str, amount: float | None) -> float | None:
    if amount is None:
        return None
    if kind in {"SPLIT", "TRANSFER_IN", "TRANSFER_OUT"} and amount == 0:
        return None
    if kind in _NEGATIVE:
        return -abs(amount)
    if kind in _POSITIVE:
        return abs(amount)
    return amount


def _detect_columns(headers: list[str], mapping: dict) -> dict:
    by_norm: dict[str, str] = {}
    for h in headers:
        by_norm.setdefault(_norm(h), h)
    cols: dict = {}
    for key, aliases in _ALIASES.items():
        if mapping.get(key):
            cols[key] = str(mapping[key])
            continue
        cols[key] = next((by_norm[a] for a in aliases if a in by_norm), None)
    if mapping.get("fee"):
        fee = mapping["fee"]
        cols["fee"] = [str(f) for f in (fee if isinstance(fee, list) else [fee])]
    else:
        cols["fee"] = [h for h in headers if _norm(h) in _FEE_ALIASES]
    if cols["date"] is None:
        raise ValueError("could not detect a date column; pass mapping.date")
    if cols["action"] is None and cols["description"] is None:
        raise ValueError(
            "could not detect an action, type, or description column; pass mapping.action"
        )
    return cols


def _csv_rows(
    rows: list, account_id: str | None, mapping: dict
) -> tuple[dict, list[dict], list[dict]]:
    headers: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            for h in r:
                if h not in headers:
                    headers.append(h)
    cols = _detect_columns(headers, mapping)
    out: list[dict] = []
    skipped: list[dict] = []
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            skipped.append({"row": i, "reason": "not an object"})
            continue
        if all(str(v or "").strip() == "" for v in r.values()):
            skipped.append({"row": i, "reason": "blank row"})
            continue
        raw_date = r.get(cols["date"])
        date = parse_date(raw_date)
        if date is None:
            skipped.append({"row": i, "reason": f"unparseable date: {str(raw_date).strip()!r}"})
            continue
        action = str(r.get(cols["action"]) or "").strip() if cols["action"] else ""
        desc = str(r.get(cols["description"]) or "").strip() if cols["description"] else ""
        units = parse_money(r.get(cols["units"])) if cols["units"] else None
        units = abs(units) if units else None
        price = parse_money(r.get(cols["price"])) if cols["price"] else None
        price = abs(price) if price is not None else None
        amount = parse_money(r.get(cols["amount"])) if cols["amount"] else None
        fee = sum(abs(parse_money(r.get(c)) or 0.0) for c in cols["fee"])
        kind, reinvested = classify(f"{action} {desc}", units, amount)
        symbol = str(r.get(cols["symbol"]) or "").strip().upper() if cols["symbol"] else ""
        entry = {
            "date": date,
            "type": kind,
            "symbol": symbol or None,
            "units": units,
            "price": price,
            "amount": _signed(kind, amount),
            "fee": round(fee, 4),
            "reinvested": reinvested,
            "description": action or desc,
            "security_name": (desc or None) if action else None,
            "account_id": account_id,
            "source_id": f"row:{i}",
            "_order": i,
        }
        if kind == "SPLIT":
            entry["split_ratio"] = split_ratio(f"{action} {desc}")
        out.append(entry)
    return cols, out, skipped


def _snaptrade_rows(rows: list, account_id: str | None) -> tuple[list[dict], list[dict]]:
    out: list[dict] = []
    skipped: list[dict] = []
    for i, a in enumerate(rows, start=1):
        if not isinstance(a, dict):
            skipped.append({"row": i, "reason": "not an object"})
            continue
        date = parse_date(a.get("trade_date") or a.get("settlement_date"))
        if date is None:
            skipped.append(
                {"row": i, "reason": f"unparseable date: {str(a.get('trade_date')).strip()!r}"}
            )
            continue
        units = parse_money(a.get("units"))
        units = abs(units) if units else None
        amount = parse_money(a.get("amount"))
        raw_type = str(a.get("type") or "").upper()
        desc = str(a.get("description") or "").strip()
        sym = a.get("symbol") if isinstance(a.get("symbol"), dict) else {}
        symbol = sym.get("symbol") or sym.get("raw_symbol")
        opt = a.get("option_symbol") if isinstance(a.get("option_symbol"), dict) else None
        if opt:
            under = (
                opt.get("underlying_symbol")
                if isinstance(opt.get("underlying_symbol"), dict)
                else {}
            )
            symbol = symbol or under.get("symbol")
            desc = f"{desc} [{opt.get('ticker')}]".strip()
        if raw_type in _SNAPTRADE_TYPES:
            kind, reinvested = _SNAPTRADE_TYPES[raw_type]
        elif raw_type == "TRANSFER":
            kind = (
                "TRANSFER_IN"
                if (units and (amount or 0) >= 0)
                else (
                    "DEPOSIT"
                    if (amount or 0) > 0
                    else "WITHDRAWAL"
                    if (amount or 0) < 0
                    else "TRANSFER_OUT"
                )
            )
            reinvested = False
        else:
            kind, reinvested = classify(f"{raw_type.replace('_', ' ')} {desc}", units, amount)
        price = parse_money(a.get("price"))
        entry = {
            "date": date,
            "type": kind,
            "symbol": str(symbol).upper() if symbol else None,
            "units": units,
            "price": abs(price) if price else None,
            "amount": _signed(kind, amount),
            "fee": round(abs(parse_money(a.get("fee")) or 0.0), 4),
            "reinvested": reinvested,
            "description": desc,
            "security_name": None,
            "account_id": account_id,
            "source_id": str(a.get("id")) if a.get("id") is not None else f"row:{i}",
            "_order": i,
        }
        if kind == "SPLIT":
            entry["split_ratio"] = split_ratio(f"{raw_type.replace('_', ' ')} {desc}")
        out.append(entry)
    return out, skipped


def run_normalize(params: dict) -> dict:
    """Normalize ``params['rows']``; raises ValueError on invalid input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    source = params.get("source")
    rows = params.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty list")
    if source not in ("csv", "snaptrade"):
        raise ValueError("source must be 'csv' or 'snaptrade'")
    account_id = params.get("account_id")
    mapping = params.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise ValueError("mapping must be an object")
    if source == "csv":
        columns, entries, skipped = _csv_rows(rows, account_id, mapping)
    else:
        columns, (entries, skipped) = None, _snaptrade_rows(rows, account_id)
    entries.sort(key=lambda e: (e["date"], e["_order"]))
    for e in entries:
        e.pop("_order")
    types: dict[str, int] = {}
    for e in entries:
        types[e["type"]] = types.get(e["type"], 0) + 1
    return {
        "source": source,
        "account_id": account_id,
        "columns": columns,
        "transactions": entries,
        "count": len(entries),
        "skipped": skipped,
        "types": dict(sorted(types.items())),
        "date_range": {"start": entries[0]["date"], "end": entries[-1]["date"]}
        if entries
        else None,
    }


def main() -> None:
    """Read JSON params from stdin, write the normalized ledger (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_normalize(json.loads(raw))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
