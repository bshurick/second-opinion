# Second Opinion - Finance

**A principled second opinion on every money decision.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/bshurick/second-opinion/actions/workflows/ci.yml/badge.svg)](https://github.com/bshurick/second-opinion/actions/workflows/ci.yml)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757.svg)](https://claude.com/claude-code)

Second Opinion is a Claude Code plugin for your own finances. It reads the brokerage accounts you connect and the statements and exports you give it, and works through questions about your portfolio, taxes, debt, home, and retirement together. The calculations are done by Python scripts bundled with the plugin rather than by the model, and your keys and records stay in files on your machine; this project runs no server and has no account of its own. It is built to analyze, not to advise: the skills are written to lay out the numbers, the cases for and against, and the risks, and not to say buy, sell, or hold.

![Portfolio brief for a sample household](docs/images/portfolio-brief.png)

- "How is my portfolio doing today?"
- "What happens to my portfolio if 2008 repeats?"
- "What's a fair price for COST?"
- "I'm 38 with $400k saved. Am I on track to retire at 60?"
- "I'm moving. Run the numbers on selling my condo versus renting it out: cap rate, cash flow, IRR over ten years."
- "Buy 10 shares of VTI in my E*Trade account." Claude previews the order, and nothing is sent until you say yes and approve the command.

```
/plugin marketplace add bshurick/second-opinion
/plugin install second-opinion@second-opinion
/reload-plugins
```

Then say **"get started with Second Opinion"**.

> This is an independent open-source project by an individual. It is not affiliated with, endorsed by, or supported by Anthropic, SnapTrade, E*Trade, Yahoo, the SEC, the Federal Reserve Bank of St. Louis, or any brokerage. Nothing here is financial, tax, or legal advice; see [Safety and disclaimer](#safety-and-disclaimer).

## Install

**Requirements:** [Claude Code](https://claude.com/claude-code) and Python 3.10+ on your PATH. A brokerage key is optional: the research, planning, and learning skills need none. For your own accounts you need a free SnapTrade Personal API key, which means creating a SnapTrade account, or an E*Trade developer key ([how to get one](docs/connecting-brokerages.md)).

In Claude Code:

```
/plugin marketplace add bshurick/second-opinion
/plugin install second-opinion@second-opinion
/reload-plugins
```

Then say **"get started with Second Opinion"**. Every skill is installed. The session-start hook builds the Python virtualenv the first time a session starts.

**Keys.** Run this in your own terminal, not in the chat. It hides what you type and saves the keys in the data directory's `.env`; add `--broker etrade` for an E*Trade key. No Node is needed.

```bash
python3 ~/.claude/plugins/marketplaces/second-opinion/skills/get-started/scripts/configure.py keys
```

**Update:** run `claude plugin marketplace update second-opinion`, then `claude plugin update second-opinion@second-opinion`, then restart Claude Code. The next session prints "Second Opinion updated to X". Say "is there an update" in Claude to see the installed and latest versions.

Uninstall with `/plugin uninstall second-opinion@second-opinion`.

Installing from a git checkout with the guided installer (`node install.js`), and scripted installs, are in [docs/install.md](docs/install.md#from-a-checkout).

### Settings and upgrades

Both routes keep `.env` (your keys), `installed.json` (the installed skills) and `settings.json` (every setting) in `~/.claude/plugins/data/second-opinion/`, or `$SECOND_OPINION_DATA` if set, so they survive plugin updates. `settings.json` has groups for depth, accounts and their roles, the portfolio plan, taxes, guardrails, replies and lessons. Say "show my settings" in Claude to see each one with its default marked, or "change a setting" to set one. Depth is standard by default: quick answers, with a deep run when you ask for one. Set it to deep ("change depth") and every valuation or stock pick is the researched kind, at minutes and 5 to 40 research subagents per run; see [docs/configuration.md](docs/configuration.md#depth). An older install is carried over on first use: `core-satellite.json` and `targets.json` are renamed to `.migrated` (nothing is deleted). Your profile, ledger, watchlist, and other records live there too. A setting in the process environment wins over the data directory's `.env`, which wins over a `.env` in the plugin root. See [docs/configuration.md](docs/configuration.md).

## Start here

1. Say **"get started with Second Opinion."** One conversation, a step at a time, each one skippable: it checks the install, tells you how to add keys, connects your brokerage (your password never reaches Claude or this plugin), confirms a role for each account, picks the research depth, records your plan (employer stock, the picks' share, a cash reserve, short-term gains) and asks three questions about how you invest. Stop at any step and say it again later to pick up there.
2. Ask **"How is my portfolio doing?"** for the daily brief, or **"check in"** for the brief, your plan and what arrived since last time, then anything in [docs/examples.md](docs/examples.md).

## What it looks like

Skills that produce a report publish an interactive page, hosted as a private Artifact on your claude.ai account: sortable tables, charts, plain-language explanations of each card, light and dark themes. You can ask Claude to change a page, or skip pages and ask for an answer in chat.

> The screenshots show a made-up household: three "Sample" accounts with invented balances and trades, rendered by each skill's real page renderer from the fixtures in [docs/samples](docs/samples). Pages are cropped to their top sections.

<details>
<summary><b>Risk and stress test</b> (risk-analysis): volatility, beta, drawdown, VaR, risk contribution, crash replays</summary>

![Risk and stress test for a sample household](docs/images/risk-analysis.png)

</details>

<details>
<summary><b>Valuation</b> (valuation): margin of safety by method, DCF with a growth sensitivity grid</summary>

![Valuation page for COST with invented financials](docs/images/valuation.png)

</details>

<details>
<summary><b>Retirement projection</b> (retirement): Monte Carlo success odds, nest egg required, guardrails</summary>

![Retirement projection for a sample household](docs/images/retirement.png)

</details>

<details>
<summary><b>Rebalancing plan</b> (portfolio-plan): drift against bands, contribution routing, tax-aware trade list</summary>

![Rebalancing plan for a sample household](docs/images/rebalancing.png)

</details>

<details>
<summary><b>Fixed income</b> (fixed-income): what a bond fund earns if held, against cash, and what a rate move does</summary>

![Fixed income page for a sample bond fund](docs/images/fixed-income.png)

</details>

<details>
<summary><b>Spending review</b> (spending): category drill-down, monthly cash flow, what changed</summary>

![Spending review for a sample month](docs/images/spending.png)

</details>

## Skills

23 skills. `get-started` is always installed. `trade-journal` is an optional extra that is on by default and adds a confirmation step to every buy. `financial-education` and suggested follow-up questions are opt-in extras; the follow-up questions are not a skill but an instruction loaded at session start. **key** means a SnapTrade or E*Trade key; **EDGAR** means an SEC contact address in `EDGAR_USER_AGENT`.

| Family | Skill | What it does | Needs |
|---|---|---|---|
| Getting started | get-started | The first run (keys, accounts and their roles, depth, the plan, three profile questions), settings, extras and repairs | |
| Accounts and holdings | connect | Link, relink, or inspect brokerage connections | key |
| | portfolio-analysis | The daily brief of every account with headlines from the other skills, "check in", allocation, concentration, performance against a benchmark, a deep review of the beliefs your holdings share | key |
| | dividend-income | Projected income, yields, trailing 12 months, ex-dates, payer safety | key |
| | watchlist | Alert rules checked when you ask or by a cron job, not pushed | |
| | risk-analysis | Volatility, beta, correlation, drawdown, VaR, crash replays, what-if shocks | key |
| History and decisions | statement-import | Local ledger from CSV exports or two years of SnapTrade activity | key |
| | trade-review | Round trips, win rate, disposition effect, buy-and-hold counterfactuals, a deep review of skill against luck | |
| | trade-journal (extra, on by default) | Thesis, target, and exit written down; checked before each buy | trade-review |
| | tax-aware | Realized gains with wash sales, open lots, estimated tax, harvesting, lot choice, a deep comparison of multi-year plans | |
| | spending | Card and bank exports or transcribed receipts; categories, recurring charges, cash flow | |
| Planning | portfolio-plan | One plan with the picks as a sleeve: drift, 5/25 bands, deposits routed (picks first while below their target), withdrawals, tax-aware sells, picks split equally, by market cap, by deep valuation or by size, new picks, a target with a date | key |
| | retirement | Monte Carlo projection, nest egg required, withdrawal rates | key |
| | real-estate | Mortgage, refinance, rent vs buy, rental underwriting, affordability, REIT metrics, a deep review of one property or market | |
| | personal-finance | Budgeting, cash-flow planning, reminders, and debts: card and loan statements recorded from PDFs, balances, APRs, interest paid, payoff order | |
| Research and markets | valuation | DCF, dividend discount, multiples, Graham and Buffett intrinsic value, and a [deep mode](#deep-research) that researches filings and values named scenarios | deep mode: EDGAR |
| | fundamental-research | SEC EDGAR financials, quality checklist, 10-K/10-Q reader, 13F diffs | EDGAR |
| | stock-screener | Every US-listed company's filings screened seven ways (growth, value, quality, GARP, magic formula, Graham, payout), a look-back check on past picks, a [deep picker](#deep-research), and re-checks of saved picks against their valuation | EDGAR |
| | options | Chains, implied volatility, expected move, greeks, payoffs | |
| | trading | Price action and technicals for one security, and every order: preview, confirmation, placement, cancellation | key |
| | market-analysis | Indices, sectors, yields, earnings calendar, market flows | |
| | fixed-income | What bonds earn held to your horizon, and the rate path the price implies | |
| Learning | financial-education (extra) | One concept at a time with worked numbers, sources, and quizzes | |

Every script behind these skills, with flags and exit codes, is in [docs/scripts.md](docs/scripts.md).

## Deep research

Six modes go beyond the scripted answers. Research subagents work through primary sources and the news, so a run takes longer and uses much more of your Claude usage than an ordinary question.

| Mode | Ask | What you get | Typical run | Needs |
|---|---|---|---|---|
| Deep valuation | *"Do a deep dive on PHM: what has to go right, and what would I earn at today's price?"* | Three to five scenarios valued by segment, each with its return at today's price and what has to be true | 10 to 15 subagents, 30 searches | SEC EDGAR |
| Deep picker | *"Find me the best opportunities right now: run the deep picker."* | A market scan and screens narrowed to three to five finalists, each with a deep valuation | 30 to 40 subagents, 160 searches | SEC EDGAR |
| Portfolio review | *"Run a deep review of my portfolio: what single belief do I depend on most?"* | The beliefs your holdings and income share, with how much rests on each and what you would lose if it were wrong | 8 subagents, 40 searches | SEC EDGAR |
| Property review | *"Run a deep review of 12 Main Street as a rental. The HOA papers and inspection report are in ~/Documents/condo."* | Named scenarios from your documents and local data, the weakest input that matters most, and the break-even price | 6 subagents, 35 searches | |
| Decision review | *"Run a deep review of my trades: which were skill and which were luck?"* | Your largest trades graded without seeing the result, then sorted into skill, luck, bad luck or mistake | 10 subagents, 30 searches | Imported ledger |
| Tax plan comparison | *"Run a deep tax review: compare selling my stock awards over three years against converting to a Roth."* | Multi-year plans compared on after-tax wealth, and which assumption decides the comparison | 5 subagents, 20 searches | Imported ledger |

- **The numbers.** Scripts do the math, and each claim or rule carries a source and date. Scenarios and assumptions are the model's judgment, so read the sources behind them.
- **The deep picker's test.** A finalist becomes a pick only if no scenario loses money over five years, dividends included, and the central scenario earns at least 10% a year at today's price. Passing means it clears the test on those scenarios, not that the return will happen.
- **No calls.** The portfolio, property and tax modes make no buy, sell or plan calls. The property review is not an appraisal or inspection, and the tax comparison is not a return or tax advice.
- **Your details.** Holding values, income, account names and your name stay out of every search.

Saved results can be checked later without rerunning the research. Each check says when a new run is due.

| Check | Ask | What it does |
|---|---|---|
| Picks | *"How are my picks doing?"* | Compares the latest quarters with each scenario and places today's price against the valuation. A notice at session start names picks due after earnings, a 15% price move or a new price level. |
| Portfolio | *"Re-check my deep review"* | Re-measures each bet against what you hold then |
| Property | *"Re-check my review of 12 Main Street: rates are now 6%"* | Reruns the numbers with what changed |
| Trades | *"Re-check my decision review"* | Keeps every grade frozen and re-measures the results |
| Tax plans | *"Re-check my tax plans"* | Reruns the saved plans on your current lots and lists this year's actions |

## Why use it

- **Your whole picture, not one account.** Retirement, real estate, taxes, debt, and the portfolio are one problem. The same session can price a rental, size the tax cost of funding it from taxable lots, and rerun the retirement projection.
- **Your actual holdings.** Account answers start from live positions, balances, and history across every brokerage you connect, aggregated by symbol.
- **Numbers from code.** Scripts fetch the data and do the math (IRR, VaR, DCF, wash-sale matching, Monte Carlo); Claude runs them and explains the result. The same question on two days gives the same layout with fresh figures. Three things are still the model's work: reading the figures off a statement PDF or a receipt you hand it (a recorded statement must balance to the cent before it is stored), the research and scenarios behind a [deep valuation](#deep-research), and anything you ask outside what the scripts cover.
- **Analysis, not advice.** The skills are written to give the data, the cases for and against, and the risks, and to leave out buy, sell, or hold calls. The decision is yours. It is not a signal generator or a trading bot; even the stock screener ranks companies by what the price implies and hands them to research, not to an order. A model can still stray from its instructions, so treat what it says as analysis to check.
- **Local files, and a clear list of what is not local.** Keys sit in a `.env` you own and records are JSON files on your disk. What leaves your machine:
  - requests to the data providers: SnapTrade or E*Trade for your accounts, Yahoo Finance, SEC EDGAR, and FRED for market data;
  - web searches and page fetches during deep research, run through Claude Code's own tools;
  - the conversation with the model, which includes the script results Claude reads: Anthropic's by default, or an [open model through Ollama](docs/ollama.md), which can keep it local;
  - report pages, which Claude Code publishes as private Artifacts on your claude.ai account. Ask for the answer in chat if you do not want a page published.

**How it differs.** Anthropic's financial-services plugins are built for analysts at firms; Second Opinion is for your own household. SnapTrade's hosted, read-only [MCP server](https://docs.snaptrade.com/docs/mcp-server) shows balances and positions in chat with no API key and is simpler if that is all you want; it does no analysis and cannot place orders. This plugin adds the analysis, a local ledger that outlives SnapTrade's two-year activity window, and gated order preview and placement, which is why it uses a Personal API key (or E*Trade's own API) rather than OAuth.

## Safety and disclaimer

**How trading works.** The `trading` and `portfolio-analysis` skills follow this protocol:

1. No order is placed until its preview has been shown in the chat and you have said yes in your own message.
2. A confirmation covers only the orders in the preview it answers. `confirm` places all of them, sells first, and `yes SYMBOL` places one. If an order fails, the rest are not placed.
3. The account's trading support is checked before any preview; read-only connections cannot trade.
4. For a cash or unknown account, orders larger than the cash balance get a warning, and margin is never inferred from buying power.
5. If the order script reports an error, the error is shown and nothing is placed.

**The hard gate.** On top of that protocol, the plugin's PreToolUse hook (`hooks/gate.sh`) makes Claude Code ask you to approve every command that would place or cancel an order or disconnect a brokerage (any run with `--confirm`), even when Claude Code would otherwise run it without asking. In bypass-permissions mode it blocks those commands outright, since a hook cannot ask there. The place-order script re-runs the preview immediately before placing, so the trade id may differ from the one in the chat preview; that is expected.

**Disclaimer.** This is an open-source personal project released under the [MIT License](LICENSE): provided as-is, with no warranty of any kind and no guarantee that it works correctly, completely, or at all. Nothing here is financial, investment, tax, or legal advice. By using it you accept that:

- **Orders are real.** With a trade-enabled connection, a confirmed order goes live to your brokerage. The only practice environments are SnapTrade's read-only `SANDBOX` brokerage and E*Trade's sandbox (`ETRADE_SANDBOX=1`), which use fake accounts.
- **The AI can be wrong.** A language model can misread a request, mix up a ticker, quantity, or side, misinterpret a preview, or act on stale or delayed data. The protocol and the gate reduce this risk; they do not remove it. Read every preview yourself before approving.
- **Bugs happen.** This code, the SnapTrade SDK and service, E*Trade's API, Yahoo Finance data, and your brokerage can each fail or return wrong data, and those failures can cost money.
- **You are responsible.** The author and contributors accept no liability for any loss, damage, missed trade, unintended trade, tax consequence, account restriction, or anything else arising from use of this software, whether caused by the code, the model, the data, or the services it depends on.
- **Third-party terms apply.** Your use of SnapTrade, E*Trade, Yahoo Finance, SEC EDGAR, FRED, and your brokerage is governed by their terms, not this project's.

Sensible precautions: connect accounts read-only unless you need to trade; keep trading to one account with a size you can afford to lose; start with small orders; check your brokerage's own order history after any trade. To report a security issue, see [SECURITY.md](SECURITY.md).

## Documentation

- [Installing](docs/install.md): marketplace and guided installs, scripted and CI flags, manual install, uninstalling
- [Connecting brokerages](docs/connecting-brokerages.md): SnapTrade, E*Trade direct, read-only and margin accounts
- [Configuration](docs/configuration.md): every environment variable and where settings live
- [Example questions](docs/examples.md): what to ask each skill
- [Running on open models with Ollama](docs/ollama.md)
- [Running the scripts yourself](docs/running-scripts.md)
- [Script reference](docs/scripts.md): every script, its flags and exit codes
- [How skills are written](docs/skill-style.md): the layout every skill follows
- [Troubleshooting](docs/troubleshooting.md)

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: create a virtualenv, `pip install -r requirements-dev.txt`, and run `python -m pytest tests -q`. The installer is TypeScript under [installer/](installer/README.md); after changing it, run `cd installer && npm ci && npm run check`, which also rebuilds the committed `install.js`.

## License

MIT. See [LICENSE](LICENSE).
