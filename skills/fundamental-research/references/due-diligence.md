# Red-Team Due Diligence

A protocol for the adversarial pass on a company whose case has already been
written — a held position, a planned one, or a screen hit the user wants
stress-tested. The job is to find every credible reason the case could be
wrong, not to restate it. Every step names a source, every finding carries a
date, and the output is ranked so the reader sees the worst first. Analysis
only: never recommend, advise, suggest, or say what the user should do.

## Contents

- Ground rules
- 1. Eight-quarter trend table by business type
- 2. Filings: what changed and what management says
- 3. Management, governance and pay
- 4. Insiders and holders
- 5. External risks with dated sources
- 6. Thesis breakers and early warnings
- 7. Findings ranked by severity
- 8. Case-flaw risk score
- 9. Output shape

## Ground rules

- Assume the favourable case is already written; do not repeat it. Read it
  first so each finding attacks a specific claim in it.
- Numbers come from the scripts (`edgar.py --quarters 8`, `filing.py`), never
  from memory. When XBRL lacks a metric, take it from the 10-Q or 10-K text and
  say which Item it came from.
- Every external item carries its publication date and source. Discard
  anything that cannot be dated to the last twelve months, or label it
  "background (DATE)".
- Skip a step only when the source does not exist for this company (a
  foreign private issuer with no proxy, a company with no Form 4 activity) and
  say so in the output.
- One `edgar.py` run, at most four `filing.py` calls, three to five web
  searches. Budget the calls before starting.

## 1. Eight-quarter trend table by business type

Run `edgar.py <symbol> --quarters 8` and build a table of the six to ten
metrics that matter for *this* business, oldest to newest, marking each row
improving / flat / deteriorating. Generic revenue and net income are the
floor, not the table. Pick the row set by business type:

| Business | Rows that matter |
|---|---|
| Insurer / mortgage insurer | premiums earned, losses incurred, loss ratio, new notices of default, reserve releases or strengthening, book value per share |
| Bank | net interest margin, non-performing loans, net charge-offs, provision for credit losses, commercial real estate share of loans, deposit cost and mix (non-interest-bearing share), CET1, book value per share |
| Card or consumer lender | net charge-off rate, 30+ day delinquency, reserve rate, purchase volume, net interest yield, partner revenue-sharing payments, CET1 |
| Retailer / consumer | comparable-store sales, gross margin, inventory days, store count, SG&A ratio |
| Industrial / manufacturer | orders and backlog, book-to-bill, gross margin, inventory days, capex vs depreciation |
| Software / subscription | ARR or deferred revenue, net retention, gross margin, SBC as % of revenue, FCF margin |
| Energy / resources | production volumes, realized price, unit costs, reserve replacement, capex vs operating cash flow |
| REIT | occupancy, same-store NOI, FFO per share, debt to EBITDA, weighted lease term |

Where the 10-Q text is the only source for a row (loss ratio, NIM, NPLs),
take it from the MD&A in step 2 and mark the cell's source. A metric that
XBRL and the MD&A disagree on is itself a finding.

## 2. Filings: what changed and what management says

Up to four `filing.py` calls, quoted with filing date and URL:

1. `--form 10-K --item 1A --diff` — the risk language *added* this year.
   Quote the added sentences verbatim; new specific risks (a named regulator,
   a named customer, a lawsuit) rank above boilerplate.
2. `--form 10-Q --item 2` — the latest MD&A: guidance, credit or demand
   trends, management's own caveats, anything "we expect" or "we can provide
   no assurance".
3. One targeted `--search` on the 10-K or 10-Q for the company's known soft
   spot: "reserve", "non-performing", "charge-off", "late fee",
   "concentration", "litigation", "investigation", "subpoena", "going
   concern", "material weakness", "restat", "covenant", "customer
   accounted for".
4. Optional: a second search or the Business Item (`--item 1`) when the
   thesis depends on a segment or contract.

Attribute every quote to its Item (1A Risk Factors, 7 MD&A, 9A Controls).

## 3. Management, governance and pay

From the latest proxy (DEF 14A, URL in the `filings` block) or web sources
dated within the year:

- CEO and CFO: names, tenure, age, any change in the last twelve months, and
  any 8-K Item 5.02 departure.
- Pay versus performance and the say-on-pay approval percentage; a result
  under 70% is a finding.
- Insider ownership percentage; related-party transactions; board
  independence; any controlling holder or dual-class structure.
- Any restatement, material weakness, auditor change, or late filing (NT
  10-K / NT 10-Q) in the period.

## 4. Insiders and holders

From `edgar.py <symbol> --filings-only --form4 10` and web sources:

- Open-market buys (code P) versus sales (code S) over twelve months, with
  dollar amounts; awards, exercises and tax withholding (A, M, F) carry
  little signal and are not counted as either.
- Notable 13F or 13D/G changes: a large holder exiting, an activist arriving.
- Short interest as a percentage of float and its trend; days to cover.

## 5. External risks with dated sources

Three to five web searches covering the last twelve months: lawsuits,
regulatory actions or investigations, rating-agency actions, short-seller
reports, analyst downgrades with the stated reason, competitive or pricing
pressure, and the macro sensitivities specific to the business (housing and
GSE policy for mortgage insurers; commercial real estate and deposit flight
for banks; fee regulation, retail-partner losses and consumer credit stress
for card lenders; input costs and tariffs for manufacturers). Record each
item as: date, source, one sentence.

## 6. Thesis breakers and early warnings

State the two or three specific conditions under which the written case is
wrong, each paired with the metric that would show it first and the
threshold at which it counts. "ROE below 10% for two quarters", "NPLs rising
two consecutive quarters", "net charge-offs above 7%", "a dividend cut" —
numbers the next quarterly run can check, not adjectives.

## 7. Findings ranked by severity

Eight to fifteen findings, each with an area (management, fundamentals,
accounting, regulatory_legal, competitive, insiders, valuation, other), one
sentence stating the finding, one sentence of evidence with date and source,
and a severity:

| Severity | Meaning |
|---|---|
| 5 | Breaks the case on its own if true (going concern, restatement, regulator action against the core business) |
| 4 | Materially weakens a load-bearing claim (a key trend row deteriorating two-plus quarters, a guidance cut) |
| 3 | Worth a line in the write-up; changes the odds, not the conclusion |
| 2 | Context the reader would want; no direct effect on the case |
| 1 | Noted for completeness |

Rank most severe first. A finding without a dated source drops one level.

## 8. Case-flaw risk score

One integer 1-10 for the whole pass: 10 means the written case is very
likely wrong; 1 means nothing material was found. Anchor it to the findings:
any severity-5 finding puts the score at 7 or above; two or more severity-4
findings put it at 5 or above; a pass with nothing above severity 2 stays
under 3. Two or three sentences of bottom line follow the score, using only
the evidence above.

## 9. Output shape

One JSON object (for a downstream step) and one short write-up (for the
reader), same content:

    {"symbol", "as_of",
     "findings": [{"area", "finding", "evidence", "severity"}],   # ranked
     "trend_table": [{"metric", "values": [8 oldest..newest or nulls], "direction"}],
     "management": {"ceo", "ceo_since", "cfo", "cfo_since", "recent_changes",
                    "insider_ownership_pct", "say_on_pay_pct", "governance_flags": []},
     "insiders": {"buys_12m", "sells_12m", "net_dollars", "short_interest_pct"},
     "thesis_breakers": [{"condition", "early_warning_metric"}],
     "case_flaw_risk": 1-10,
     "bottom_line": "two or three sentences"}

The write-up (about 400 words) runs findings by severity with evidence, then
the trend table, management, insiders, thesis breakers and bottom line. It
presents both what held up and what did not; it never recommends an action.
