# DCF Valuation Methods — Full Reference

Read this file when a valuation question turns on the mechanics below
(cash-flow measures, discount rates, terminal-value sensitivity, EVA/MVA
equivalence, Gordon, multi-stage or stochastic dividend models, startup
cash-flow modelling, WACC component derivation). The first section is a
one-page digest of the formulas; the Parts after it derive them.

## Contents

- Essentials at a glance
- Introduction: Why Discounted Cash Flow Analysis Matters
- Part 1: The Foundational Concept -- The Cash Budget Identity
- Part 2: Deriving the Key Cash Flow Measures
- Part 3: Valuation Frameworks
- Part 4: Economic Value Added (EVA) and Economic Profit
- Part 5: The Weighted Average Cost of Capital (WACC) in Detail
- Part 6: Terminal Value -- The Most Influential Number
- Part 7: The Dividend Discount Model -- From Gordon to Markov Chains
- Part 8: DCF and Startup Valuation -- Special Challenges
- Part 9: Measurement Issues and Practical Adjustments
- Part 10: Other Valuation Methods (For Context)
- Part 11: Key Takeaways and Practical Guidance
- References

## Essentials at a glance

### Cash flow measures
- **CFE (FCFE) = NPAT + depreciation - total net investment + net debt issuance**. It is the
  maximum that could be paid as dividends.
- **CFF (FCFF) = NOPAT + depreciation - total net investment**, where
  **NOPAT = NPAT + (1 - tau) * Int** and tau is the corporate tax rate. Practical form:
  **FCFF = NOPAT + D&A - Capex - Increase in Net Working Capital**.
- The interest tax shield is stripped out of FCFF and handled in WACC via the after-tax
  cost of debt; including it in both double-counts it.
- Match the discount rate to the cash flow: FCFF → WACC (enterprise value, then subtract
  net debt); FCFE and dividends → cost of equity (equity value directly).

### Discount rate
- **WACC = (E / (D + E)) * (r_f + beta * (r_m - r_f)) + (D / (D + E)) * i * (1 - t)**
  with E, D at market value, r_f the risk-free rate, beta the equity beta, r_m the
  expected market return, i the firm's interest rate on debt, t the effective tax rate.
- **COE = r_f + beta * (r_m - r_f)** (CAPM); beta from ~5 years of excess-return
  regression, or a relevered peer-group median unlevered beta for unlisted firms.
- **COD = i * (1 - t)**; with several tranches, the weighted average after-tax cost.

### Terminal value
- **TV = FCF_TV * (1 + g) / (r - g)**, with
  **Company Value = sum of FCF_t / (1+r)^t + TV / (1+r)^(n+1)**.
- The perpetual growth rate generally falls between 0% and 5%, in line with
  long-term nominal GDP growth; above 5% implies the firm outgrows the economy.
- Terminal value typically dominates: in the BASF case (WACC 9.0%), EUR 44,923 million of
  EUR 67,850 million enterprise value (roughly 66%) came from the terminal value alone.
- Sensitivity (base 9.0% WACC, 1.5% g): WACC 7.0%/g 3.0% → +97.5%; WACC 11.0%/g 0.0%
  → -31.2%. Raising WACC 100 bp while cutting g 50 bp shrinks fair value by more than
  19%. The DCF-derived price is a range, not a point estimate.
- Always report terminal value as a percentage of total value; flag when it exceeds ~70%.

### Dividend discount model
- Gordon: **p(t) = D(t+1) / (k_e - g)**, requiring g < k_e; it explodes as g approaches
  k_e and suits mature companies with stable dividend policies and growth below the
  economy's. Multi-stage models (two-stage, H-model, three-stage) handle firms whose
  growth is transitioning.

### Startups and high-growth firms
- DCF systematically favors slow-growth startups and short payback periods: the growth
  rate g is negatively correlated with DCF outcomes (Spearman -0.601 in a sample of 2,290
  Finnish startups) because higher growth means more negative early cash flows, and long
  development cycles (biotech, technology) score worse regardless of eventual value.
  Widen the range and weight IRR/payback evidence accordingly.


# Discounted Cash Flow Valuation Methods: Free Cash Flow, EVA, NPV, and the Dividend Discount Model

*Methodology distilled from standard corporate-finance literature (Shrieves & Wachowicz 2001; Steiger 2008; D'Amico & De Blasis 2020; Laitinen 2019).*

---

## Introduction: Why Discounted Cash Flow Analysis Matters

At its core, valuation is the act of determining what something is worth today based on what it will produce in the future. The discounted cash flow (DCF) family of methods addresses this problem by projecting a stream of future cash flows and then translating them back into present-day dollars using an appropriate discount rate that reflects the time value of money and the riskiness of those cash flows.

The concept dates back to antiquity -- compound interest calculations appear in Old Babylonian texts from 1800-1600 BC -- but the modern theoretical framework was established by Irving Fisher in 1930 and Jack Hirshleifer in the 1950s and 1960s, who provided rigorous utility-theoretic foundations. Today, DCF is the dominant methodology in corporate finance. It sits at the heart of capital budgeting, mergers and acquisitions, IPO pricing, and security analysis. Goldman Sachs, for example, advised on M&A deals totaling over EUR 475 billion in enterprise value in the first half of 2008 alone, and DCF was central to virtually all of those transactions.

Despite its ubiquity, DCF is not a single technique but rather a family of closely related approaches. Students and practitioners encounter what appear to be several different valuation methods -- the dividend discount model, the free-cash-flow-to-equity model, the free-cash-flow-to-the-firm model, economic value added (EVA), net present value (NPV), and adjusted present value (APV) -- and it is not always obvious how they relate to one another. A central insight from the academic literature is that all of these approaches are, under consistent assumptions, mathematically equivalent. They are different computational routes to the same destination. Understanding this equivalence, and the practical situations where one approach may be preferable to another, is what this summary aims to teach.

---

## Part 1: The Foundational Concept -- The Cash Budget Identity

Every DCF method begins from the same place: the firm's cash budget identity. In any given period, the sources of cash must equal the uses of cash. Shrieves and Wachowicz express this as:

**Sources = Uses**

R + dB = O + Int + Div + Taxes + dI + dWC

where:
- **R** = operating revenue
- **dB** = net debt issuance (new borrowing net of repayment)
- **O** = out-of-pocket operating costs
- **Int** = interest payments on debt, less any interest income
- **Div** = dividends on equity
- **Taxes** = total taxes paid
- **dI** = net investment in non-current assets (capital expenditures net of asset sales)
- **dWC** = net investment in working capital (including cash and marketable securities)

This identity is a tautology -- it holds by construction from the financial statements. But it is powerful because by rearranging its terms, we can derive every major DCF valuation formula. Each "method" is simply a different algebraic rearrangement that isolates a different cash flow measure for discounting.

---

## Part 2: Deriving the Key Cash Flow Measures

### Dividends

Solving the cash budget identity for dividends paid in any period gives:

Div = [R - O - Depr - Int - Taxes + Depr] - [dI + dWC] + dB

which simplifies to:

**Div = NPAT + depreciation - total net investment + net debt issuance**

where NPAT is net profit after tax (i.e., the bottom line of the income statement). This expression says that dividends are the residual: what is left from after-tax profits after adding back non-cash charges (depreciation), subtracting capital investments, and accounting for any new borrowing.

### Free Cash Flow to Equity (FCFE or CFE)

FCFE is defined as the cash flow available to equity holders. It represents the maximum amount that *could* be paid as dividends, even if management chooses to pay less (retaining cash for discretionary investment or holding it as excess marketable securities). The formula is identical to the dividend equation:

**CFE = NPAT + depreciation - total net investment + net debt issuance**

The difference between CFE and actual dividends is merely a matter of management's dividend policy. Because investments in "excess" marketable securities are presumed to be zero-NPV, the valuation result is the same whether you discount actual dividends or CFE, as long as the discount rate is applied consistently.

### Cash Flow to Debtholders (CFD)

Cash flow to debtholders is simply the interest payments they receive minus any net new lending they provide:

**CFD = Int - dB = interest payments - net debt issuance**

### Free Cash Flow to the Firm (FCFF or CFF)

Free cash flow to the firm is the total cash flow available to *all* investors -- both equity and debt holders. It is derived by combining CFE and CFD, with one important adjustment: the interest tax shield is removed from the cash flow and instead handled through the discount rate (WACC). This gives:

**CFF = CFE + CFD - tau * Int**

which, after algebraic simplification, becomes:

**CFF = NOPAT + depreciation - total net investment**

where:
- **NOPAT** = Net Operating Profit After Taxes = NPAT + (1 - tau) * Int
- **tau** = the corporate tax rate

NOPAT is a pivotal concept. It represents what the firm's after-tax profit would be if it had no debt -- the profit from operations alone, with the tax benefit of debt excluded. This is necessary because when we discount CFF at the weighted average cost of capital (WACC), the tax benefit of debt is already captured in the discount rate through the after-tax cost of debt component. Including it in the cash flow as well would double-count it.

An equivalent practical formula, widely used in industry (from Steiger and Damodaran), is:

**FCFF = NOPAT + D&A - Capex - Increase in Net Working Capital**

This starts from EBIT (earnings before interest and taxes), applies taxes to get NOPAT, adds back non-cash charges (depreciation and amortization), subtracts actual capital expenditures, and subtracts the increase in net working capital.

### The Tax Decomposition

An important subtlety is how taxes are treated. Total taxes paid can be decomposed as:

Taxes = tax with no debt financing - interest tax shield benefits

Or: Taxes = tau * (R - O - Depr) - tau * Int

The first term is the tax the firm would pay if it were all-equity financed. The second term is the tax savings from interest deductibility. The FCF method strips out the tax shield from the cash flow (resulting in a higher cash flow) and compensates by using a lower discount rate (WACC includes the after-tax cost of debt). The equity methods leave the tax shield in the cash flow and use the cost of equity as the discount rate.

---

## Part 3: Valuation Frameworks

### Three Contexts for Valuation

Shrieves and Wachowicz identify three business contexts in which DCF valuation arises, and they demonstrate that all three lead to equivalent results:

1. **Security (equity) valuation** -- What is the value of the firm's shares?
2. **Enterprise (total firm) valuation** -- What is the value of the entire firm (equity + debt)?
3. **Project valuation (capital budgeting)** -- What is the NPV of a proposed investment?

### Discount Rates

Before computing any present value, we need discount rates. Let:

- **k_e** = the required rate of return on equity (cost of equity)
- **k_b** = the pre-tax required rate of return on debt (cost of debt)
- **k** = the overall capitalization rate for the firm's free cash flows

The compound discount factors are:

- omega_e(t) = product of [1/(1 + k_e(s))] for s = 1 to t (for equity cash flows)
- omega_b(t) = product of [1/(1 + k_b(s))] for s = 1 to t (for debt cash flows)
- omega(t) = product of [1/(1 + k(s))] for s = 1 to t (for firm cash flows)

The overall rate k is the weighted average cost of capital:

**k = (V_e / (V_e + V_b)) * k_e + (V_b / (V_e + V_b)) * k_b * (1 - tau)**

This is the classic WACC formula. It weights the cost of equity and the after-tax cost of debt by their respective proportions in the firm's capital structure, using market (not book) values.

### Equity Valuation: The Dividend Discount Approach

The value of the firm's equity is the present value of all future dividends, discounted at the cost of equity:

**V_e = sum of omega_e(t) * Div(t) for t = 0 to T**

Expanding the dividend expression:

V_e = sum of omega_e(t) * {NPAT + depreciation - total net investment + net debt issuance}

### Equity Valuation: The Free-Cash-Flow-to-Equity Approach

Alternatively, discount FCFE at the cost of equity:

**V_e = sum of omega_e(t) * CFE(t) for t = 0 to T**

Under consistent assumptions, this produces the same result as the dividend discount approach, because FCFE equals dividends adjusted for discretionary investment in zero-NPV marketable securities.

### Debt Valuation

The value of the firm's debt is simply the present value of cash flows to debtholders:

**V_b = sum of omega_b(t) * CFD(t) for t = 0 to T**

### Total Firm Valuation: The Free-Cash-Flow-to-the-Firm Approach

The total value of the firm equals the sum of equity and debt values:

**V_0 = V_e + V_b = sum of omega(t) * CFF(t) for t = 0 to T**

Equivalently:

**V_0 = sum of omega(t) * {NOPAT + depreciation - total net investment}**

The value of equity is then obtained by subtracting the market value of debt:

**V_e = V_0 - V_b**

### Project Valuation: Net Present Value

For a proposed investment project j, the NPV is the discounted value of the incremental free cash flows the project generates:

**NPV_j = (1/omega_m) * sum of omega(t) * delta_CFF(t)**

where delta_CFF represents the incremental cash flow attributable to the project and omega_m is the discount factor at the time the investment decision is made. If debt is always issued at fair market value, the NPV of the project is also equal to the present value of the incremental FCFE, meaning equity holders capture the full NPV.

---

## Part 4: Economic Value Added (EVA) and Economic Profit

### The EVA Concept

Economic Value Added is not a different valuation methodology in principle -- it is a mathematically equivalent restatement of the FCF approach. The key insight of EVA is to "reallocate" investment expenditures from the periods when they occur to the periods when they generate benefits, through two charges:

1. **EVA depreciation** -- a portion of the asset's cost, representing the "usage" of the asset during the period
2. **Capital charge** -- the opportunity cost of the capital still invested in the firm, computed as k * (book value of invested capital)

The economic profit in any period is:

**EP = NOPAT + (Depr_tax - P) - k * (U + WC)**

where:
- P = EVA depreciation for the period
- U = the undepreciated book value of capital assets at the beginning of the period
- WC = beginning-of-period working capital
- k = the weighted average cost of capital

Simplified, this becomes:

**EP = NOPAT - capital charge on operating assets**

Or equivalently: Economic profit equals the operating profit the firm earns minus the profit it *should* earn (i.e., the minimum return investors require on the capital employed).

### The Equivalence of EVA and FCF

The central mathematical result is:

**V_0 = sum of omega(t) * CFF(t) = sum of omega(t) * EP(t)**

The present value of the stream of free cash flows equals the present value of the stream of economic profits. This is not an approximation -- it is an exact mathematical identity, demonstrated through the formal decomposition of investment expenditures into depreciation and opportunity cost components (shown in the Appendix of Shrieves and Wachowicz).

### Market Value Added (MVA)

Proponents of EVA define Market Value Added as:

**MVA = sum of omega(t) * EP(t) - BV_0**

That is, MVA is the difference between the total market value of the firm (the present value of all future economic profits) and the book value of the firm's assets. A positive MVA means the firm has created value beyond the capital invested in it.

### Project NPV in EVA Terms

For a specific project, the NPV can be expressed as the present value of the stream of economic value added by that project:

**NPV_j = (1/omega_m) * sum of omega(t) * EVA_j(t)**

This provides a period-by-period measure of value creation, which is why EVA has become popular for managerial performance evaluation and compensation.

### An Important Distinction: EVA in Theory vs. Practice

In theory, EVA is computed by comparing a project's or firm's economic profit to what it would be in the absence of the project or policy. In practice, EVA is often measured as the year-to-year *change* in economic profit (EP_t - EP_{t-1}). This involves an implicit assumption that year-to-year changes in EP reflect the results of management decisions, which may or may not hold in practice.

---

## Part 5: The Weighted Average Cost of Capital (WACC) in Detail

The WACC is one of the most consequential inputs in any DCF analysis because small changes in it produce large changes in the resulting valuation. Steiger's paper provides a detailed treatment.

### The Full WACC Formula

**WACC = (E / (D + E)) * (r_f + beta * (r_m - r_f)) + (D / (D + E)) * i * (1 - t)**

where:
- E = market value of equity
- D = market value of debt
- r_f = risk-free rate
- beta = the firm's equity beta (systematic risk)
- r_m = expected return on the market portfolio
- i = the firm's interest rate on debt
- t = effective corporate tax rate

### Cost of Equity via CAPM

The cost of equity is typically estimated using the Capital Asset Pricing Model:

**COE = r_f + beta * (r_m - r_f)**

The risk-free rate is proxied by the yield on government treasury bills or bonds (or, in practice, sometimes by interbank offered rates such as LIBOR). Beta is estimated via linear regression of the stock's excess returns against market excess returns, typically using about five years of historical data. For unlisted companies, a peer group's median unlevered beta is determined and then relevered to the target's capital structure.

The CAPM has been criticized -- notably by Roll (1977), who argued the true market portfolio is unobservable and therefore the model is untestable -- but it remains the standard tool for estimating cost of equity in practice.

The dividend discount model paper (D'Amico & De Blasis) provides additional perspective on CAPM, noting that it originates from Markowitz's (1952) mean-variance efficient portfolio theory, was formalized by Sharpe (1964) and Lintner (1965), and extended by Black (1972), who substituted the risk-free rate with a zero-beta portfolio. Fama and French (1992, 1993) further challenged single-factor CAPM with multi-factor models.

### Cost of Debt

The cost of debt is the interest rate the firm pays on its outstanding debt, adjusted for the tax deductibility of interest:

**COD = i * (1 - t)**

The interest rate depends on the firm's credit rating -- companies rated AAA borrow at much lower rates than those rated BB-. The credit spread (the difference between the firm's borrowing rate and the risk-free rate) also varies with market conditions. During the 2007-2008 financial crisis, for example, credit spreads widened dramatically as banks and hedge funds disclosed massive subprime exposure.

If the company has multiple tranches of debt at different rates, the cost of debt is the weighted average of the after-tax cost of each tranche.

---

## Part 6: Terminal Value -- The Most Influential Number

In a standard DCF analysis, free cash flows are projected in detail for a "scenario period" of 5-15 years. Beyond that horizon, the analyst must estimate the **terminal value (TV)** -- the present value of all cash flows from the end of the scenario period to infinity.

### The Gordon Growth Model for Terminal Value

The terminal value is typically calculated using a perpetuity growth formula (a form of the Gordon growth model):

**TV = FCF_TV * (1 + g) / (r - g)**

where:
- FCF_TV = the free cash flow in the last projected year
- g = the perpetual growth rate (the rate at which FCFs are assumed to grow forever)
- r = the discount rate (WACC)

The total company value is then:

**Company Value = sum of FCF_t / (1+r)^t + TV / (1+r)^(n+1)**

### Why Terminal Value Dominates

Steiger's BASF case study dramatically illustrates the importance of terminal value. Using Credit Suisse analyst estimates for 2008-2013 and a WACC of 9.0%, the enterprise value came to EUR 67,850 million. Of this total, **EUR 44,923 million -- roughly 66% -- came from the terminal value alone.** The discounted scenario-period cash flows accounted for only about a third of total value.

This means the valuation is overwhelmingly sensitive to the terminal value assumptions, particularly the perpetual growth rate and the WACC.

### Sensitivity Analysis: Small Changes, Massive Impact

Steiger conducted a sensitivity analysis varying the WACC and perpetual growth rate around the base case (9.0% WACC, 1.5% perpetual growth). The results were striking:

| Perpetual Growth Rate | WACC 7.0% | WACC 9.0% | WACC 11.0% |
|---|---|---|---|
| 0.0% | +19.2% | -14.5% | -31.2% |
| 1.5% | +47.6% | 0.0% (base) | -21.6% |
| 3.0% | +97.5% | +21.8% | -8.2% |

*Values shown as percentage deviation from the base case share price of EUR 58.49.*

Increasing the WACC by just 100 basis points and simultaneously decreasing the perpetual growth rate by 50 basis points shrinks the calculated fair share price by more than 19%. Since analysts cannot estimate the perpetual growth rate or the WACC with precision of even a few basis points, **the DCF-derived price should be treated as a range, not a point estimate.**

The perpetual growth rate should generally fall between 0% and 5%, in line with long-term nominal GDP growth. Growth rates above 5% are not sustainable indefinitely, as they would imply the firm eventually becomes larger than the economy.

---

## Part 7: The Dividend Discount Model -- From Gordon to Markov Chains

The dividend discount model (DDM) is the oldest and most intuitive of the DCF approaches. D'Amico and De Blasis provide a comprehensive review tracing its evolution from simple deterministic models to sophisticated stochastic formulations.

### The General Model

The foundational insight, first articulated by Williams (1938), is that the intrinsic value of a stock is the present value of all future dividends:

**p(t) = sum over i of E[D(t+i+1) / product of (1 + k_e(t+j)) for j = 0 to i]**

This says: the price today equals the expected value of each future dividend, discounted back at the required rate of return. If we assume the discounted stock price converges to zero at infinity (i.e., there are no speculative bubbles), then the price is fully determined by the dividend stream.

### The Gordon Growth Model (1962)

The most widely known special case assumes a constant dividend growth rate g and a constant discount rate k_e:

**p(t) = D(t+1) / (k_e - g)**

This requires g < k_e for the price to be finite. The model is elegant and requires only two inputs (the growth rate and the discount rate, both estimable from historical data), but it has significant limitations:
- It produces wildly incorrect results when g approaches k_e (the price goes to infinity)
- It is most appropriate for mature companies with stable dividend policies and growth rates below that of the overall economy
- Empirical evidence shows dividends tend to grow exponentially, suggesting linear growth models are not suitable for stock valuation

### Multi-Stage Models

To accommodate companies that do not fit the constant-growth assumption, several multi-stage extensions have been developed:

**Two-stage model (Malkiel, 1963):** The firm experiences a period of extraordinary growth g_h for n years, after which growth drops to a stable long-term rate g. The stock value is the sum of the discounted dividends during the high-growth phase plus the discounted Gordon model value at year n:

p(t) = [D(t)(1+g_h) * (1 - ((1+g_h)/(1+k_e))^n)] / (k_e - g) + P^G(n) / (1 + k_e)^n

This model is useful for companies with a specific competitive advantage (a patent, a first-mover advantage) that produces temporarily high growth.

**H-model (Fuller and Hsia, 1984):** Rather than an abrupt drop from high growth to stable growth, this model assumes a *linear decline* from the initial growth rate g_a to the stable rate g_n over a period of 2H years:

p(t) = D(t)(1 + g_a) / (k_e - g_n) + D(t) * H * (g_a - g_n) / (k_e - g_n)

This avoids the unrealistic discontinuity of the two-stage model.

**Three-stage model (Molodovsky et al., 1965):** Combines high-growth, declining-growth, and stable-growth phases, with potentially different discount factors for each. It allows for variable payout ratios across phases, overcoming the constant-payout limitation of simpler models. Empirical evidence from Sorensen and Williamson (1985), testing 150 S&P 400 firms, showed that the three-stage model outperformed the constant growth and two-period models in identifying undervalued and overvalued securities.

### Stochastic Dividend Discount Models

A major limitation of all the deterministic models above is that they treat future dividends as known quantities. In reality, dividend growth is uncertain. Several authors have developed stochastic extensions:

**Markov dividend stream (Hurley and Johnson, 1994):** Dividends increase by a fixed amount with probability q, remain unchanged with probability (1-q-q_B), and the firm goes bankrupt with probability q_B. This produces an additive model with closed-form solutions. A geometric variant assumes dividends grow by rate g with probability q.

**Trinomial model (Yao, 1997):** Extends Hurley and Johnson by allowing dividends to also *decrease*, with probability q_d. This produces better empirical fits than the simpler binary models.

**Markov chain models (Ghezzi and Piccardi, 2003; Barbu et al., 2017; D'Amico and De Blasis, 2018):** These model the dividend growth rate as a discrete Markov process, allowing the price-dividend ratio to depend on the current state of the growth process. This is more realistic than models that produce a single valuation regardless of the economic environment. The Markov approach allows different valuations depending on the current "regime" (e.g., expansion vs. recession), and later extensions to multivariate settings allow modeling an entire portfolio of stocks with cross-stock dependencies.

### Limitations of the DDM

The dividend discount model, despite its intuitive appeal, faces several challenges:
- It only applies to companies that pay dividends consistently
- Many firms now prefer share buybacks over dividends for tax reasons, which reduces the dividend cash flow and leads to undervaluation
- The constant discount rate assumption is unrealistic over long time horizons
- Buybacks and other non-dividend distributions can be incorporated by adjusting the cash flow definition, but this complicates the model

---

## Part 8: DCF and Startup Valuation -- Special Challenges

Laitinen's paper investigates what happens when DCF methods are applied to startups, revealing systematic biases that practitioners should be aware of.

### Why DCF Is Used for Startups

DCF is the most popular valuation method among startup investors, followed by the internal rate of return (IRR) and payback period methods. It is especially favored when there is little comparable transaction data available -- precisely the situation that characterizes most startup investments.

### The Startup Cash Flow Model

Laitinen develops a model where:
- Expenditure grows at a steady rate g: M_t = M_0 * (1+g)^t
- Each period's expenditure generates a lagged revenue stream following a geometric distribution, parameterized by a level parameter K and a lag parameter q (0 < q < 1)
- The internal rate of return r represents true profitability (r = IRR)
- Cash flow = Revenue - Expenditure, and the present value is discounted at rate d

The key insight is that startup cash flows are non-stationary: revenue lags expenditure, especially in early years. The growth rate of revenue converges toward g from below, and the revenue-to-expenditure ratio converges toward a steady-state value of (1+r-q)(1+g) / ((1+r)(1+g-q)), which exceeds unity only if r > g.

### DCF's Systematic Biases in Startup Valuation

The numerical experiments (81 parameter combinations, 100 simulation runs each) and empirical validation using 2,290 Finnish startups revealed several troubling biases:

**1. DCF favors slow-growth startups.** The growth rate g is *negatively* correlated with DCF outcomes. Higher growth means more early-stage investment, more negative cash flows upfront, and a lower present value -- even if the firm will ultimately be more valuable. The Spearman correlation between DCF and g was -0.601 in the empirical sample.

**2. DCF favors short payback periods.** The lag parameter q (a proxy for payback period) is also negatively correlated with DCF. Firms that generate revenue quickly from their investments score better on DCF than firms whose investments take longer to pay off. This systematically disadvantages technology firms, biotech companies, and other businesses with long development cycles.

**3. DCF is positively correlated with IRR, but the effect is weak in early stages.** In the launch stage (first 5 years), the payback period is the most significant driver of mean DCF. IRR's importance grows as the time series lengthens -- by the growth stage (10 years), IRR becomes the most significant factor.

**4. Higher risk aversion amplifies the biases.** When the expected utility function includes a risk-aversion penalty (lambda/2 * Variance), the negative effects of growth and long payback periods are magnified. For higher rates of risk aversion (lambda = 1.0 or 1.5), the negative effect of growth becomes the *only* significant determinant of expected utility, completely dominating IRR.

### Implications for Practice

These findings have serious implications for startup investing. If investors rely on DCF as their primary criterion:
- They will systematically undervalue fast-growing companies with long development cycles -- exactly the high-tech, high-innovation startups that economies need most
- They will overvalue slow-growing, quick-payback businesses like certain retail or service companies
- The bias is strongest in the early years when startup financing decisions are most consequential

This does not mean DCF should be abandoned for startups, but it should be supplemented with other methods and interpreted with awareness of these structural biases.

---

## Part 9: Measurement Issues and Practical Adjustments

### From Accounting Numbers to Economic Cash Flows

All DCF methods rely on cash flow projections that typically start from accounting data. But Generally Accepted Accounting Principles (GAAP) introduce several distortions:

**Revenue recognition:** Accounting recognizes revenue when goods or services are provided, not when cash is received. This creates timing differences between accounting profit and cash flow.

**Matching principle:** Costs are matched to the revenues they generate, which spreads expenditures across periods differently from when cash is actually paid.

**Inventory accounting:** The choice between LIFO and FIFO affects reported cost of goods sold, inventory values, and therefore operating income.

**Depreciation:** The choice of depreciation schedule (straight-line, declining balance, etc.) affects reported operating costs but not actual cash flows. For DCF purposes, you need the tax depreciation schedule (which determines the actual tax shield), not necessarily the book depreciation schedule.

### Common Adjustments for FCF Models

When deriving FCFE or FCFF from financial statements, common adjustments include:
- Adding back deferred tax provisions
- Including equity income from subsidiaries (net of dividends received)
- Adjusting for changes in LIFO reserves
- Adding back goodwill amortization
- Making foreign currency translation adjustments

### Common Adjustments for EVA

EVA requires adjustments to the *capital base* as well as to NOPAT. Examples include:
- **Capitalizing R&D** and other expenditures that create future value (with depreciation of capitalized R&D included in future NOPATs)
- **Adding goodwill of acquired companies** to the invested capital base
- **Capitalizing non-capital leases** (treating them as debt-financed assets)
- **LIFO inventory valuation reserves** should be added back to the capital base

Stewart (1991) documented a comprehensive list of such adjustments in *The Quest for Value*. The number of potential adjustments is large, and different practitioners will make different choices, which is one reason why valuations of the same firm can differ substantially.

---

## Part 10: Other Valuation Methods (For Context)

While DCF is the focus of these papers, Steiger notes that practitioners almost always use multiple valuation approaches in parallel, comparing results to increase confidence.

### Trading Comparables

Build a peer group of listed companies with similar industry classification, geography, and business model. Calculate valuation multiples (EV/Sales, EV/EBITDA, EV/EBIT, P/E) for each peer. Apply the median or mean multiple to the target company's fundamentals. This tends to produce conservative estimates because it excludes acquisition premiums.

### Transaction Comparables

Similar to trading comparables, but the peer group consists of *completed transactions* (M&A deals) rather than current market prices. This captures the premiums acquirers actually paid, making it more relevant for M&A contexts. However, finding statistically significant peer groups of similar transactions is difficult.

### Adjusted Present Value (APV)

APV separates the value of the firm into two components: (1) the NPV of free cash flows assuming pure equity financing, plus (2) the present value of the interest tax shield and other financing side effects. APV and standard DCF produce the same result but APV is sometimes easier to use when the capital structure is expected to change significantly over time.

---

## Part 11: Key Takeaways and Practical Guidance

### The Equivalence Principle

Free cash flow, economic value added, and net present value are conceptually equivalent approaches to valuation. They differ in what they discount (cash flows vs. economic profits) and what discount rate they use, but when applied consistently, they yield the same answer. The choice between them should be driven by practical considerations: which approach is easier to implement given the available data and the specific valuation context.

### When to Use Which Method

| Context | Recommended Approach | Why |
|---|---|---|
| Equity valuation of a mature, dividend-paying company | Dividend Discount Model or FCFE | Direct, intuitive, and cash flows are relatively predictable |
| Enterprise valuation for M&A | FCFF discounted at WACC | Captures value to all capital providers; standard in investment banking |
| Capital budgeting (project evaluation) | NPV of incremental FCFF | Focuses on the incremental impact of the project on firm value |
| Managerial performance evaluation | EVA | Provides period-by-period value creation metrics |
| Startup valuation | FCFF with caution | Be aware of systematic biases against high-growth, long-payback firms |
| Changing capital structure | APV | Avoids complications of a changing WACC |

### The Critical Importance of Assumptions

The DCF framework is only as good as its inputs. The sensitivity analyses from Steiger's BASF case study demonstrate that tiny changes in assumptions -- a shift of 50 basis points in the perpetual growth rate or 100 basis points in the WACC -- can change the implied share price by 20% or more. The terminal value alone can account for two-thirds or more of the total valuation.

This means:
1. **Always run sensitivity analyses.** Present results as ranges, not point estimates.
2. **Use scenario analysis.** Develop base, bull, and bear cases with different assumptions for growth, margins, and capital costs.
3. **Cross-check with other methods.** Trading comparables, transaction comparables, and other approaches should bracket the DCF result.
4. **Be skeptical of terminal value assumptions.** The perpetual growth rate is the single most influential assumption in the entire analysis, and it is inherently unknowable.
5. **Understand the biases.** DCF systematically favors certain types of firms (mature, slow-growing, short payback) over others (fast-growing, capital-intensive, long-cycle). Adjust your interpretation accordingly.

### Summary of Key Formulas

| Measure | Formula |
|---|---|
| **NOPAT** | NPAT + (1-tau) * Interest = EBIT * (1 - tau) |
| **FCFE** | NPAT + Depreciation - Net Investment + Net Debt Issuance |
| **FCFF** | NOPAT + Depreciation - Net Investment |
| **WACC** | (E/(D+E)) * k_e + (D/(D+E)) * k_b * (1-tau) |
| **Cost of Equity (CAPM)** | r_f + beta * (r_m - r_f) |
| **Cost of Debt** | i * (1 - t) |
| **Terminal Value** | FCF * (1+g) / (WACC - g) |
| **Company Value** | Sum of discounted FCFs + Discounted Terminal Value |
| **Economic Profit** | NOPAT - k * Invested Capital |
| **Gordon Growth Price** | D(t+1) / (k_e - g) |

---

## References

- Shrieves, R.E. & Wachowicz, J.M. Jr. (2001). "Free Cash Flow (FCF), Economic Value Added (EVA), and Net Present Value (NPV): A Reconciliation of Variations of Discounted-Cash-Flow (DCF) Valuation." *The Engineering Economist*, 46(1), 33-52. Parts 1-4 follow this paper's derivation; the cash-budget identity and its notation are theirs.
- Steiger, F. (2008). "The Validity of Company Valuation Using Discounted Cash Flow Methods." Seminar paper, European Business School. arXiv:1003.4881. Source of the WACC treatment and the BASF terminal-value and sensitivity figures in Parts 5-6.
- D'Amico, G. & De Blasis, R. (2020). "A Review of the Dividend Discount Model: From Deterministic to Stochastic Models." arXiv:2001.00465. Source of Part 7.
- Laitinen, E.K. (2019). "Discounted Cash Flow (DCF) as a Measure of Startup Financial Success." *Theoretical Economics Letters*, 9, 2997-3020 (CC BY 4.0). Source of Part 8.

The text above is a paraphrase written for this skill; it reproduces the papers' methods, notation, and reported figures, not their prose.
