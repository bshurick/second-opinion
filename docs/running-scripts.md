# Running the scripts yourself

Every skill's scripts can be run directly from the repository root. Each prints one JSON object and uses the exit codes in [scripts.md](scripts.md). Inside Claude Code the session-start hook sets `SNAPTRADE_PY` to the plugin's virtualenv interpreter; outside it, point `PY` at `~/.claude/plugins/data/second-opinion/venv/bin/python` or any Python with `requirements.txt` installed.

## SnapTrade sandbox smoke test

```bash
PY="${SNAPTRADE_PY:-python3}"
$PY skills/connect/scripts/connect.py --broker SANDBOX   # opens the portal; finish it in the browser
$PY skills/connect/scripts/status.py
$PY skills/portfolio-analysis/scripts/accounts.py        # copy the account_id values you need
$PY skills/portfolio-analysis/scripts/portfolio.py <account_id>
$PY skills/portfolio-analysis/scripts/quote.py AAPL
```

`--broker` takes SnapTrade's brokerage slug (`ETRADE`, `FIDELITY`, `SCHWAB`, `ROBINHOOD`, `SANDBOX`, ...); omit it to choose in the portal. `--connection-type read` makes a read-only connection; `--reconnect <authorization_id> --connection-type trade` upgrades one later, using the id shown by `status.py`.

## E*Trade direct against its sandbox

With `ETRADE_SANDBOX=1` in `.env`:

```bash
$PY skills/connect/scripts/etrade-login.py                       # prints the authorize URL
$PY skills/connect/scripts/etrade-login.py --verifier CODE       # paste the code E*Trade shows you
$PY skills/portfolio-analysis/scripts/accounts.py
$PY skills/portfolio-analysis/scripts/portfolio.py <account_id>
$PY skills/portfolio-analysis/scripts/quote.py AAPL
$PY skills/trading/scripts/preview-order.py <account_id> AAPL BUY 1 --type LIMIT --limit 1
$PY skills/trading/scripts/orders.py <account_id>
```

`place-order.py`, `cancel-order.py`, and `disconnect.py` act only with `--confirm`; without it they print what they would do and exit 3. Run from your own terminal, the hard gate in `hooks/gate.sh` does not apply, since it is a Claude Code hook.
