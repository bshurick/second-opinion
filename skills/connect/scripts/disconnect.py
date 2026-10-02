#!/usr/bin/env python3
"""Usage: disconnect.py <authorization_id> --confirm

Remove one brokerage connection (all its accounts disappear from SnapTrade).
Without --confirm prints the connection and exits 3. Output: {authorization_id, deleted}.
Exit codes: 0, 2, 3, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput, NotConfirmed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        confirm = "--confirm" in args
        rest = [a for a in args if a != "--confirm"]
        if len(rest) != 1:
            raise InvalidInput("usage: disconnect.py <authorization_id> --confirm")
        auth_id = rest[0]
        sdk = router.load().for_broker("snaptrade").sdk
        match = next((a for a in brokerage.list_authorizations(sdk) if a.get("id") == auth_id), None)
        if match is None:
            raise InvalidInput(f"no connection with id {auth_id}", code="AUTHORIZATION_NOT_FOUND")
        if not confirm:
            b = match.get("brokerage") or {}
            raise NotConfirmed("re-run with --confirm after the user explicitly approves disconnecting", connection={"id": auth_id, "brokerage": b.get("name"), "type": match.get("type")})
        return brokerage.delete_authorization(sdk, auth_id)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
