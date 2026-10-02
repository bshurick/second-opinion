# Value Investing: Graham's Margin of Safety and Buffett's Owner Earnings

A digest of the intrinsic-value methods that predate the DCF-everything era,
written to accompany `scripts/intrinsic.py`. Every figure the script emits
maps to a section here. Sources are primary: Graham's own text and Berkshire
Hathaway's shareholder letters, with Greenwald as the modern synthesis.

## Contents

- Sources
- 1. The margin of safety (Graham, ch. 20)
- 2. The Graham number (ch. 14, criteria 6 and 7 combined)
- 3. Graham's growth formula (ch. 11; 1974 revision)
- 4. Net current asset value and net-nets (ch. 15; Security Analysis Part IV)
- 5. The defensive investor's seven criteria (ch. 14)
- 6. Owner earnings (Buffett, 1986 letter, appendix)
- 7. Intrinsic value (Buffett, 1992 letter)
- 8. Buffett's quantifiable tenets
- 9. Presenting the result
- 10. Financials and REITs

## Sources

- Graham, B. (1973). *The Intelligent Investor*, 4th rev. ed. Chapter 8 ("The
  Investor and Market Fluctuations", Mr. Market), chapter 14 ("Stock Selection
  for the Defensive Investor", the seven criteria), chapter 15 (the
  enterprising investor, net-nets), chapter 20 ("Margin of Safety as the
  Central Concept of Investment"). The growth formula appears in chapter 11
  and was restated with the bond-yield adjustment in the 1974 revision.
- Graham, B. & Dodd, D. (1934). *Security Analysis*. Part IV (net current
  asset value), Part VI (the earnings record and the margin of safety).
- Buffett, W. Berkshire Hathaway Chairman's Letters: 1977 (return on equity
  as the measure of managerial performance), 1983 (economic goodwill), 1986
  appendix ("owner earnings"), 1992 (intrinsic value, Aesop, and the
  "look-through" view), 1994 and 2007 (moats and pricing power). All at
  https://www.berkshirehathaway.com/letters/letters.html.
- Greenwald, B., Kahn, J., Sonkin, P. & van Biema, M. (2001). *Value
  Investing: From Graham to Buffett and Beyond*. Chapters 4 to 6 (asset
  value, earnings power value, growth as the residual).

## 1. The margin of safety (Graham, ch. 20)

Graham's one idea: pay a price far enough below a conservative estimate of
value that ordinary errors in the estimate, and ordinary bad luck in the
business, do not produce a loss. The margin is the difference between price
and value, and its purpose is to make forecasting unnecessary. Graham
expressed it two ways:

- **Earnings power over bond yield.** A stock's earnings yield (EPS / price)
  should exceed the yield on high-grade bonds by a wide margin. At a P/E of
  9 the earnings yield is 11%; against a 4% bond yield the excess is a
  margin of safety that accumulates as retained earnings.
- **Price below asset value.** For the net-net investor the margin is the
  gap between price and net current asset value: the buyer pays less than
  the liquidating value of the working capital alone and gets the plant and
  the going concern for nothing.

Graham's rule of thumb for the defensive investor was to pay no more than
two thirds of appraised value, a one-third discount. The script labels every
discount against 25%, 33%, and 50% bands. Those labels are description, not
a signal: a stock can sit at a 50% discount to a value estimate that is
itself wrong.

## 2. The Graham number (ch. 14, criteria 6 and 7 combined)

Criteria 6 and 7 of the defensive list set two ceilings: price no more than
15 times the average earnings of the past three years, and price no more
than 1.5 times book value, with the proviso that a lower earnings multiple
justifies a higher asset multiple as long as the product of the two stays
under 22.5 (15 x 1.5). Solving that product for price gives

    Graham number = sqrt(22.5 x EPS_3yr_avg x book value per share)

Both inputs must be positive. The script uses diluted EPS averaged over the
latest three fiscal years in the table and the latest fiscal year's total
equity divided by diluted shares (or a supplied share count). It is a
ceiling on what a defensive investor pays, not an estimate of what the
business is worth.

## 3. Graham's growth formula (ch. 11; 1974 revision)

For growth stocks Graham offered a formula that reproduces the results of
"the more refined mathematical calculations":

    Value = EPS x (8.5 + 2g)

with g the expected annual growth rate over the next 7 to 10 years in
percentage points (so g = 7 for 7%). The 8.5 is the P/E he thought fair for
a no-growth company when Aaa bonds yielded about 4.4%. The 1974 revision
made that explicit:

    Value = EPS x (8.5 + 2g) x 4.4 / Y

where Y is the current Moody's Aaa corporate bond yield in percent. Higher
bond yields lower every stock's value, which is the earnings-yield-versus-
bond-yield idea of section 1 in another form. Graham himself warned that
the formula extrapolates growth in a way he did not trust, which is why the
script's default g is deliberately tame: the smaller of the EPS CAGR and
the revenue CAGR over the table, clipped to the range 0 to 8%. EPS can
outrun revenue for years on margin expansion, buybacks, and a low tax
rate, none of which compounds forever; revenue growth is the harder
ceiling. When EPS is not positive at both ends of the table the revenue
CAGR stands alone. The output spells the arithmetic out in
`inputs.growth_rate.source` and gives `growth_alternatives`: both CAGRs
and the formula's value at g = 5%, 10%, and 15%, so the sensitivity is on
the page without a rerun; `growth_rate` overrides the default and is not
clipped. The script applies the formula to the three-year average EPS, so
a one-year earnings spike does not become a valuation, and the
`normalized` block (section 10) restates the Graham number on the ten-year
average EPS for the same reason. FRED series `AAA` supplies Y;
`intrinsic-inputs.py` fetches it.

## 4. Net current asset value and net-nets (ch. 15; Security Analysis Part IV)

    NCAV per share = (current assets - total liabilities) / shares

Note that Graham subtracts all liabilities, including long-term debt and
preferred stock, not just current liabilities. A net-net is a stock selling
below NCAV; Graham bought diversified groups of them at two thirds of NCAV
or less and reported that the method "worked out well for us" over more
than thirty years. Such stocks are rare in modern large-cap markets, and
when NCAV is negative (most operating companies) the test simply does not
apply; the script says so with a NEGATIVE_NCAV flag rather than reporting a
meaningless number.

## 5. The defensive investor's seven criteria (ch. 14)

Graham wrote these for a portfolio of "large, prominent, and conservatively
financed" companies, to be applied mechanically. The script scores them as
pass, fail, or no data:

| # | Criterion | Graham's threshold | Script's test |
|---|---|---|---|
| 1 | Adequate size | not less than $100M of annual sales (1973 dollars) for an industrial | latest revenue >= `min_revenue`, default $700M as a rough CPI adjustment |
| 2 | Sufficiently strong financial condition | current assets at least twice current liabilities; long-term debt not exceeding net current assets (working capital) | both on the latest fiscal year |
| 3 | Earnings stability | some earnings for the common stock in each of the past ten years | positive net income every year in the table |
| 4 | Dividend record | uninterrupted payments for at least the past 20 years | dividends paid every year in the table |
| 5 | Earnings growth | at least one-third increase in per-share earnings over the past ten years, using three-year averages at the beginning and end | three-year average EPS at the end of the table at least 4/3 of the three-year average at the start |
| 6 | Moderate P/E | current price not more than 15 times average earnings of the past three years | price / EPS_3yr_avg <= 15 |
| 7 | Moderate price to assets | not more than 1.5 times book value last reported; product of P/E and P/B not over 22.5 | either condition |

Criteria 3, 4, and 5 want 10 to 20 years of history. XBRL company facts
reach back to about 2009, so `intrinsic-inputs.py` asks for ten fiscal years
by default and the script reports `years_covered` and a SHORT_HISTORY flag
when it saw fewer than ten. A pass on five years of data is weaker evidence
than Graham had in mind; say so when presenting.

## 6. Owner earnings (Buffett, 1986 letter, appendix)

Buffett's definition, verbatim in structure:

> (a) reported earnings plus (b) depreciation, depletion, amortization, and
> certain other non-cash charges ... less (c) the average annual amount of
> capitalized expenditures for plant and equipment, etc. that the business
> requires to fully maintain its long-term competitive position and its
> unit volume.

He adds that (c) "must be a guess, and sometimes a very difficult one to
make," and that owner earnings will often differ from GAAP earnings and from
"cash flow" as promoters use the term, because promoters stop at (b). The
script computes

    owner earnings = net income + D&A - maintenance capex

and estimates maintenance capex two ways, then defaults to the larger of
the two so the estimate errs toward less owner earnings:

- **D&A as the floor.** A business that spends less than its depreciation
  on plant is usually shrinking its asset base.
- **Average capex over the table.** A steady business's average spending
  is what it has actually needed to stay in place, growth included.

Neither is right for every company. A fast grower's average capex includes
growth spending and overstates maintenance; a business with old plant
under-depreciates and D&A understates it. Pass `maintenance_capex` to
override, and say which judgment was made. Free cash flow (operating cash
flow minus all capex) is the conservative cousin of owner earnings and is
what `dcf.py` and `inputs.py` use; the difference between the two is the
growth capex that owner earnings adds back.

## 7. Intrinsic value (Buffett, 1992 letter)

> Intrinsic value can be defined simply: It is the discounted value of the
> cash that can be taken out of a business during its remaining life.

Buffett discounts at the long-term Treasury rate, not at a CAPM cost of
equity, because he handles risk by insisting on a margin of safety and on
businesses he can predict rather than by adding a premium to the rate. He
has also said that when rates are unusually low he does not use them as
they stand. The script therefore hands `dcf.py` a discount rate of
max(10-year Treasury, `discount_rate_floor`), with the floor at 8% by
default, and prints the rule it applied. The rest of the handoff is a
ten-year stage at the growth rate used above, a 2% terminal growth, a net
debt of zero, and the current price so `dcf.py` also reports the growth the
market is implying. The zero is deliberate: owner earnings start from net
income, which is already after interest, so they are the owners' cash flow
and their present value is equity value directly. Subtracting the balance
sheet's debt as well would count it twice; `net_debt_note` quotes the
long-term debt and cash for context. Run `dcf.py` on
`buffett.dcf_input` to get the present value; `intrinsic.py` does not
duplicate the discounting.

The 1992 letter also settles the growth-versus-value debate: growth is
"always a component in the calculation of value," and the two approaches
"are joined at the hip." Growth only adds value when each dollar retained
earns more than a dollar of market value, which is the retained-earnings
test of the 1983 and later letters. The script does not compute that test,
because it needs a market-value history the annual table lacks.

## 8. Buffett's quantifiable tenets

The letters do not give a checklist, but they return to the same measures.
Hagstrom's *The Warren Buffett Way* (1994) organized them into business,
management, financial, and market tenets. The script scores the seven that
reduce to numbers in the annual table:

| Tenet | Source | Script's test |
|---|---|---|
| Consistently high return on equity | 1977 letter: ROE, not EPS growth, is "the primary test of managerial economic performance" | ROE >= 15% in at least 80% of years |
| Little debt | 1987 letter: the best businesses earn high returns "employing little or no debt" | long-term debt / equity <= 0.5 |
| High profit margins | 1983 and 1993 letters: pricing power shows up as margins that hold | net margin >= 10% |
| Consistent operating history | 1987 letter: "businesses that have been stable for many years" | positive operating income every year |
| Positive owner earnings every year | 1986 appendix | as computed in section 6 |
| Earnings that turn into cash | 1986 appendix, on the gap between reported earnings and owner earnings | free cash flow / net income >= 0.8 |
| Share count not rising | 1984 letter on repurchases and the dilution of per-share value | diluted shares not above the first year's |

The qualitative tenets (a durable moat, candid and rational management,
staying within one's circle of competence) are the part that matters most
to Buffett and cannot be scored from a table. When the checklist is strong,
those are the questions to take to the 10-K, the proxy, and the
`fundamental-research` skill's filing reader.

## 9. Presenting the result

- Report the Graham number and the growth-formula value as ceilings from
  two different assumptions, not as the company's worth. Report the
  owner-earnings DCF as a range from `dcf.py`'s sensitivity grid.
- State the margin of safety for each as price / value and the discount,
  and say which estimate it is against. A stock rarely clears every test;
  the pattern of passes and failures is the finding.
- Say how many fiscal years the history tests saw and which estimate of
  maintenance capex was used.
- Keep the compliance rules: no recommendation, both cases, risks with
  opportunities. Graham's own framing helps here: the margin of safety is
  a description of the gap between price and an estimate, and the estimate
  can be wrong.

## 10. Financials and REITs

Graham wrote the seven criteria for industrials and said so; his chapter
on "financial enterprises" (ch. 14, the closing pages) notes that banks
and insurers have no inventories or receivables in the industrial sense
and that their "current ratio" is meaningless. `intrinsic-inputs.py`
reads the SEC SIC code from the EDGAR submissions index and sets
`business_type` accordingly (banks and credit 6020-6199, brokers and asset
managers 6200-6299, insurers 6311-6411 are `financial`; 6798 is `reit`;
`--business-type` overrides). The script then changes what it scores:

- **Financial.** The current ratio, net current asset value, and the
  net-net test are null with a NOT_APPLICABLE flag. The financial-condition
  criterion becomes equity / total assets >= 8%, a plain leverage ratio in
  the spirit of the Basel floors, with the threshold string saying so. The
  "little debt" tenet is skipped because deposits and borrowings are the
  business. Owner earnings and the `dcf_input` are still computed so the
  numbers are on the page, but flagged DCF_NOT_MEANINGFUL_FOR_FINANCIALS
  with `net_debt` set to 0: a bank's D&A and capex do not describe its
  reinvestment, and its debt is not net debt to subtract. The yardstick
  that fits is `book_value_tests`: price to book against the latest and
  ten-year ROE. A P/B of 1.0 is fair when ROE equals the discount rate; the
  justified multiple is (ROE - g) / (r - g), and the note prints it.
- **REIT.** GAAP EPS is after real-estate depreciation that rarely
  reflects economic decay, so the Graham number and growth formula are
  reported but flagged GAAP_EPS_UNDERSTATES_REIT. Maintenance capex
  defaults to 1% of revenue, the usual recurring-capex reserve, unless
  `maintenance_capex` overrides it, and `reit_tests` reports owner
  earnings per share as an AFFO proxy with price / AFFO proxy, dividend
  yield, and the payout of the AFFO proxy. The `real-estate` skill's REIT
  calculators (FFO, AFFO, NAV) take over from here.

**Normalized earnings (all types).** Graham's chapter 12 and Security
Analysis Part VI insist on average earnings over a full cycle, because a
peak year makes any earnings multiple look cheap. The `normalized` block
averages owner earnings and EPS over the last ten fiscal years (at least
five must be present), restates the Graham number on the ten-year EPS,
and builds `dcf_input_mid_cycle`: fcf0 at the ten-year average owner
earnings growing only at terminal growth. A CYCLE_PEAK flag fires when the
latest owner earnings exceed 1.5x the ten-year average; present the
normalized figures beside the latest-year ones when it does.
