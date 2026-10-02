#!/usr/bin/env python3
"""Usage: items.py attach --items FILE.json|- [--date YYYY-MM-DD --amount N [--merchant TEXT] | --id TXID]
                        [--source KIND] [--create --account ID [--description TEXT] [--merchant TEXT]] [--dry-run]
       items.py list [--id TXID | --date YYYY-MM-DD]
       items.py detach --id TXID

Attach an itemized breakdown (a receipt, an order history, an invoice) to one transaction in
``spending.json``. ``--items`` accepts a bare JSON list of items or an object with an "items"
key. Items are ``[{"name", "amount" (signed, spend negative), "category" (taxonomy),
"detail" (slash path, optional), "quantity" (optional)}]``; their total may not exceed the
transaction's amount by more than $0.01, and the shortfall is the remainder, which stays in the
transaction's own category. The transaction is found by --id, or by --date and --amount (within
3 days and $0.50) plus an optional --merchant substring; one match attaches, several are listed
(exit 2, AMBIGUOUS_MATCH, ``candidates``), none exits 2 NO_MATCH unless --create stores a new
transcribed transaction (--account required, and --create cannot be combined with --id; an
empty store is initialized rather than exiting CONFIG_MISSING). --description defaults to
"<merchant> receipt" when --merchant is given, else the source kind capitalized once (e.g.
"Receipt"), which also becomes the merchant; source transcribed:<KIND>, KIND defaulting to
receipt. If the new row's account, date, amount and description reproduce an existing row's key,
nothing new is stored and the items attach to that existing row instead (matched_by "existing",
reported correctly on a --dry-run preview too). A second attach to the same transaction replaces
its items. ``list`` shows transactions that carry items (all, one by --id, or those on a date);
``detach`` removes a transaction's items. --dry-run validates and matches without writing.
Exit codes: 0, 2 (INVALID_ITEMS with items_total/transaction_amount, AMBIGUOUS_MATCH, NO_MATCH),
4 (CONFIG_MISSING when no store exists and --create is not given), 5 (SPENDING_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import spendnormalize  # noqa: E402
from second_opinion import output, spending  # noqa: E402
from second_opinion.errors import ApiError, ConfigError, InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"items.py: {message}")


def _load_book(create: bool = False) -> dict:
    path = spending.spending_path()
    if not path.is_file():
        if create:
            return spending.empty()
        raise ConfigError("nothing imported yet", hint="run import-spending.py <file> --account ID first", path=str(path))
    return spending.load(path)


def _read_items(spec: str) -> list:
    if spec == "-":
        raw = sys.stdin.read()
    else:
        path = Path(spec).expanduser()
        if not path.is_file():
            raise InvalidInput(f"items file not found: {path}", code="INVALID_ITEMS")
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InvalidInput(f"could not read items file: {exc}", code="INVALID_ITEMS") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise InvalidInput(f"--items must be JSON: {exc}", code="INVALID_ITEMS") from exc
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise InvalidInput("--items must be a non-empty JSON list of items", code="INVALID_ITEMS")
    return items


def _summary(book: dict, t: dict) -> dict:
    items = t.get("items") or []
    total = round(sum(float(i["amount"]) for i in items), 2)
    return {
        "id": t["id"], "date": t["date"], "account_id": t["account_id"], "merchant": t["merchant"], "description": t["description"],
        "amount": t["amount"], "category": t["category"], "detail": t.get("detail"), "source": spending.source_of(book, t),
        "items": items, "items_total": total, "remainder": round(float(t["amount"]) - total, 2),
    }


def _candidate(t: dict) -> dict:
    return {"id": t["id"], "date": t["date"], "account_id": t["account_id"], "merchant": t["merchant"], "amount": t["amount"], "has_items": bool(t.get("items"))}


def _check_date(date_: str | None) -> None:
    if date_ and spendnormalize.parse_date(date_) != date_:
        raise InvalidInput("--date must be YYYY-MM-DD")


def _existing_row(book: dict, tx_out: dict) -> dict | None:
    """The store's own row that a just-built candidate collided with in ``merge`` (same base key)."""
    base = spending.base_key(tx_out)
    return next((t for t in book["transactions"] if spending.base_key(t) == base and (t.get("occurrence") or 1) == 1), None)


def _attach(book: dict, ns: argparse.Namespace) -> dict:
    if ns.create and ns.id:
        raise InvalidInput("--create cannot be combined with --id: --create only applies when matching by --date/--amount")
    raw_items = _read_items(ns.items)
    try:
        items = spendnormalize.validate_items(raw_items)
    except ValueError as exc:
        raise InvalidInput(str(exc), code="INVALID_ITEMS") from exc
    if ns.source:
        items = [{**i, "source": i.get("source") or ns.source} for i in items]
    created = False
    matched_by = None
    if ns.id:
        tx = spending.find_transaction(book, ns.id)
        if tx is None:
            raise InvalidInput(f"no transaction with id {ns.id}", code="NO_MATCH")
        matched_by = "id"
    elif ns.date and ns.amount is not None:
        if ns.create and not ns.account:
            raise InvalidInput("--create needs --account ID")
        hits = spending.match_transactions(book, ns.date, ns.amount, merchant=ns.merchant)
        if len(hits) > 1:
            raise InvalidInput(
                "several transactions match; pass --id from the candidates", code="AMBIGUOUS_MATCH", candidates=[_candidate(t) for t in hits[:10]],
            )
        if hits:
            tx = hits[0]
            matched_by = "date+amount+merchant" if ns.merchant else "date+amount"
        elif ns.create:
            account = book["accounts"].get(ns.account)
            kind = (account or {}).get("kind") or "card"
            if ns.description:
                description = ns.description
            elif ns.merchant:
                description = f"{ns.merchant} receipt"
            else:
                # No merchant either: fall back to the source kind alone (capitalized once)
                # rather than interpolating it into "<Kind> receipt", which normalize_merchant
                # would then title-case a second time into a duplicated "Receipt Receipt".
                description = (ns.source or "receipt").capitalize()
            try:
                tx = spendnormalize.build_transaction(
                    ns.account, kind, date=ns.date, post_date=None, amount=float(ns.amount), description=description, issuer_category=None,
                    type_hint=None, fitid=None, rules=spending.load_rules(), source_id=f"items:{ns.date}", merchant_override=ns.merchant,
                    category_override=None, source=f"transcribed:{ns.source or 'receipt'}",
                )
            except ValueError as exc:
                raise InvalidInput(str(exc), code="INVALID_ITEMS") from exc
            if tx is None:
                raise InvalidInput("the new transaction matches an ignore rule", code="INVALID_ITEMS")
            if account is None:
                book["accounts"][ns.account] = {"id": ns.account, "name": ns.account, "kind": kind, "preset": "rows", "added": ns.date}
            created, matched_by = True, "created"
        else:
            raise InvalidInput("no transaction within 3 days and $0.50; pass --id, or --create --account ID to store a transcribed one", code="NO_MATCH")
    else:
        raise InvalidInput("pass --id TXID, or --date and --amount (with an optional --merchant)")
    try:
        items = spendnormalize.validate_items(items, float(tx["amount"]))
    except ValueError as exc:
        raise InvalidInput(str(exc), code="INVALID_ITEMS", items_total=round(sum(float(i["amount"]) for i in items), 2), transaction_amount=tx["amount"]) from exc
    replaced = bool(tx.get("items"))
    tx_out = {**tx, "items": items}
    result = {
        "dry_run": bool(ns.dry_run), "created": created, "matched_by": matched_by, "replaced": replaced,
        "items_total": round(sum(i["amount"] for i in items), 2), "remainder": round(float(tx["amount"]) - sum(i["amount"] for i in items), 2),
        "transaction": {**tx_out},
    }
    if ns.dry_run:
        if created:
            # A dry run never merges, so run the same collision check merge() would do (base
            # key, without stamping an occurrence) to preview against an existing row instead
            # of always claiming "created".
            collision = _existing_row(book, tx_out)
            if collision is not None:
                result["created"] = False
                result["matched_by"] = "existing"
                result["replaced"] = bool(collision.get("items"))
                result["transaction"] = {**collision, "items": items}
        return result
    if created:
        added, _dupes = spending.merge(book, [tx_out], {"file": "items", "account_id": ns.account, "preset": "rows"})
        if added == 0:
            book["imports"].pop()  # merge always logs an attempt; discard it when nothing was actually added
            existing = _existing_row(book, tx_out)
            if existing is None:
                raise ApiError("merge reported a duplicate but no matching row was found", code="SPENDING_CORRUPT")
            replaced = bool(existing.get("items"))
            existing["items"] = items
            result["created"] = False
            result["matched_by"] = "existing"
            result["replaced"] = replaced
            result["transaction"] = {**existing}
        else:
            stored = next(t for t in book["transactions"] if t.get("source_id") == tx_out["source_id"] and t["date"] == tx_out["date"] and t["amount"] == tx_out["amount"])
            result["transaction"] = {**stored}
    else:
        tx["items"] = items
    spending.save(book)
    result["spending_path"] = str(spending.spending_path())
    return result


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="items.py", add_help=False)
        sub = p.add_subparsers(dest="command", required=True)
        at = sub.add_parser("attach", add_help=False)
        at.add_argument("--items", required=True)
        at.add_argument("--id", default=None)
        at.add_argument("--date", default=None)
        at.add_argument("--amount", type=float, default=None)
        at.add_argument("--merchant", default=None)
        at.add_argument("--source", default=None)
        at.add_argument("--create", action="store_true")
        at.add_argument("--account", default=None)
        at.add_argument("--description", default=None)
        at.add_argument("--dry-run", action="store_true")
        ls = sub.add_parser("list", add_help=False)
        ls.add_argument("--id", default=None)
        ls.add_argument("--date", default=None)
        de = sub.add_parser("detach", add_help=False)
        de.add_argument("--id", required=True)
        ns = p.parse_args(args)
        book = _load_book(create=ns.command == "attach" and getattr(ns, "create", False))
        if ns.command == "attach":
            _check_date(ns.date)
            return _attach(book, ns)
        if ns.command == "list":
            _check_date(ns.date)
            rows = book["transactions"]
            if ns.id:
                rows = [t for t in rows if t.get("id") == ns.id]
            elif ns.date:
                rows = [t for t in rows if t.get("date") == ns.date]
            rows = [t for t in rows if t.get("items")]
            return {"count": len(rows), "transactions": [_summary(book, t) for t in rows], "spending_path": str(spending.spending_path())}
        tx = spending.find_transaction(book, ns.id)
        if tx is None or not tx.get("items"):
            raise InvalidInput(f"no transaction with items has id {ns.id}", code="NO_MATCH")
        count = len(tx.pop("items"))
        spending.save(book)
        return {"detached": count, "transaction": _candidate(tx), "spending_path": str(spending.spending_path())}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
