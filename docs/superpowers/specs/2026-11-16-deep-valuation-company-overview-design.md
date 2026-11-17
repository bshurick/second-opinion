# Deep valuation page: company overview and price history — design

## Intent

A reader who lands on a deep valuation page sees what the company is worth before seeing
what the company does. Add context at the top: a short model-written summary of the business,
the profile facts that say how large and where it operates, and a line chart of its share price
over five years. The valuation itself is unchanged and stays the answer the page leads with
after the context.

## Goals

- The page opens with an "About SYMBOL" card: company name, sector, industry, country,
  employees, market capitalisation and website, then a short business summary.
- The same card carries a five-year weekly share-price line chart, ending at the latest close.
- The summary is written by the model from the valuation's own research. When no summary
  exists, the card shows Yahoo Finance's business description instead.
- `render_deep.py --case` fills both from the case folder and a Yahoo history fetch, and
  writes them into `page.json`, so a later `--in` run reproduces the page without a fetch.
- A missing profile or a failed history fetch leaves the rest of the page intact.

## Non-goals

- No change to the scenarios, the model, the returns, the ledger or any existing block.
- No second chart, no comparison series, no benchmark line.
- No price history in the research pack (`deep_prep.py` is unchanged).
- No change to the quick valuation page.
- No change to the deep picker's gate or saved pick fields.

## Constraints

- The published page is one self-contained fragment: no external scripts, stylesheets or
  runtime fetches. The chart uses `F.lines` from `lib/second_opinion/page.py`.
- `render_deep.py --in` fetches nothing. Only `--case` may call `market.price_history()`.
- Every card carries a help modal (`F.help`); the page audit test enforces this.
- Old case folders and old `page.json` files keep rendering as they do today, without the
  new card, rather than failing.
- The profile facts are Yahoo Finance's, at prep time. The summary is the model's, and the
  card says which is which.
- Version bump to 1.14.0 in both manifests, with a CHANGELOG entry.

## Approaches

1. **Renderer fetches at page build.** `render_deep.py --case` reads
   `baseline/fundamentals.json` for the profile and calls `market.price_history(symbol,
   period="5y", interval="1wk")` for the chart. Both go into `page.json`.
   *Picked:* the chart is current at publish, one script owns the page, and `--in`
   round-trips exactly. Cost: the renderer gains a network call and its `--case` test needs a
   monkeypatched market.
2. **Prep writes it into the pack.** `deep_prep.py` saves the history beside the other pack
   files and the renderer stays offline. Rejected: the chart would be hours stale by publish,
   and prep runs once per deep-picker candidate, adding a Yahoo call each.
3. **A named `price-history.py` step.** A script writes the history into the case folder
   before rendering. Rejected: it adds a command to the deep steps and one more thing to
   forget, while the renderer still has to cope with the file being absent.

## Data contract

`page.json` (and the `--in` input) gains two optional top-level keys:

```json
{
  "company": {
    "summary": "Two or three sentences written by the model.",
    "name": "Acme Corporation", "sector": "Industrials",
    "industry": "Tools and Accessories", "country": "United States",
    "employees": 12345, "market_cap": 1234567890,
    "website": "https://example.com",
    "description": "Yahoo Finance's business summary, the fallback text."
  },
  "price_history": {
    "symbol": "ACME", "period": "5y", "interval": "1wk",
    "prices": [{"date": "2021-11-19", "close": 123.4}]
  },
  "flags": [{"code": "PRICE_HISTORY_UNAVAILABLE", "message": "..."}]
}
```

- `company` is optional. `summary`, when present, is a non-empty string of at most 80 words
  with none of `summary_card.FORBIDDEN_VERB_RE`'s advice words. `description` is used only
  when `summary` is absent, and is clipped to 90 words with an ellipsis.
- `price_history.prices` is a list of objects with a `date` string and a numeric `close`.
  Points with a null close are dropped.
- `flags` carries renderer-found problems and merges into the page's Flags list.
- `blocks.json` gains an optional top-level `company` object, of which only `summary` is
  read. `render_deep.py --case` merges it over the facts from
  `baseline/fundamentals.json` (`info`): `name`, `sector`, `industry`, `country`,
  `employees`, `market_cap`, `website`, `description`. The model's summary wins; the
  Yahoo description remains as the fallback.
- `--case` fetches the history with the symbol from `model.out.json`. A non-empty response
  becomes `price_history` with each point trimmed to `date` and `close`. An exception or an
  empty response leaves `price_history` out and appends
  `PRICE_HISTORY_UNAVAILABLE` with the reason to `flags`.

## Rendering

- A single new section, `#about-card`, sits between `#intro` and `#headline`. The script
  builds it only when `company` or `price_history` has usable data; otherwise the element
  stays empty, so old inputs render exactly as today.
- The heading reads "About {name}" when a name is present, otherwise "About {symbol}".
- The facts line joins the fields that exist: sector, industry, country,
  "{employees} employees", market capitalisation through `F.moneyC`, and the website as a
  link. Each value is escaped.
- The summary paragraph shows `company.summary`; with none, it shows the clipped
  `description`. A muted line names the source: the valuation's research, or Yahoo Finance
  for the fallback.
- The chart uses `F.lines` with `xIsDate`, the first series colour, `area: true`,
  `height: 260`, a money y-axis formatted to cents, and an aria label naming the symbol and
  span. It renders only with two or more points. Beneath it, one caption line gives the last
  close date and the range over the final 52 weeks (or the whole series when shorter).
- The card's help modal explains what the card shows, that the summary is written from the
  valuation's research while the profile facts come from Yahoo Finance, and how to read the
  chart. The card is included in the page's card audit.
- The page's Flags section merges `data.flags` after the model's, returns', missing-role and
  note flags.

## Files

| File | Change |
|---|---|
| `skills/valuation/scripts/render_deep.py` | Validation, `--case` assembly, the about card, chart, flags, docstring |
| `skills/valuation/SKILL.md` | Step 12 tells the model to write `company.summary`; the case-folder table, the page description and the deep page section name the new card and data |
| `docs/scripts.md` | The `render_deep.py` row |
| `docs/samples/valuation-deep.json` | Regenerated from the test fixture with the new keys |
| `tests/test_scripts_valuation_deep.py` | New and updated tests |
| `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 1.14.0 |

## Tests

- Every-block page renders with a company card and chart when the input carries both.
- An input without `company` or `price_history` renders unchanged and has no about card.
- A summary over 80 words, an advice word, a bad `prices` row and a non-object `company`
  each exit 2 naming the problem.
- `--case` reads `baseline/fundamentals.json`, fetches through a monkeypatched
  `market.price_history`, and writes `company` and `price_history` into `page.json`; a
  second run with `--in page.json` produces identical HTML.
- A failed fetch still writes the page and appends `PRICE_HISTORY_UNAVAILABLE`.
- Without `company.summary`, the card shows the Yahoo description clipped at 90 words.
- The card audit passes with the new card visible.

## Left to the builder

- Exact wording of the help modal and the source line.
- Whether the facts line reads better as a `<dl>` or one wrapped line; the sample page
  decides.
- The chart's exact y-axis label format and caption phrasing.
