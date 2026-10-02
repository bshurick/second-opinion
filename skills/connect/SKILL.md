---
name: connect
description: Links, relinks, or inspects brokerage connections through SnapTrade or E*Trade direct login (daily re-auth). Use when the user asks to connect a brokerage, reconnect, see which accounts are connected, or when a brokerage script exits with code 4 or 5.
---
Connects the user's brokerage accounts through SnapTrade, or directly with their own E*Trade developer key, so the other finance skills can read holdings and place orders. Everything happens in the user's own browser; the brokerage login is never seen here.

## Background

- **Two routes.** SnapTrade links a brokerage through a hosted portal. E*Trade direct uses the user's own developer key, stored in `.env`.
- **SnapTrade connection types.** A connection's `type` is `"trade"` or `"read"`. A `type: "read"` connection cannot place orders.
- **SnapTrade portal URL.** `connect.py` prints the portal URL to stderr and as `url` in its JSON. Auto-open can fail. The URL expires after 5 minutes.
- **Polling.** `connect.py` polls for up to 100 seconds (`--timeout`); the Bash tool's default timeout is 120 s.
- **SnapTrade sandbox.** `--broker SANDBOX` links SnapTrade's simulated brokerage, so nothing real is touched. SANDBOX offers no trade connection: the script links it read-only (output `connection_type: "read"`), so orders cannot be tested there.
- **Probe.** `status.py --probe` makes one lightweight holdings call per connection and reports `healthy`, `disabled`, `stale`, `error` or `no_accounts` per authorization. It confirms a connection still works, not just that it exists.
- **Direct rows.** When `status.py` shows a `direct` row with broker `etrade`, that brokerage is served by the user's own developer key, not SnapTrade. Its `status` is `usable`, `expired`, or `none`.
- **E*Trade token life.** E*Trade tokens expire at midnight Eastern every day, so a login is expected once per trading day. Idle tokens renew on their own.
- **E*Trade environment.** `ETRADE_SANDBOX=1` in `.env` points every E*Trade call at E*Trade's sandbox (fake accounts, fake fills) and needs its own login. `--broker ETRADE_SANDBOX` is accepted for symmetry but selects nothing: the environment comes from `ETRADE_SANDBOX` in `.env`.
- **What may be pasted in chat.** The verifier is a one-time code and may be pasted in chat. The authorize URL carries the consumer key, because E*Trade's flow requires it. The consumer SECRET never leaves `.env`.
- **Shadowed accounts.** `accounts.py` and `status.py` return `shadowed`: SnapTrade accounts hidden because a direct broker serves the same brokerage account. `accounts.py --include-shadowed` shows them. The scripts refuse an order through a shadowed account with code `SHADOWED_ACCOUNT` and name the direct account to use.
- **Possible duplicates.** The same two scripts return `warnings`. A `POSSIBLE_DUPLICATE` row is a SnapTrade account at a brokerage a direct adapter also serves whose number matched no direct account, so its holdings may be counted twice.
- **Margin accounts.** Unless `BROKER_ACCOUNT_TYPES=<account_id>=margin` is set in `.env`, previews and orders treat the account as cash and unsettled-cash warnings will be wrong.
- **Code 1083 with no connection.** A bare `snaptrade_code` 1083 with no prior connection at all means the key has no registered user yet. The scripts register one automatically and retry.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/connect/scripts/status.py" [--probe]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/connect/scripts/connect.py" [--broker SLUG] [--reconnect ID] [--connection-type trade|read] [--timeout SECONDS]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/connect/scripts/disconnect.py" <id> --confirm
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/connect/scripts/brokers.py" [--query TEXT]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/connect/scripts/etrade-login.py" [--verifier CODE | --revoke | --status]
```

| Script | What it does |
|---|---|
| `status.py` | Lists connections and accounts, plus `direct`, `shadowed` and `warnings`. `--probe` checks each connection is still healthy. |
| `connect.py` | Opens the SnapTrade portal to link or relink a brokerage, then polls until the connection appears. `--reconnect ID` relinks an existing connection. `--broker ETRADE` starts the E*Trade direct flow when the key is configured (output `pending: true`). |
| `disconnect.py` | Removes one brokerage connection. Without `--confirm` it prints the connection and exits 3. |
| `brokers.py` | Lists every brokerage SnapTrade supports. `--query TEXT` filters by name or slug. A row with `maintenance_mode: true` cannot be linked right now. |
| `etrade-login.py` | E*Trade direct login (developer key in `.env`). No arguments starts the flow and prints the authorize `url`. `--verifier CODE` completes it. `--status` answers "am I logged in" without a network call. `--revoke` signs out. |

All scripts print JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad arguments | `error` |
| 3 | `disconnect.py` ran without `--confirm` | the connection it printed |
| 4 | Credentials missing | `hint`, then stop |
| 4 with code `ETRADE_REAUTH` | An E*Trade login is needed | follow the E*Trade login case below |
| 5 with code `CONNECT_TIMEOUT` | The poll ended before the user finished in the browser | run `connect.py` again |
| 5 (other) | Brokerage API error | `error`; run `status.py` first |
| 6 | Python dependencies not installed | `requirements` and `install_log` |

## Steps

Always start with step 1, then pick the case that matches the request.

1. Run `status.py`. Add `--probe` when you need to confirm a connection still works.
2. If the user already has the connection they want, say so and stop.
3. If `shadowed` is not empty, tell the user once which rows were hidden.
4. If `warnings` has a `POSSIBLE_DUPLICATE` row, show those rows and ask the user whether it is the same account before trusting the totals.

**The user wants to link a brokerage through SnapTrade**

1. If they ask "can I link X?", run `brokers.py --query X` and answer from its data. Check it before telling a user a brokerage isn't supported.
2. Run `connect.py`, with `--broker SLUG` when the brokerage is known. Use `--broker SANDBOX` for a first smoke test.
3. Always show the `url` in the chat.
4. If the user wants trading, say the portal must be completed with trade permission.
5. If the script exits with `CONNECT_TIMEOUT` before the user has finished in the browser, run it again and show the new portal URL.
6. After connecting a MARGIN account, tell the user to set `BROKER_ACCOUNT_TYPES=<account_id>=margin` in `.env`. The `account_id` comes from `status.py` or `accounts.py`.

**The user wants trading on a read-only connection**

1. Run `connect.py --reconnect <id>` to upgrade the existing read-only connection.
2. Continue from step 3 of the SnapTrade case.

**A connection no longer works**

This case applies when a downstream script fails with `snaptrade_code` 1083, HTTP 401/403 on an account call, or `status.py --probe` reports a connection as `stale`.

1. If it is a bare 1083 with no prior connection at all, tell the user to rerun the command that failed. Stop here.
2. Otherwise prescribe `connect.py --reconnect <authorization_id>` before anything else. That credential no longer works.

**E*Trade direct login**

This case applies when the `direct` row's `status` is `expired` or `none`, when any script exits 4 with code `ETRADE_REAUTH`, or when the user asks to connect E*Trade.

1. Get the authorize URL: it is the `url` in the failed script's output. To start fresh, run `etrade-login.py` with no arguments or `connect.py --broker ETRADE`; either entry point works.
2. Show the `url`.
3. Tell the user to sign in at E*Trade and read the 5-character verifier code.
4. Ask them to paste the code.
5. Run `etrade-login.py --verifier CODE`.
6. Rerun the command that failed, once.
7. If the user declines the login, rerun that command once with the `--partial` flag the output names.

**The user wants to remove a connection**

1. Show which brokerage will be removed.
2. Wait for the user to say yes in their own message.
3. Run `disconnect.py <id> --confirm`.

## Rules

- Never run `disconnect.py --confirm` until you have shown which brokerage will be removed and the user has said yes in their own message.
- Never place an order through a shadowed SnapTrade account.
- Neither E*Trade key is ever pasted in chat. They go in `.env` via `node install.js`.
- Always show the portal or authorize URL in the chat, because auto-open can fail.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
