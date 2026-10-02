#!/usr/bin/env python3
"""Usage: accounts.py [--include-closed] [--include-shadowed] [--partial]

List connected brokerage accounts. Output: {"accounts": [{account_id, name,
account_number, institution_name, supports_trading, raw_type, balance_total,
broker, account_type}], "shadowed": [...]} where account_type is "cash" or
"margin" (per-account override, else the broker's own type, else "cash") and
broker is the adapter that served the row ("snaptrade" or a direct broker's
name). ``shadowed`` lists SnapTrade accounts hidden because a direct broker
already serves the same brokerage account; --include-shadowed folds them back
into "accounts". ``warnings`` carries POSSIBLE_DUPLICATE rows: a SnapTrade
account at a brokerage a direct adapter also serves whose number matched no
direct account. ``broker_errors`` lists brokers that could not be listed at
all ({broker, code, message, hint?, url?, sandbox?}); their accounts are
missing from this run, and the list is empty on a clean run. Exit codes: 0,
4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        allowed = {"--include-closed", "--include-shadowed", "--partial"}
        bad = [a for a in args if a not in allowed]
        if bad:
            raise InvalidInput("usage: accounts.py [--include-closed] [--include-shadowed] [--partial]")
        hub = router.load()
        hub.partial = "--partial" in args
        accounts = hub.list_accounts(include_closed="--include-closed" in args, include_shadowed="--include-shadowed" in args)
        return {"accounts": accounts, "shadowed": hub.shadowed, "warnings": hub.warnings, "broker_errors": hub.broker_errors}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
