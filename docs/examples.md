# Example questions

Say these in plain language; Claude picks the skill. Grouped as in the README's skills table.

## Getting started

- **onboarding:** "Get started with Second Opinion." · "Show my profile." · "Update my profile: I hold for shorter now." · "What should I try next?"
- **setup:** "Set up Second Opinion." · "Turn on suggested follow-up questions." · "Reinstall the Python dependencies."

## Accounts and holdings

- **connect:** "Connect my Fidelity account." · "Which accounts are connected?" · "Reconnect E*Trade."
- **portfolio-snapshot:** "How is my portfolio doing today?" · "Give me the daily brief." · "What changed since last week's snapshot?"
- **portfolio-analysis:** "What's my allocation across all my accounts? How concentrated am I?" · "How did my portfolio do against SPY this year?" · "Buy 10 shares of VTI in my E*Trade account."
- **dividend-income:** "How much dividend income will I earn this year, and in which months?" · "Which of my holdings go ex-dividend soon?" · "Have any of my payers cut their dividend?"
- **watchlist:** "Watch PLTR and alert me if it drops below 20 or moves 5% in a day." · "What on my watchlist moved?"
- **risk-analysis:** "How risky is my portfolio?" · "What happens to my portfolio if 2008 repeats? What if NVDA drops 30%?"

## History and decisions

- **statement-import:** "Import this Fidelity CSV export into my ledger." · "Pull two years of activity from my connected accounts."
- **trade-review:** "Review my trades from the last two years." · "Was selling NVDA in March a good call?"
- **trade-journal** (extra): "Journal this trade: buying 100 MSFT at 410, target 460, stop 385, six-month horizon." · "Am I following my plan?"
- **tax-aware:** "What do I owe in capital gains so far this year? Any wash sales?" · "Which lots of AAPL are cheapest to sell, tax-wise?" · "Any losses I could harvest?"
- **spending:** "Import this Amex export." · "Here is my Amazon order list for the month, break the Amazon charges down." · "Where can I cut? Drill into Groceries." · "What subscriptions am I paying for, and which went up?"

## Planning

- **rebalancing:** "I'm targeting 60/40. How far off am I?" · "Where does this $5,000 deposit go?"
- **retirement:** "I'm 38 with $400k saved. Am I on track to retire at 60? What if I put $150k into a house first?" · "What withdrawal rate lasts 35 years?" · "Compare claiming Social Security at 62, 67 and 70."
- **real-estate:** "I'm moving. Run the numbers on selling my condo versus renting it out: cap rate, cash flow, IRR over ten years." · "Rent vs buy on a $750k home at 6.5%, against $3,200 rent." · "Refinance from 6.5% to 5.75%? Where is the breakeven?" · "What are O's FFO and AFFO multiples?"
- **personal-finance:** "Avalanche or snowball on my recorded debts, with $300 extra a month?" · "Build a monthly budget from my cash flow." · "What does $500 a month grow to in 20 years at 7%?"
- **debt-tracker:** "Record this Chase statement: ~/Downloads/statement-aug.pdf." · "What do I owe across my cards and mortgage? What is the monthly interest run rate?"

## Research and markets

- **valuation:** "What's a fair price for COST?" · "Does KO pass Graham's defensive-investor tests? What are its owner earnings and the margin of safety at today's price?"
- **fundamental-research:** "What does Nvidia's latest 10-K say about risk factors?" · "What did Berkshire buy last quarter?"
- **stock-screener:** "Find me companies with strong growth that the market is underpricing." · "Run a value screen: cheap on cash flow, little debt, no dilution." · "Loosen the growth screen to include smaller companies." · "Run the magic formula, leaving out what I already own." · "Does Graham's defensive screen find anything today?" · "How did the quality screen's picks from three years ago do?"
- **options:** "Show me the AAPL option chain for next month and the expected move." · "What's the payoff and breakeven on a 180/190 call spread?"
- **trading:** "Chart AMD's trend. Where are support and resistance?" · "Is MSFT above its 200-day average?"
- **market-analysis:** "How are markets doing today? What is the yield curve saying?" · "How are asset managers positioned in S&P futures?" · "Which earnings are out this week?"
- **fixed-income:** "What will BND earn me a year if I hold it five years, and is that better than cash?" · "What happens to my bond fund if rates go up 1%?" · "What short-rate path is priced into the curve, and how does it compare with the Fed's own projections?" · "Is a 4% T-bill really yielding 4%?"

## Learning

- **financial-education** (extra): "Teach me what a Sharpe ratio is, with a worked example." · "Quiz me on bonds." · "Give me a reading path on value investing."

## How debt tracking works

Card CSV exports carry transactions but never a balance, minimum payment, due date, or APR. Statement PDFs do, in the summary box every US card and loan statement prints, so the debt picture is built from statements, one at a time:

1. "Record this statement: ~/Downloads/statement.pdf." Claude reads the summary box and transcribes about a dozen numbers (previous balance, payments, purchases, interest, fees, new balance, minimum, due date, APR).
2. Before storing anything, the recorder checks the statement's own identity: previous balance minus payments and credits plus purchases, fees, and interest must equal the new balance to the cent. A misread digit fails loudly instead of landing in your data.
3. "What do I owe?" gives balances, APRs, minimums, due dates, utilization, interest this period and over the trailing twelve months, and flags such as a stale statement, a past due date, or minimum-only payments. Mortgages, auto and student loans, and HELOCs sit in the same register as cards.
4. "Avalanche or snowball?" hands the recorded balances, APRs, and minimums to the payoff calculator in personal-finance. Escrow is excluded from a loan's minimum.

Only the last four digits of an account number are stored, and the PDF itself is never copied. Statements live in `statements.json` in the data directory.
