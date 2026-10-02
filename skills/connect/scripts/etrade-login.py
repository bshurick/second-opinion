#!/usr/bin/env python3
"""Usage: etrade-login.py [--verifier CODE | --revoke | --status]

E*Trade direct authorization (OAuth 1.0a). With no arguments: fetch a request
token, print the authorize URL (also to stderr) and try to open it; output
{url, pending: true, sandbox, opened}. The user signs in at E*Trade and reads a
5-character verifier code. --verifier CODE exchanges it, stores the access
token in the plugin data dir (mode 600) and lists the accounts it can see:
{authorized: true, sandbox, accounts}. --status reports the stored token
without any network call: {configured, token: none|usable|expired, created_at,
sandbox}. --revoke revokes and deletes the token. Tokens expire at midnight
Eastern; any E*Trade script then exits 4 with code ETRADE_REAUTH and the
URL to repeat this flow. Exit codes: 0, 2, 4 (ETRADE_NO_PENDING when
--verifier is used before a start), 5, 6.
"""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import config, output  # noqa: E402
from second_opinion.brokers import etrade_auth, router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

USAGE = "usage: etrade-login.py [--verifier CODE | --revoke | --status]"


def open_url(url: str) -> bool:
    try:
        if webbrowser.open(url):
            return True
    except Exception:  # noqa: BLE001
        pass
    for cmd in (["open", url], ["xdg-open", url]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def parse(args: list[str]) -> tuple[str, str | None]:
    if not args:
        return "start", None
    if args == ["--status"]:
        return "status", None
    if args == ["--revoke"]:
        return "revoke", None
    if len(args) == 2 and args[0] == "--verifier" and args[1] and not args[1].startswith("-"):
        return "complete", args[1]
    raise InvalidInput(USAGE)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        mode, verifier = parse(args)
        settings = config.load_settings().require_etrade()
        auth = etrade_auth.ETradeAuth(settings)
        if mode == "status":
            return auth.status()
        if mode == "revoke":
            auth.revoke()
            return {"revoked": True}
        if mode == "start":
            started = auth.start()
            sys.stderr.write(f"Open this URL, sign in to E*Trade, then run etrade-login.py --verifier CODE (link expires in 5 minutes):\n{started['url']}\n")
            return {"url": started["url"], "pending": True, "sandbox": started["sandbox"], "opened": open_url(started["url"])}
        token = auth.complete(verifier or "")
        accounts = router.load().for_broker("etrade").list_accounts()
        return {"authorized": True, "sandbox": token.sandbox, "accounts": accounts}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
