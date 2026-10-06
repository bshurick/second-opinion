# Changelog

## Unreleased

- valuation: deep mode. Research subagents read the filings and news, keep a sourced belief ledger, chase the contested beliefs, and value three to five named scenarios segment by segment (`model.py`), with the annualized return at today's price for each (`returns.py`) on a new page (`render_deep.py`).
- valuation: quick mode shows the bear, base and bull annualized return at today's price.
- valuation: deep mode reports what today's price implies, values banks, insurers and utilities on book value and ROE with matching charts and sensitivity axes, and its research follows blind-spot rules (structural-threat checklist, a source arguing the other side, a blind-spot thread each round).
