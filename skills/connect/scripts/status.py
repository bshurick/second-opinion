#!/usr/bin/env python3
"""Usage: status.py [--probe]

Connected brokerages and accounts: {"connections": [{id, brokerage, slug,
type ("trade"|"read"), disabled, updated_date}], "accounts": [...as
accounts.py], "direct": [{id, broker, type, status, sandbox}], "shadowed":
[...as accounts.py], "warnings": [...as accounts.py], "broker_errors":
[...as accounts.py]}. "direct" comes from every configured non-SnapTrade
broker's own connection status (empty when none is configured). A broker in
"broker_errors" answered nothing this run: its accounts are missing and
--probe reports it as "stale" with the same hint. Run this
first whenever another script exits 4 (config) or 5 (API).
--probe adds {"probe": [{id, brokerage, status, error_code?, message?}]}: one
lightweight holdings call per SnapTrade authorization (against its first
account) to tell healthy apart from stale (reconnect needed) or erroring
connections, plus one holdings call per configured direct broker; status is
"healthy", "disabled", "no_accounts", "stale", or "error". A "stale" row
carries "message" (how to reconnect); an "error" row carries "error_code"
instead. A probe failure never fails the run. Exit codes: 0, 2, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, ConfigError, InvalidInput  # noqa: E402

STALE_CODE = "1083"
STALE_HTTP_STATUSES = (401, 403)


def summarize(auth: dict) -> dict:
    b = auth.get("brokerage") or {}
    return {"id": auth.get("id"), "brokerage": b.get("name"), "slug": b.get("slug"), "type": auth.get("type"), "disabled": auth.get("disabled"), "updated_date": auth.get("updated_date")}


def probe_connections(sdk, auths: list[dict], accounts: list[dict]) -> list[dict]:
    first_account_by_auth: dict[str, dict] = {}
    for acct in accounts:
        auth_id = acct.get("brokerage_authorization")
        if auth_id and auth_id not in first_account_by_auth:
            first_account_by_auth[auth_id] = acct

    rows = []
    for auth in auths:
        auth_id = auth.get("id")
        b = auth.get("brokerage") or {}
        row = {"id": auth_id, "brokerage": b.get("name")}
        if auth.get("disabled"):
            row["status"] = "disabled"
            rows.append(row)
            continue
        acct = first_account_by_auth.get(auth_id)
        if acct is None:
            row["status"] = "no_accounts"
            rows.append(row)
            continue
        try:
            brokerage.get_portfolio(sdk, acct["account_id"])
            row["status"] = "healthy"
        except (ApiError, InvalidInput) as e:
            if isinstance(e, ApiError):
                code = e.extra.get("snaptrade_code")
                http_status = e.extra.get("http_status")
                if code == STALE_CODE or http_status in STALE_HTTP_STATUSES:
                    row["status"] = "stale"
                    row["message"] = f"reconnect with connect.py --reconnect {auth_id}"
                else:
                    row["status"] = "error"
                    row["error_code"] = code if code is not None else http_status
            else:
                # e.g. a malformed account_id from list_accounts (validate_account_id
                # inside brokerage.get_portfolio); never let this fail the whole run.
                row["status"] = "error"
                row["error_code"] = e.code if e.code and e.code != "INVALID_INPUT" else "INVALID_ACCOUNT_ID"
        rows.append(row)
    return rows


def probe_direct(hub) -> list[dict]:
    rows = []
    for b in hub.brokers:
        if b.name == "snaptrade":
            continue
        row = {"id": b.name, "brokerage": b.name}
        try:
            b.list_accounts()
            row["status"] = "healthy"
        except ConfigError as e:
            row["status"] = "stale"
            row["message"] = e.extra.get("hint") or str(e)
            if e.extra.get("url"):
                row["url"] = e.extra["url"]
        except (ApiError, InvalidInput) as e:
            row["status"] = "error"
            row["error_code"] = e.code
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        probe = "--probe" in args
        rest = [a for a in args if a != "--probe"]
        if rest:
            raise InvalidInput("usage: status.py [--probe]")
        hub = router.load()
        hub.partial = True  # a status report shows an expired login; it never demands one
        accounts = hub.list_accounts()
        result = {"connections": [], "accounts": accounts, "direct": hub.statuses(), "shadowed": hub.shadowed, "warnings": hub.warnings, "broker_errors": hub.broker_errors}
        try:
            sdk = hub.for_broker("snaptrade").sdk
        except ConfigError:
            sdk = None
        if sdk is not None:
            auths = brokerage.list_authorizations(sdk)
            result["connections"] = [summarize(a) for a in auths]
            if probe:
                result["probe"] = probe_connections(sdk, auths, accounts)
        if probe:
            result.setdefault("probe", []).extend(probe_direct(hub))
        return result

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
