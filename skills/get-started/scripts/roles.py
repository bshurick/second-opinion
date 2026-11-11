#!/usr/bin/env python3
"""Usage: roles.py [--accept] [--partial]

The first run's accounts step: every connected account with one role. Output:
{"accounts": [{account_id, name, institution, raw_type, proposed_role, saved_role, role,
margin}], "broker_errors": [...]}. ``proposed_role`` is the account-type guess (retirement for an
IRA, Roth, 401(k) and the like, else trading); ``saved_role`` is ``accounts.<id>.role`` in
settings.json (null when unset); ``role`` is the saved role, else the proposal. ``margin`` is
true when the broker or BROKER_ACCOUNT_TYPES says margin.

--accept saves the proposal for each account with no saved role and prints the same table. A
saved role is never overwritten; a different role is saved with the get-started skill's
``settings.py set accounts.<id>.role ROLE``.

Exit codes: 0, 2 (bad argument), 4 (credentials or ETRADE_REAUTH; --partial runs without
E*Trade), 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, settings  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

USAGE = "usage: roles.py [--accept] [--partial]"


def _row(acct: dict) -> dict:
    aid = acct["account_id"]
    proposed = "retirement" if settings.is_tax_advantaged(acct.get("raw_type")) else "trading"
    saved = settings.get(f"accounts.{aid}.role")
    return {"account_id": aid, "name": acct.get("name"), "institution": acct.get("institution_name"),
            "raw_type": acct.get("raw_type"), "proposed_role": proposed, "saved_role": saved,
            "role": saved or proposed, "margin": acct.get("account_type") == "margin"}


def run(args: list[str]) -> dict:
    bad = [a for a in args if a not in ("--accept", "--partial")]
    if bad:
        raise InvalidInput(USAGE)
    hub = router.load()
    hub.partial = "--partial" in args
    rows = [_row(a) for a in hub.list_accounts()]
    if "--accept" in args:
        for r in rows:
            if r["saved_role"] is None:
                settings.set_value(f"accounts.{r['account_id']}.role", r["proposed_role"])
                r["saved_role"] = r["proposed_role"]
    return {"accounts": rows, "broker_errors": hub.broker_errors}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
