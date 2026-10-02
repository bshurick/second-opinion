# Sample household (fictional)

Every fixture in this directory describes the same made-up household. Nothing here is real:
no real person, account, balance or trade. Values are round and internally consistent so the
README screenshots read as one portfolio.

- As of: 2026-09-15 (a Tuesday). Prices are plausible for that date but invented.
- Person: age 38, retiring at 62, moderate risk, targets 55% US equities / 15% international / 25% bonds / 5% cash.

## Accounts

| Account | Institution | Type | Trading | Value | Cash |
|---|---|---|---|---|---|
| Sample Brokerage | Sample Securities | taxable brokerage | yes | 168,000 | 12,215 |
| Sample Roth IRA | Sample Securities | Roth IRA | no | 74,500 | 3,400 |
| Sample 401(k) | Sample Retirement Plan | 401(k) | no | 170,000 | 6,100 |
| **Total** | | | | **412,500** | **21,715** |

## Holdings

| Account | Symbol | Name | Units | Price | Value | Cost basis | Bucket |
|---|---|---|---|---|---|---|---|
| Sample Brokerage | VTI | Vanguard Total Stock Market ETF | 220 | 312.00 | 68,640 | 52,800 | US equities |
| Sample Brokerage | AAPL | Apple Inc. | 120 | 232.00 | 27,840 | 19,200 | US equities |
| Sample Brokerage | MSFT | Microsoft Corp. | 55 | 505.00 | 27,775 | 18,150 | US equities |
| Sample Brokerage | COST | Costco Wholesale Corp. | 22 | 915.00 | 20,130 | 15,400 | US equities |
| Sample Brokerage | SCHD | Schwab US Dividend Equity ETF | 400 | 28.50 | 11,400 | 10,400 | US equities |
| Sample Roth IRA | VXUS | Vanguard Total International Stock ETF | 600 | 68.00 | 40,800 | 34,200 | international equities |
| Sample Roth IRA | JNJ | Johnson & Johnson | 100 | 165.00 | 16,500 | 15,800 | US equities |
| Sample Roth IRA | VNQ | Vanguard Real Estate ETF | 150 | 92.00 | 13,800 | 13,050 | US equities |
| Sample 401(k) | VTI | Vanguard Total Stock Market ETF | 300 | 312.00 | 93,600 | 66,000 | US equities |
| Sample 401(k) | BND | Vanguard Total Bond Market ETF | 950 | 74.00 | 70,300 | 72,200 | bonds |

Aggregated by symbol: VTI 162,240 (39.3%), BND 70,300 (17.0%), VXUS 40,800 (9.9%), AAPL 27,840 (6.7%),
MSFT 27,775 (6.7%), COST 20,130 (4.9%), JNJ 16,500 (4.0%), VNQ 13,800 (3.3%), SCHD 11,400 (2.8%), cash 21,715 (5.3%).

Current mix: US equities 67.8% (279,685), international 9.9% (40,800), bonds 17.0% (70,300), cash 5.3% (21,715) (over on US, under on bonds and international).

Those are the rebalancing target groups, which put VNQ under US equities. The portfolio brief's own
asset buckets place a real-estate fund under "other", so the brief shows US equities 64.5% and other 3.3%.

## Day moves (2026-09-15)

VTI +0.6%, AAPL +1.8%, MSFT -0.9%, COST +0.4%, SCHD +0.3%, VXUS +0.2%, JNJ -1.4%, VNQ -0.7%, BND +0.1%.

## Other facts fixtures may use

- Retirement: 412,500 saved, 2,000/month contributions, spend 82,000/year in retirement, Social Security 30,000/year from 67, 6.5% nominal return, 2.5% inflation.
- Spending month: August 2026, cards "Sample Visa" and "Sample Amex", checking "Sample Checking"; take-home income 9,800/month.
- Valuation subject: COST at 915.00.
- Debts (if needed): none beyond a 3,200/month mortgage payment.

## How the fixtures are produced

Every generator only does arithmetic through the skills' real code and writes into this directory;
none of them fetches data or reads anything from a user's plugin data directory.

| Fixture | Source |
|---|---|
| `portfolio-brief.json` | `gen_portfolio_brief.py`: real summary math and rebalancing headline; news, events, other headlines and coverage invented |
| `rebalancing.json` | `gen_rebalancing.py`: real plan math; suggested bands invented |
| `valuation.json` | `gen_valuation.py`: invented COST-shaped financials through the real valuation functions |
| `spending-month.json`, `spending-changes.json` | `gen_spending.py`: invented ledger through the real report code |
| `retirement.json` | `retire.py`, command below |
| `risk-analysis.json` | hand-written against `risk.py`'s output contract |

`retire.py` with explicit savings needs no brokerage, network, profile or data directory, so the
fixture is its real output, run in an empty environment:

```
env -i PATH=/usr/bin:/bin HOME="$TMP" SECOND_OPINION_DATA="$TMP/fa-data" \
  python3 skills/retirement/scripts/retire.py --savings 412500 --age 38 --retirement-age 62 \
  --end-age 92 --contribution 24000 --return 0.065 --inflation 0.025 --spending 82000 \
  --other-income 30000 --other-income-start-age 67 --guardrail-cut 0.10 --guardrail-trigger 0.20 \
  --seed 42 --simulations 2000 > docs/samples/retirement.json
```

After changing a fixture or a renderer, rebuild the images with `python3 docs/samples/build_screenshots.py`.
