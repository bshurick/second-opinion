#!/usr/bin/env python3
"""Usage: connect.py [--broker SLUG] [--reconnect AUTHORIZATION_ID] [--connection-type trade|read] [--timeout SECONDS]

Open the SnapTrade Connection Portal to link (or relink) a brokerage, then
poll for up to SECONDS (default 100 — the Bash tool's default timeout is
120s) until the connection appears. Prints the URL first so it can be shown
to the user if auto-open fails. --broker SANDBOX links SnapTrade's simulated
brokerage for testing. --broker ETRADE starts the direct E*Trade
authorization flow instead when ETRADE_CONSUMER_KEY is configured (output
{url, pending, sandbox, opened, broker}); read the printed URL, sign in, then
run etrade-login.py --verifier CODE. ETRADE_SANDBOX is accepted as a spelling
for symmetry but selects nothing: the environment (live or E*Trade sandbox)
comes from ETRADE_SANDBOX in .env. Otherwise it opens the
SnapTrade portal as usual. If the poll times out (CONNECT_TIMEOUT) before the
user finishes in the browser, just run the script again — a new portal URL
is issued (the old one expires after 5 minutes). Output on success:
{url, opened, connection}. Exit codes: 0, 2, 4, 5 (CONNECT_TIMEOUT), 6.
"""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402


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


DEFAULT_TIMEOUT_S = 100.0


def wait(sdk, before, timeout_s: float = DEFAULT_TIMEOUT_S):
    return brokerage.wait_for_connection(sdk, before, timeout_s=timeout_s, interval_s=5)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        broker = reconnect = None
        connection_type = "trade"
        timeout_s = DEFAULT_TIMEOUT_S
        it = iter(args)
        for a in it:
            if a == "--broker":
                broker = next(it, None)
            elif a == "--reconnect":
                reconnect = next(it, None)
            elif a == "--connection-type":
                connection_type = (next(it, None) or "").lower()
                if connection_type not in ("trade", "read"):
                    raise InvalidInput("--connection-type must be trade or read")
            elif a == "--timeout":
                raw = next(it, None)
                try:
                    timeout_s = float(raw)
                except (TypeError, ValueError):
                    raise InvalidInput("--timeout requires a number of seconds")
            else:
                raise InvalidInput("usage: connect.py [--broker SLUG] [--reconnect AUTHORIZATION_ID] [--connection-type trade|read] [--timeout SECONDS]")
        hub = router.load()
        if broker and broker.upper() in ("ETRADE", "ETRADE_SANDBOX") and any(b.name == "etrade" for b in hub.brokers):
            direct = hub.for_broker("etrade")
            started = direct.auth.start()
            sys.stderr.write(f"E*Trade is connected directly. Open this URL, sign in, then run etrade-login.py --verifier CODE:\n{started['url']}\n")
            return {"url": started["url"], "pending": True, "sandbox": started["sandbox"], "opened": open_url(started["url"]), "broker": "etrade"}
        sdk = hub.for_broker("snaptrade").sdk
        before = brokerage.list_authorizations(sdk)
        opened_conn = brokerage.open_connection(sdk, broker=broker, reconnect=reconnect, connection_type=connection_type)
        url = opened_conn["url"]
        if opened_conn["connection_type"] != opened_conn["requested_connection_type"]:
            sys.stderr.write(
                f"{broker or 'This brokerage'} offers no trade connection; linking it read-only "
                "(orders cannot be placed through it).\n"
            )
        sys.stderr.write(f"Open this URL to connect your brokerage (expires in 5 minutes):\n{url}\n")
        opened = open_url(url)
        found = wait(sdk, before, timeout_s)
        if found is None:
            raise ApiError(
                f"no new connection appeared within {timeout_s:g} seconds; run connect.py again",
                code="CONNECT_TIMEOUT",
                connection_type=opened_conn["connection_type"],
                url=url,
                opened=opened,
            )
        return {
            "url": url,
            "opened": opened,
            "connection_type": opened_conn["connection_type"],
            "requested_connection_type": opened_conn["requested_connection_type"],
            "connection": found,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
