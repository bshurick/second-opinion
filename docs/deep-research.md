# Deep research

Six modes go beyond the scripted answers. Research subagents work through primary sources and the news, so a run takes longer and uses much more of your Claude usage than an ordinary question.

## The modes

| Mode | Ask | What you get | Typical run | Needs |
|---|---|---|---|---|
| Deep valuation | *"Do a deep dive on PHM: what has to go right, and what would I earn at today's price?"* | Three to five scenarios valued by segment, each with its return at today's price and what has to be true | 8 to 11 subagents, 25 searches | SEC EDGAR |
| Deep picker | *"Find me the best opportunities right now: run the deep picker."* | A market scan and screens narrowed to three to five finalists, each with a deep valuation | 25 to 35 subagents, 127 searches | SEC EDGAR |
| Portfolio review | *"Run a deep review of my portfolio: what single belief do I depend on most?"* | The beliefs your holdings and income share, with how much rests on each and what you would lose if it were wrong | 8 subagents, 40 searches | SEC EDGAR |
| Property review | *"Run a deep review of 12 Main Street as a rental. The HOA papers and inspection report are in ~/Documents/condo."* | Named scenarios from your documents and local data, the weakest input that matters most, and the break-even price | 6 subagents, 35 searches | |
| Decision review | *"Run a deep review of my trades: which were skill and which were luck?"* | Your largest trades graded without seeing the result, then sorted into skill, luck, bad luck or mistake | 10 subagents, 30 searches | Imported ledger |
| Tax plan comparison | *"Run a deep tax review: compare selling my stock awards over three years against converting to a Roth."* | Multi-year plans compared on after-tax wealth, and which assumption decides the comparison | 5 subagents, 20 searches | Imported ledger |

## What to know

- **The numbers.** Scripts do the math, and each claim or rule carries a source and date. Scenarios and assumptions are the model's judgment, so read the sources behind them.
- **The deep picker's test.** A finalist becomes a pick only if no scenario loses money over five years, dividends included, and the central scenario earns at least 10% a year at today's price. Passing means it clears the test on those scenarios, not that the return will happen.
- **No calls.** The portfolio, property and tax modes make no buy, sell or plan calls. The property review is not an appraisal or inspection, and the tax comparison is not a return or tax advice.
- **Your details.** Holding values, income, account names and your name stay out of every search.

## Re-checks

Saved results can be checked later without rerunning the research. Each check says when a new run is due.

| Check | Ask | What it does |
|---|---|---|
| Picks | *"How are my picks doing?"* | Compares the latest quarters with each scenario and places today's price against the valuation. A notice at session start names picks due after earnings, a 15% price move or a new price level. |
| Portfolio | *"Re-check my deep review"* | Re-measures each bet against what you hold then |
| Property | *"Re-check my review of 12 Main Street: rates are now 6%"* | Reruns the numbers with what changed |
| Trades | *"Re-check my decision review"* | Keeps every grade frozen and re-measures the results |
| Tax plans | *"Re-check my tax plans"* | Reruns the saved plans on your current lots and lists this year's actions |

## Making deep the default

Depth is standard by default: quick answers, with a deep run when you ask for one. Say "change depth" to make every valuation and stock pick the researched kind. See [Configuration](configuration.md#depth).
