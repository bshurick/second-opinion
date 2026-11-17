# Deep picker flags

Each deep-picker script prints `flags` as a list of `{"code", "message"}`. The coordinator looks up each code here and does what its row says. The reply's Flags section names the ones a row says to name.

| Flag or field | Printed by | What to do |
|---|---|---|
| `SCREEN_PRICING_INCOMPLETE` | `pick_prep.py` | Yahoo rate-limited a screen, so its survivors are not the preset's. Wait a few minutes and run the same `pick_prep.py` command on the same folder. |
| `PRICING_INCOMPLETE` | `pool.py` | A screen file still carries the rate limit. Wait a few minutes, rerun `pick_prep.py` on the same folder, then `pool.py`. |
| `SCREEN_FAILED` | `pick_prep.py` | One screen wrote no file and the others were kept. Go on, and name the screen in the reply's Flags. |
| `MACRO_SERIES_UNAVAILABLE` | `pick_prep.py` | FRED did not return a series, and `macro.md` leaves it out. Go on. |
| `BUDGET_KEPT` | `pick_prep.py` | The folder already had a budget, and its count carries on. Expected on a rerun. |
| `BUDGET_UNAVAILABLE` | `pick_prep.py` | No budget was started. Run `budget.py DIR/pick-DATE init --plan picker-N`. If that fails, stop and show its `error`: the valuation skill is not installed. |
| `POOL_TRIMMED` | `pool.py` | More than 40 candidates were cut to 40. Say how many in the reply's Flags (`counts.trimmed`). |
| `HEALTH_CHECK_FAILED` | `pool.py` | Every name stayed, as `unchecked`. Rerun `pool.py` once. If it flags again, go on: the quick readers judge health, and the reply's Flags say the health check did not run. |
| `INDUSTRY_FILE_SKIPPED`, `SCREEN_FILE_SKIPPED`, `PROSPECT_SKIPPED` | `pool.py`, `pick_assemble.py` | A file is not JSON or not the expected shape, or a prospect has no ticker. Repair a scanner's `industries/group<N>.json` from its `.md` notes and rerun the script; for a screen file, rerun `pick_prep.py`. |
| `THEME_FILE_SKIPPED` | `pool.py`, `pick_assemble.py` | `context/themes.json` is not an object with a `themes` list. Repair it from `context/themes.md` and rerun the script. |
| `TREND_UNAVAILABLE` | `cards.py` | Nothing to rerun. The price-history download failed, so every card's `trend` is null; the cards are otherwise complete. |
| `YAHOO_RATE_LIMITED` | `cards.py` | Wait a few minutes, then run the `cards.py --run … --symbols … --force` command its `message` prints. |
| `PACK_FAILED` and `failed` | `cards.py` | Run `cards.py --run DIR/pick-DATE` once more; it fetches only the names without a pack from today. A name still in `failed` gets no quick read: leave it out of its batch and name it in the reply's Flags. |
| `NEWS_UNAVAILABLE` in a card's `sentiment_flags` | `cards.py` | Nothing to rerun. That company's quick reader spends its one search on news, as its brief says. |
| `CURRENCY_MISMATCH` in a card's `red_flags.inputs_flags` | `cards.py` | Nothing to rerun. The statements are in another currency than the share price (a foreign filer), so the pack's `quick_value.basis` and the card's `value_hint` are null. The quick reader scores `value` from multiples. |
| `LEVERAGE_HIGH` | `cards.py` | Nothing to rerun. The named cards fail the balance-sheet check (`leverage.why` in each data file says which test). They get quick reads but are not finalists. Name them in the reply's Flags. |
| `DEBT_CHANGED_SINCE_ANNUAL` in a card's `leverage.flags` | `cards.py` | Nothing to rerun. Debt is over 1.5x the last annual balance sheet's (a deal or refinancing since), so the 10-K's leverage figures in `edgar.json` are stale. The check uses today's debt. |
| `THIN_EDGAR_HISTORY` in a card's `red_flags.inputs_flags` | `cards.py` | Nothing to rerun. `edgar.json` has no annual rows or no 10-K was found (a foreign filer, or filings under a predecessor registrant), so health and direction rest on fewer figures. The card says so. |
| `HEALTH_NOT_CHECKED` | `pick_assemble.py` | The health screen did not run, so the page's funnel leaves out "Health check passed" and goes from the merged pool to "Kept for quick read". Say in the reply's Flags that the health check did not run. |
| `THESIS_MISSING` | `pick_assemble.py` | Add the pick's `thesis` to `picks-notes.json` and rerun. |
| `PICK_NOTE_DROPPED` | `pick_assemble.py` | Expected: the notes entry of a finalist that failed the gate was left off the page. |
| `CARD_SKIPPED`, `FINALIST_WITHOUT_CARD` | `pick_assemble.py` | A `cards/<TICKER>.json` is not valid JSON, or a finalist has none. Repair or write the card from its `.md` notes and rerun. |
| `CASE_PAGE_MISSING` | `pick_assemble.py` | Run the valuation skill's `render_deep.py --case DIR/deep-SYMBOL` for that pick before its save command. |
