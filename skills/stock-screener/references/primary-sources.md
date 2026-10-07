# Primary sources catalog

Where the deep picker's subagents and coordinator fetch dated industry and macro data before spending a web search. Each row names the data, its publisher, a URL to fetch directly, how often it updates, and the date the URL was last checked. Only rows with a date were fetched on that date (the page answered HTTP 200); "unchecked" rows were not fetched and may need a one-search fix.

## Contents
- Macro and rates
- Group 1: Technology, Communication Services, Consumer Discretionary, Consumer Staples
- Group 2: Health Care, Financials, Real Estate, Utilities
- Group 3: Industrials, Energy, Materials
- Company pages
- Keeping the catalog current

## Macro and rates

| Data | Publisher | URL (template) | Updates | Checked |
|---|---|---|---|---|
| 10-year Treasury yield (DGS10) | FRED | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10` | Daily | unchecked |
| BBB corporate effective yield (BAMLC0A4CBBBEY) | FRED | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A4CBBBEY` | Daily | unchecked |
| Consumer price index release | BLS | `https://www.bls.gov/news.release/cpi.nr0.htm` | Monthly | unchecked |
| Implied equity risk premium | Damodaran, NYU Stern | `https://pages.stern.nyu.edu/~adamodar/` | Monthly | 2026-10-06 |
| S&P 500 earnings estimates and revisions | FactSet Earnings Insight | `https://insight.factset.com/topic/earnings` | Weekly | 2026-10-06 |

Any other FRED series fits the same template: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES`.

## Group 1: Technology, Communication Services, Consumer Discretionary, Consumer Staples

| Data | Publisher | URL (template) | Updates | Checked |
|---|---|---|---|---|
| Advance monthly retail sales | Census Bureau | `https://www.census.gov/retail/marts/www/marts_current.pdf` | Monthly | 2026-10-06 |
| Worldwide semiconductor sales and forecast | WSTS | `https://www.wsts.org/` | Monthly, forecast twice a year | 2026-10-06 |
| TSA checkpoint passenger throughput | TSA | `https://www.tsa.gov/travel/passenger-volumes` | Daily | 2026-10-06 |
| Consumer price index, by category | BLS | `https://www.bls.gov/news.release/cpi.nr0.htm` | Monthly | unchecked |

## Group 2: Health Care, Financials, Real Estate, Utilities

| Data | Publisher | URL (template) | Updates | Checked |
|---|---|---|---|---|
| Bank earnings, margins and credit quality | FDIC Quarterly Banking Profile | `https://www.fdic.gov/quarterly-banking-profile` | Quarterly | 2026-10-06 |
| REIT earnings, returns and sector data | Nareit | `https://www.reit.com/data-research` | Quarterly and monthly | 2026-10-06 |
| Power-market load and price outlook | PJM Inside Lines | `https://insidelines.pjm.com/` | Irregular | 2026-10-06 |
| Electricity demand and price outlook | EIA Short-Term Energy Outlook | `https://www.eia.gov/outlooks/steo/` | Monthly | 2026-10-06 |

## Group 3: Industrials, Energy, Materials

| Data | Publisher | URL (template) | Updates | Checked |
|---|---|---|---|---|
| Oil, gas, coal and power outlook | EIA Short-Term Energy Outlook | `https://www.eia.gov/outlooks/steo/` | Monthly | 2026-10-06 |
| Weekly rail traffic | AAR | `https://www.aar.org/data-center/rail-traffic-data/` | Weekly | 2026-10-06 |
| Construction spending | Census Bureau | `https://www.census.gov/construction/c30/current/index.html` | Monthly | 2026-10-06 |
| Industrial production, manufacturing (IPMAN) | FRED | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=IPMAN` | Monthly | unchecked |

## Company pages

- Company investor-relations pages: take `info.website` from the valuation skill's `fundamentals.py SYMBOL` and look for the investor-relations link on it. Presentations, earnings slides and segment data sit there.
- Earnings releases and the filing text come only through the SEC scripts (`earnings.py`, `filing.py`), not through a URL.

## Keeping the catalog current

A moved or retired URL costs one search to find the new address. Then update the catalog row (the URL and the Checked date) in the same run, so the next run fetches directly.
