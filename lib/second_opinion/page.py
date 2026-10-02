"""Self-contained interactive HTML pages for skill results.

A skill's ``render.py`` turns the JSON its main script printed into one HTML fragment that the
Artifact tool can publish (no ``<html>``/``<head>``/``<body>``: the host wraps it). Everything is
inline: theme tokens for light and dark, a small CSS system (stat tiles, sortable tables, chips,
bars, a tooltip) and a JS toolkit (``FA``) with number formatting, table sorting/filtering and
inline-SVG bar, donut, line/area/band charts and a heatmap. No external scripts or stylesheets.

Usage from a skill::

    from second_opinion import page
    html = page.render(title="Portfolio Snapshot", data=result, body=BODY_HTML, script=BUILD_JS)

``data`` is embedded as ``window.DATA``; ``script`` runs after the toolkit is defined and builds the
sections into the elements ``body`` declared. ``page.write(path, html)`` writes it.

Readers without finance vocabulary: ``GLOSSARY`` (below) is embedded as ``window.GLOSSARY``; a
renderer wraps jargon with ``FA.term("beta")`` (hover or tap shows the one-sentence explanation),
opens the page with ``FA.explain(el, html)`` ("What am I looking at?"), and can open detail panels
with ``FA.modal(html)``. Each card explains itself through ``FA.help(card, {lead, sections})``: one
ⓘ button in its h2 opening a modal with the lead, the sections (html or a ``render(el)`` diagram,
e.g. ``FA.flow`` / ``FA.readGrid``) and the card's glossary terms with links; a card without a spec
but with terms gets a terms-only button (``FA.armHelp``), and ``data-help="none"`` exempts one.
Teaching text belongs in a walkthrough rather than on the page: ``FA.intro(el, {lead, steps})``
puts one plain sentence and a "How to read this page" button at the top, and the button runs
``FA.tour(steps)`` -- one card per step, each outlining the section it explains.
"""

from __future__ import annotations

import html as html_mod
import json
from pathlib import Path


# One intro for every page's Flags section, so they all say what a flag is the same way.
FLAGS_INTRO = (
    '<p class="sub">Notes about the data behind this page: where a figure rests on an estimate, '
    "a default setting or missing data. They describe the numbers, not the investment.</p>"
)

# Plain-language glossary: term -> (one-sentence explanation, link to more). Keys are lower-case.
# Renderers call FA.term("beta") to mark a word; the page shows the explanation on hover/tap and lists it
# with its link in the card's help modal.
GLOSSARY: dict[str, tuple[str, str]] = {
    "volatility": ("How much the value swings from day to day, annualized; higher means bumpier.", "https://www.investopedia.com/terms/v/volatility.asp"),
    "beta": ("How much the portfolio tends to move when the market moves 1%; 0.5 means about half as much.", "https://www.investopedia.com/terms/b/beta.asp"),
    "max drawdown": ("The largest peak-to-trough fall in value over the period shown.", "https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp"),
    "drawdown": ("How far value sits below its previous high.", "https://www.investopedia.com/terms/d/drawdown.asp"),
    "var": ("Value at risk: the one-day loss you would expect to exceed only rarely (for 95%, about one day in twenty).", "https://www.investopedia.com/terms/v/var.asp"),
    "cvar": ("Conditional VaR: the average loss on the worst days beyond the VaR threshold.", "https://www.investopedia.com/terms/c/conditional_value_at_risk.asp"),
    "sharpe ratio": ("Return earned per unit of volatility; higher means more reward for the risk taken.", "https://www.investopedia.com/terms/s/sharperatio.asp"),
    "sortino ratio": ("Like the Sharpe ratio but only counts downside swings as risk.", "https://www.investopedia.com/terms/s/sortinoratio.asp"),
    "correlation": ("How closely two holdings move together, from -1 (opposite) to +1 (in lockstep); low correlation is what diversification relies on.", "https://www.investopedia.com/terms/c/correlation.asp"),
    "diversification ratio": ("Weighted average of the holdings' volatilities divided by the portfolio's; above 1 means the mix is smoother than its parts.", "https://www.investopedia.com/terms/d/diversification.asp"),
    "risk contribution": ("The share of total portfolio volatility that comes from each holding, counting how it co-moves with the rest.", "https://www.investopedia.com/terms/r/riskmanagement.asp"),
    "factor exposure": ("How much the portfolio moves with broad market styles (size, value, momentum, rates), measured against proxy ETFs.", "https://www.investopedia.com/terms/f/factor-investing.asp"),
    "explained variance": ("How much of the portfolio's movement a factor accounts for, from 0% to 100%.", "https://www.investopedia.com/terms/r/r-squared.asp"),
    "liquidity": ("How easily a position can be sold without moving the price; compared here with typical daily dollar volume.", "https://www.investopedia.com/terms/l/liquidity.asp"),
    "stress test": ("What the portfolio would have lost if a past crash repeated with today's holdings.", "https://www.investopedia.com/terms/s/stresstesting.asp"),
    "hhi": ("Herfindahl index: a concentration score from 0 (spread evenly) to 1 (everything in one position).", "https://www.investopedia.com/terms/h/hhi.asp"),
    "concentration": ("How much of the total sits in a few positions.", "https://www.investopedia.com/terms/c/concentrationrisk.asp"),
    "allocation": ("The split of the portfolio across asset types such as stocks, bonds and cash.", "https://www.investopedia.com/terms/a/assetallocation.asp"),
    "sector": ("The part of the economy a company operates in, such as technology or energy.", "https://www.investopedia.com/terms/s/sector.asp"),
    "look-through": ("Counting a fund's underlying holdings as if you held them directly, so a total-market ETF adds to every sector it owns.", "https://www.investopedia.com/terms/l/look-through-earnings.asp"),
    "unrealized p&l": ("Paper gain or loss on holdings you still own, versus what you paid.", "https://www.investopedia.com/terms/u/unrealizedgain.asp"),
    "cost basis": ("What you paid for a holding, used to work out gains and taxes.", "https://www.investopedia.com/terms/c/costbasis.asp"),
    "headline": ("A one-line finding from another Second Opinion skill (watchlist, market, filings, tax, debt and so on), ranked alert, notice or info; NEW means it was not in the last brief.", "https://www.investopedia.com/terms/f/financial-plan.asp"),
    "coverage": ("Which skills contributed to this brief, which were skipped because they are not set up, and which failed.", "https://www.investopedia.com/terms/f/financial-plan.asp"),
    "drift": ("How far an allocation has moved away from its target weight.", "https://www.investopedia.com/terms/p/portfolio-drift.asp"),
    "rebalancing band": ("The tolerance around a target weight; outside it, a trade is flagged.", "https://www.investopedia.com/terms/r/rebalancing.asp"),
    "turnover": ("The share of the portfolio bought or sold to carry out a plan.", "https://www.investopedia.com/terms/t/turnover.asp"),
    "dividend yield": ("Annual dividends divided by the current price.", "https://www.investopedia.com/terms/d/dividendyield.asp"),
    "yield on cost": ("Annual dividends divided by what you paid, rather than today's price.", "https://www.investopedia.com/terms/y/yield-on-cost.asp"),
    "payout ratio": ("The share of earnings paid out as dividends; very high ratios leave less room to keep paying.", "https://www.investopedia.com/terms/p/payoutratio.asp"),
    "ex-dividend date": ("You must own the shares before this date to receive the next dividend.", "https://www.investopedia.com/terms/e/ex-dividend.asp"),
    "trailing 12 months": ("Totals over the last twelve months, whatever the calendar year.", "https://www.investopedia.com/terms/t/ttm.asp"),
    "wash sale": ("Selling at a loss and buying the same thing within 30 days; the tax loss is disallowed.", "https://www.investopedia.com/terms/w/washsalerule.asp"),
    "long-term gain": ("A gain on something held more than a year, taxed at lower rates than short-term.", "https://www.investopedia.com/terms/l/long-term_capital_gain_loss.asp"),
    "tax-loss harvesting": ("Selling losers to offset gains and cut this year's tax bill.", "https://www.investopedia.com/terms/t/taxgainlossharvesting.asp"),
    "loss carryforward": ("Losses beyond what can be used this year, carried into future years.", "https://www.investopedia.com/terms/t/tax-loss-carryforward.asp"),
    "tax lot": ("One batch of shares bought at one time and price; which lots you sell changes the tax.", "https://www.investopedia.com/terms/t/taxlotaccounting.asp"),
    "fifo": ("First in, first out: the oldest shares are treated as sold first.", "https://www.investopedia.com/terms/f/fifo.asp"),
    "monte carlo": ("Thousands of simulated futures with random market returns, to show a range of outcomes rather than one number.", "https://www.investopedia.com/terms/m/montecarlosimulation.asp"),
    "success odds": ("The share of simulated futures in which the money lasts the whole plan.", "https://www.investopedia.com/terms/m/montecarlosimulation.asp"),
    "sustainable withdrawal rate": ("The yearly share of savings you can spend with a good chance of not running out.", "https://www.investopedia.com/terms/f/four-percent-rule.asp"),
    "nest egg": ("The savings needed at retirement to fund the planned spending.", "https://www.investopedia.com/terms/n/nestegg.asp"),
    "percentile": ("Where an outcome ranks: the 10th percentile is worse than 90% of simulations.", "https://www.investopedia.com/terms/p/percentile.asp"),
    "amortization": ("How each loan payment splits between interest and paying down the balance over time.", "https://www.investopedia.com/terms/a/amortization.asp"),
    "piti": ("Principal, interest, taxes and insurance: the full monthly housing payment.", "https://www.investopedia.com/terms/p/piti.asp"),
    "noi": ("Net operating income: rent minus operating costs, before the mortgage.", "https://www.investopedia.com/terms/n/noi.asp"),
    "cap rate": ("Net operating income divided by the property price; a yield-like measure for property.", "https://www.investopedia.com/terms/c/capitalizationrate.asp"),
    "dscr": ("Debt service coverage: operating income divided by loan payments; below 1.2 lenders get nervous.", "https://www.investopedia.com/terms/d/dscr.asp"),
    "irr": ("Internal rate of return: the annual return that accounts for when each cash flow happens.", "https://www.investopedia.com/terms/i/irr.asp"),
    "cash-on-cash return": ("Yearly cash flow divided by the cash you put in.", "https://www.investopedia.com/terms/c/cashoncashreturn.asp"),
    "ffo": ("Funds from operations: a REIT's earnings with property depreciation added back.", "https://www.investopedia.com/terms/f/fundsfromoperation.asp"),
    "affo": ("Adjusted FFO: FFO minus the upkeep spending needed to maintain the properties.", "https://www.investopedia.com/terms/a/affo.asp"),
    "nav": ("Net asset value: what the assets are worth minus debts, per share.", "https://www.investopedia.com/terms/n/nav.asp"),
    "reit": ("A company that owns income-producing property and pays most of its income out as dividends.", "https://www.investopedia.com/terms/r/reit.asp"),
    "savings rate": ("The share of income not spent.", "https://www.investopedia.com/terms/s/savings-rate.asp"),
    "recurring charge": ("A payment that repeats on a schedule, such as a subscription.", "https://www.investopedia.com/terms/s/subscription-business-model.asp"),
    "apr": ("Annual percentage rate: the yearly cost of borrowing, including fees.", "https://www.investopedia.com/terms/a/apr.asp"),
    "utilization": ("Card balance divided by the credit limit; high utilization weighs on credit scores.", "https://www.investopedia.com/terms/c/credit-utilization-rate.asp"),
    "minimum payment": ("The smallest amount due to keep the account in good standing; paying only this keeps interest running.", "https://www.investopedia.com/terms/m/minimum-monthly-payment.asp"),
    "revolving debt": ("Debt you can draw and repay repeatedly, such as credit cards.", "https://www.investopedia.com/terms/r/revolvingcredit.asp"),
    "installment debt": ("A loan repaid in fixed payments over a set term, such as a car loan.", "https://www.investopedia.com/terms/i/installmentdebt.asp"),
    "round trip": ("A buy and its matching sell, treated as one trade.", "https://www.investopedia.com/terms/r/roundtriptrading.asp"),
    "win rate": ("The share of closed trades that made money.", "https://www.investopedia.com/terms/w/win-loss-ratio.asp"),
    "disposition effect": ("The tendency to sell winners too early and hold losers too long.", "https://www.investopedia.com/terms/d/disposition.asp"),
    "buy-and-hold counterfactual": ("What the position would be worth today had it not been sold.", "https://www.investopedia.com/terms/b/buyandhold.asp"),
    "drift after sale": ("How the price moved in the weeks after you sold; a rise means the sale was early.", "https://www.investopedia.com/terms/o/opportunitycost.asp"),
    "moving average": ("The average price over the last N days; the 50- and 200-day lines are common trend markers.", "https://www.investopedia.com/terms/m/movingaverage.asp"),
    "momentum": ("Recent price trend; here the return over the past year excluding the latest month.", "https://www.investopedia.com/terms/m/momentum.asp"),
    "atr": ("Average true range: the typical size of a day's price move.", "https://www.investopedia.com/terms/a/atr.asp"),
    "relative volume": ("Today's trading volume compared with the recent average.", "https://www.investopedia.com/terms/v/volume.asp"),
    "support and resistance": ("Price levels where falls have tended to stop (support) or rises to stall (resistance).", "https://www.investopedia.com/trading/support-and-resistance-basics/"),
    "52-week high": ("The highest price in the past year.", "https://www.investopedia.com/terms/1/52weekhighlow.asp"),
    "implied volatility": ("The size of price move the options market is pricing in.", "https://www.investopedia.com/terms/i/iv.asp"),
    "expected move": ("The range the options market implies the price will stay within by expiry, about two thirds of the time.", "https://www.investopedia.com/terms/e/expected-move.asp"),
    "term structure": ("How implied volatility differs across expiry dates.", "https://www.investopedia.com/terms/t/termstructure.asp"),
    "delta": ("How much an option's price changes when the stock moves $1.", "https://www.investopedia.com/terms/d/delta.asp"),
    "gamma": ("How fast delta itself changes as the stock moves.", "https://www.investopedia.com/terms/g/gamma.asp"),
    "theta": ("How much an option loses per day from time passing.", "https://www.investopedia.com/terms/t/theta.asp"),
    "vega": ("How much an option's price changes when implied volatility moves one point.", "https://www.investopedia.com/terms/v/vega.asp"),
    "open interest": ("The number of option contracts currently outstanding.", "https://www.investopedia.com/terms/o/openinterest.asp"),
    "max pain": ("The strike where the most options expire worthless, sometimes a magnet near expiry.", "https://www.investopedia.com/terms/m/maxpain.asp"),
    "breakeven": ("The price at expiry where the position neither makes nor loses money.", "https://www.investopedia.com/terms/b/breakevenpoint.asp"),
    "assignment": ("Being required to buy or sell the shares because an option you sold was exercised.", "https://www.investopedia.com/terms/a/assignment.asp"),
    "dcf": ("Discounted cash flow: today's value of the cash a business is expected to produce.", "https://www.investopedia.com/terms/d/dcf.asp"),
    "wacc": ("The blended cost of a company's debt and equity, used as the discount rate.", "https://www.investopedia.com/terms/w/wacc.asp"),
    "terminal value": ("The value of all cash flows beyond the forecast years; often most of a DCF.", "https://www.investopedia.com/terms/t/terminalvalue.asp"),
    "terminal growth": ("The steady growth rate assumed forever after the forecast years.", "https://www.investopedia.com/terms/t/terminalvalue.asp"),
    "graham number": ("A ceiling price from earnings and book value, from Benjamin Graham's defensive-investor rules.", "https://www.investopedia.com/terms/g/graham-number.asp"),
    "owner earnings": ("Warren Buffett's cash-earnings measure: profit plus depreciation minus the spending needed to maintain the business.", "https://www.investopedia.com/terms/o/owner-earnings-run-rate.asp"),
    "margin of safety": ("How far the price sits below an estimate of value; the cushion against being wrong.", "https://www.investopedia.com/terms/m/marginofsafety.asp"),
    "p/e": ("Price divided by earnings per share; how many years of profit you pay for.", "https://www.investopedia.com/terms/p/price-earningsratio.asp"),
    "p/b": ("Price divided by book value per share.", "https://www.investopedia.com/terms/p/price-to-bookratio.asp"),
    "ev/ebitda": ("Enterprise value divided by operating cash profit, a debt-aware price multiple.", "https://www.investopedia.com/terms/e/ev-ebitda.asp"),
    "ddm": ("Dividend discount model: value from the dividends expected in future.", "https://www.investopedia.com/terms/d/ddm.asp"),
    "roe": ("Return on equity: profit divided by shareholders' equity.", "https://www.investopedia.com/terms/r/returnonequity.asp"),
    "free cash flow": ("Cash from operations minus capital spending; what is left to pay owners.", "https://www.investopedia.com/terms/f/freecashflow.asp"),
    "net current asset value": ("Current assets minus all liabilities; Graham's liquidation floor.", "https://www.investopedia.com/terms/n/ncavps.asp"),
    "bonds": ("Loans to governments or companies that pay interest; steadier than stocks, sensitive to interest rates.", "https://www.investopedia.com/terms/b/bond.asp"),
    "etf": ("Exchange-traded fund: a basket of holdings that trades like a single stock.", "https://www.investopedia.com/terms/e/etf.asp"),
    "money market fund": ("A cash-like fund holding very short-term debt.", "https://www.investopedia.com/terms/m/money-marketfund.asp"),
    "margin": ("Borrowing from the broker against your holdings; a negative cash balance is a margin loan.", "https://www.investopedia.com/terms/m/margin.asp"),
}

CSS = """
:root{color-scheme:light;
 --page:#f7f7f5;--surface:#fdfdfc;--ink:#111110;--ink2:#4f4e4a;--muted:#86847e;--grid:#e3e2dc;--ring:rgba(17,17,16,.10);
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#4a3aa7;--s8:#e34948;
 --up:#006300;--down:#d03b3b;--warn:#8a5a00;--tip:#fdfdfc}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;
 --page:#0e0e0d;--surface:#1a1a19;--ink:#f4f4f1;--ink2:#c3c2b7;--muted:#8b8a84;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;--s8:#e66767;
 --up:#0ca30c;--down:#e66767;--warn:#e0a020;--tip:#1a1a19}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0e0e0d;--surface:#1a1a19;--ink:#f4f4f1;--ink2:#c3c2b7;--muted:#8b8a84;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;--s8:#e66767;
 --up:#0ca30c;--down:#e66767;--warn:#e0a020;--tip:#1a1a19}
body{background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
 padding-block:24px 48px;padding-inline:clamp(16px,4vw,44px);max-width:1120px;margin-inline:auto}
[hidden]{display:none!important}
h1{font-size:24px;font-weight:650;letter-spacing:-.01em;margin:0 0 2px;text-wrap:balance}
h2{font-size:15px;font-weight:600;margin:0 0 8px}
.sub{color:var(--ink2);margin:0 0 20px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:6px;padding:12px 14px}
.tile .k{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.tile .v{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.tile .d{font-size:12px;color:var(--ink2)}
.pos{color:var(--up)}.neg{color:var(--down)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:6px;padding:14px 16px;position:relative}
section{margin-bottom:24px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.controls input,.controls select{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--grid);border-radius:5px;padding:5px 8px}
.controls input:focus,.controls select:focus,button:focus-visible,th:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--grid);border-radius:999px;padding:3px 10px;font-size:12px;color:var(--ink2);background:var(--surface);cursor:pointer}
.chip[aria-pressed="true"]{border-color:var(--s1);color:var(--ink)}
.twrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child,th.l,td.l{text-align:left}
th{color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.05em;text-transform:uppercase;cursor:pointer;user-select:none}
th[aria-sort="ascending"]::after{content:" \\2191"}th[aria-sort="descending"]::after{content:" \\2193"}
tbody tr:hover{background:color-mix(in srgb,var(--s1) 6%,transparent)}
.bar{display:grid;grid-template-columns:minmax(90px,1fr) 4fr auto;gap:10px;align-items:center;font-size:13px;padding:3px 0}
.bar .track{height:12px;background:var(--grid);border-radius:3px;overflow:hidden}
.bar .fill{height:100%;border-radius:3px}
.bar .n{color:var(--ink2);font-variant-numeric:tabular-nums;min-width:60px;text-align:right}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--ink2);margin-top:8px}
.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:10px;height:10px;border-radius:2px;display:inline-block}
svg{display:block;max-width:100%;height:auto;overflow:visible}
.tip{position:fixed;pointer-events:none;background:var(--tip);border:1px solid var(--ring);border-radius:5px;padding:6px 9px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.14);display:none;z-index:9;white-space:nowrap}
.news{list-style:none;padding:0 0 6px 0;margin:0 0 4px 0;font-size:12.5px}
.news li{padding:2px 0 2px 12px;border-left:2px solid var(--grid);margin-left:4px}
.news a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--grid)}
table.heat th,table.heat td{padding:4px 6px;font-size:12px}
table.heat td{color:var(--ink)}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:8px 0}
.flow .box{display:flex;flex-direction:column;border:1px solid var(--grid);border-radius:5px;padding:5px 9px;min-width:0}
.flow .box .k{font-size:11px;color:var(--muted)}.flow .box .v{font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink)}
.flow .box.last{border-color:var(--s1);background:color-mix(in srgb,var(--s1) 10%,transparent)}
.flow .op{color:var(--muted);font-weight:600}
table.heat td.base{outline:2px solid var(--ink);outline-offset:-2px;font-weight:700}
table.heat.mini{width:auto}table.heat.mini td{width:44px}
.readgrid-cap{margin:0 0 6px;font-size:12.5px;color:var(--ink2)}
.readgrid-notes{margin:8px 0 0;padding-left:18px;font-size:12.5px;color:var(--ink2)}
.tip .r{display:flex;justify-content:space-between;gap:12px}
.term{border-bottom:1px dotted var(--muted);cursor:help}
.card-help{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;margin-left:8px;border-radius:50%;border:1px solid var(--muted);background:none;color:var(--muted);font:inherit;font-size:12px;line-height:1;cursor:pointer;vertical-align:middle;padding:0}
.card-help:hover{color:var(--ink);border-color:var(--ink)}
.modal .help-lead{font-size:14px;color:var(--ink);margin:6px 0 12px}
.modal .help-sec{margin:12px 0}.modal .help-sec h4,.modal .help-terms h4{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin:0 0 6px;font-weight:600}
.modal .help-sec p{margin:6px 0;color:var(--ink2);font-size:13px}
.modal .help-terms ul{list-style:none;padding:0;margin:0;font-size:13px;color:var(--ink2)}.modal .help-terms li{padding:4px 0;border-top:1px solid var(--grid)}
.modal .help-terms b{color:var(--ink);font-weight:600}.modal .help-terms a{color:var(--s1);white-space:nowrap}
.explain{background:var(--surface);border:1px solid var(--ring);border-left:3px solid var(--s1);border-radius:0 6px 6px 0;padding:10px 14px;margin:0 0 20px;font-size:13px;max-width:78ch}
.explain summary{font-weight:600;color:var(--ink)}
.explain p{margin:8px 0 0;color:var(--ink2)}
.tip.wide{white-space:normal;max-width:320px}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:flex-start;justify-content:center;padding:6vh 16px;z-index:20;overflow:auto}
.modal{background:var(--surface);color:var(--ink);border:1px solid var(--ring);border-radius:8px;max-width:760px;width:100%;padding:18px 20px;box-shadow:0 12px 40px rgba(0,0,0,.3);position:relative}
.modal .x{position:absolute;top:8px;right:10px;font:inherit;background:none;border:0;color:var(--muted);font-size:20px;cursor:pointer;line-height:1}
.modal h3{margin:0 24px 4px 0;font-size:18px}
.modal .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px;margin:10px 0}
.modal .kv dt{color:var(--muted)}.modal .kv dd{margin:0}
.clickable{cursor:pointer}
.flags{list-style:none;padding:0;margin:0}
.flags li{padding:6px 10px;border-left:3px solid var(--warn);background:var(--surface);border-radius:0 4px 4px 0;margin-bottom:6px;font-size:13px}
.flags li b{font-weight:600;margin-right:6px}
.hl{list-style:none;padding:0;margin:0}
.hl li{display:flex;gap:10px;align-items:flex-start;padding:7px 10px;border-radius:4px;margin-bottom:4px;background:var(--surface);border:1px solid var(--grid)}
.hl .dot{width:9px;height:9px;border-radius:50%;margin-top:6px;flex:none}
.sev-alert .dot{background:var(--down)}.sev-notice .dot{background:var(--warn)}.sev-info .dot{background:var(--s1)}
.hl .body{flex:1;min-width:0}.hl .t{font-weight:500}.hl .d{color:var(--ink2);font-size:12px;margin-top:2px}
.pill{display:inline-block;border-radius:999px;padding:1px 7px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;margin-left:6px;vertical-align:middle}
.pill-new{background:var(--down);color:#fff}.pill-lead{margin-left:0;margin-right:6px}.pill-skill{border:1px solid var(--grid);color:var(--muted)}
.cov{font-size:12px;color:var(--ink2)}.cov table{width:100%;font-size:12px}.cov .ok{color:var(--up)}.cov .skipped{color:var(--muted)}.cov .failed{color:var(--down)}
.hl-totals{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.hl-totals .tot{display:inline-flex;align-items:center;gap:6px}
.hl li.toggle{cursor:pointer}.hl li.toggle:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.hl li .more{margin-top:2px}
#hl-more{margin:6px 0 10px}
.hl .why{font-style:italic;color:var(--ink2);font-size:12px}
.hl .answer{font-size:13px;margin-top:2px}
.hl-link{margin-left:8px;font-size:12px;white-space:nowrap}
.muted{color:var(--muted)}
.note{color:var(--muted);font-size:12px;margin-top:12px;max-width:70ch}
details summary{cursor:pointer;color:var(--ink2);font-size:13px}
.intro{display:flex;gap:12px 16px;align-items:center;flex-wrap:wrap;margin:0 0 20px}
.intro p{margin:0;color:var(--ink2);font-size:14px;max-width:72ch;flex:1 1 320px}
.btn{font:inherit;font-size:13px;border:1px solid var(--s1);color:var(--ink);background:var(--surface);border-radius:999px;padding:5px 14px;cursor:pointer;white-space:nowrap}
.btn:hover{background:color-mix(in srgb,var(--s1) 10%,var(--surface))}
.btn.quiet{border-color:var(--grid);color:var(--ink2)}
.tour-card{position:fixed;right:16px;bottom:16px;width:min(400px,calc(100vw - 32px));background:var(--surface);color:var(--ink);border:1px solid var(--ring);border-top:3px solid var(--s1);border-radius:8px;padding:14px 16px;box-shadow:0 12px 40px rgba(0,0,0,.28);z-index:30;font-size:13.5px}
.tour-card .step{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.tour-card h3{margin:2px 24px 6px 0;font-size:16px}
.tour-card p{margin:6px 0 0;color:var(--ink2)}
.tour-card .x{position:absolute;top:6px;right:8px;font:inherit;background:none;border:0;color:var(--muted);font-size:20px;cursor:pointer;line-height:1}
.tour-card .nav{display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:8px}
.tour-on{outline:3px solid var(--s1);outline-offset:4px;border-radius:6px}
@media (prefers-reduced-motion:no-preference){.bar .fill{transition:width .25s}}
"""

JS = r"""
const FA = (() => {
  const S = ['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)','var(--s6)','var(--s7)','var(--s8)'];
  const isNum = v => typeof v === 'number' && Number.isFinite(v);
  const money = (v, dp = 2) => isNum(v) ? (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: dp, maximumFractionDigits: dp}) : '—';
  const moneyS = v => isNum(v) ? (v > 0 ? '+' : v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
  // compact money for axes, tiles and large totals: $335.5B, -$1.4M, $820k, $95
  const moneyC = v => { if (!isNum(v)) return '—'; const a = Math.abs(v), sg = v < 0 ? '-' : '';
    if (a >= 1e12) return sg + '$' + (a / 1e12).toFixed(1).replace(/\.0$/, '') + 'T';
    if (a >= 1e9) return sg + '$' + (a / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (a >= 1e6) return sg + '$' + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (a >= 1e3) return sg + '$' + (a / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return sg + '$' + a.toFixed(0); };
  // round-number axis ticks covering [lo, hi]: the step (1, 2, 2.5 or 5 x 10^k) giving 4-8 ticks that wastes the least range
  const niceTicks = (lo, hi) => { if (!(hi > lo)) return [lo]; const mag = Math.pow(10, Math.floor(Math.log10((hi - lo) / 5))); let best = null;
    for (const m of [0.1, 1, 10]) for (const f of [1, 2, 2.5, 5]) { const step = f * m * mag; const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
      const count = Math.round((b - a) / step) + 1; if (count < 4 || count > 8) continue; const waste = (b - a) / (hi - lo) + count * 0.05;
      if (!best || waste < best.waste) best = {a, step, count, waste}; }
    if (!best) return [lo, hi]; const out = []; for (let k = 0; k < best.count; k++) { const t = best.a + k * best.step; out.push(Math.abs(t) < best.step * 1e-9 ? 0 : +t.toPrecision(12)); } return out; };
  const pct = (v, dp = 1, sign = false) => isNum(v) ? ((sign && v > 0) ? '+' : '') + (100 * v).toFixed(dp) + '%' : '—';
  const num = (v, dp = 2) => isNum(v) ? v.toLocaleString('en-US', {minimumFractionDigits: dp, maximumFractionDigits: dp}) : '—';
  const cls = v => isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : '';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const el = (tag, attrs = {}, html = '') => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); e.innerHTML = html; return e; };
  // tooltip
  let tipEl;
  const tip = { show(ev, html) { if (!tipEl) { tipEl = el('div', {class: 'tip'}); document.body.appendChild(tipEl); } tipEl.innerHTML = html; tipEl.style.display = 'block'; this.move(ev); },
                move(ev) { if (!tipEl) return; const x = ev.clientX + 14, y = ev.clientY + 12; tipEl.style.left = Math.min(x, window.innerWidth - tipEl.offsetWidth - 8) + 'px'; tipEl.style.top = y + 'px'; },
                hide() { if (tipEl) tipEl.style.display = 'none'; } };
  const bindTip = (node, html) => { node.addEventListener('mousemove', ev => tip.show(ev, typeof html === 'function' ? html() : html)); node.addEventListener('mouseleave', () => tip.hide()); };
  // horizontal bar list: rows = [{label, value, share (0..1), color, tip}]
  const bars = (root, rows) => {
    root.innerHTML = '';
    const max = Math.max(...rows.map(r => Math.abs(r.share || 0)), 1e-9);
    for (const r of rows) {
      const row = el('div', {class: 'bar'});
      row.appendChild(el('span', {class: 'l'}, esc(r.label)));
      const track = el('div', {class: 'track'});
      const fill = el('div', {class: 'fill'}); fill.style.width = (100 * Math.abs(r.share || 0) / max) + '%'; fill.style.background = r.color || S[0];
      track.appendChild(fill); row.appendChild(track);
      row.appendChild(el('span', {class: 'n'}, esc(r.text ?? pct(r.share))));
      if (r.tip) bindTip(row, r.tip);
      root.appendChild(row);
    }
  };
  // donut: parts = [{label, value, color}]
  const donut = (root, parts, centerLabel) => {
    const total = parts.reduce((a, p) => a + (p.value || 0), 0) || 1;
    const R = 60, r = 38, cx = 80, cy = 80; let a0 = -Math.PI / 2; let svg = `<svg viewBox="0 0 160 160" width="160" height="160" role="img" aria-label="${esc(centerLabel)}">`;
    parts.forEach((p, i) => { const a1 = a0 + 2 * Math.PI * (p.value || 0) / total; const big = a1 - a0 > Math.PI ? 1 : 0;
      const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0), x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      const xi0 = cx + r * Math.cos(a1), yi0 = cy + r * Math.sin(a1), xi1 = cx + r * Math.cos(a0), yi1 = cy + r * Math.sin(a0);
      svg += `<path data-i="${i}" d="M${x0.toFixed(2)} ${y0.toFixed(2)} A${R} ${R} 0 ${big} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} L${xi0.toFixed(2)} ${yi0.toFixed(2)} A${r} ${r} 0 ${big} 0 ${xi1.toFixed(2)} ${yi1.toFixed(2)} Z" fill="${p.color || S[i % 8]}" stroke="var(--surface)" stroke-width="2"/>`; a0 = a1; });
    svg += `<text x="${cx}" y="${cy + 4}" text-anchor="middle" font-size="12" fill="var(--ink2)">${esc(centerLabel)}</text></svg>`;
    root.innerHTML = svg;
    root.querySelectorAll('path').forEach(pth => { const p = parts[+pth.dataset.i]; bindTip(pth, `<b>${esc(p.label)}</b> ${pct(p.value / total)} · ${money(p.value, 0)}`); });
    const lg = el('div', {class: 'legend'}); parts.forEach((p, i) => lg.appendChild(el('span', {}, `<i style="background:${p.color || S[i % 8]}"></i>${esc(p.label)} ${pct(p.value / total)}`))); root.appendChild(lg);
  };
  // sortable, filterable table. cols = [{key, label, fmt, cls, left}], rows = objects
  const table = (root, cols, rows, opts = {}) => {
    let sortKey = opts.sortKey || cols[0].key, desc = opts.desc !== false, filter = () => true, query = '';
    const t = el('table'); const thead = el('thead'); const tr = el('tr');
    cols.forEach(c => { const th = el('th', {tabindex: '0', class: c.left ? 'l' : ''}, esc(c.label)); th.addEventListener('click', () => { if (sortKey === c.key) desc = !desc; else { sortKey = c.key; desc = true; } draw(); }); th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); th.click(); } }); th.dataset.key = c.key; tr.appendChild(th); });
    thead.appendChild(tr); t.appendChild(thead); const tb = el('tbody'); t.appendChild(tb); root.innerHTML = ''; root.appendChild(t);
    const draw = () => {
      const q = query.toLowerCase();
      const vis = rows.filter(filter).filter(r => !q || cols.some(c => String(r[c.key] ?? '').toLowerCase().includes(q)));
      vis.sort((a, b) => { const x = a[sortKey], y = b[sortKey]; const nx = x == null, ny = y == null; if (nx && ny) return 0; if (nx) return 1; if (ny) return -1; const d = typeof x === 'number' ? x - y : String(x).localeCompare(String(y)); return desc ? -d : d; });
      thead.querySelectorAll('th').forEach(th => th.setAttribute('aria-sort', th.dataset.key === sortKey ? (desc ? 'descending' : 'ascending') : 'none'));
      tb.innerHTML = vis.map(r => '<tr>' + cols.map(c => `<td class="${c.left ? 'l ' : ''}${c.cls ? c.cls(r[c.key], r) : ''}">${c.fmt ? c.fmt(r[c.key], r) : esc(r[c.key])}</td>`).join('') + '</tr>').join('');
      if (opts.onDraw) opts.onDraw(vis);
    };
    draw();
    return { setFilter(fn) { filter = fn; draw(); }, setQuery(q) { query = q; draw(); }, redraw: draw };
  };
  // line / area chart with bands and a crosshair tooltip.
  // opts = {series:[{name, points:[[x,y]...], color, area}], bands:[{name, lo:[[x,y]], hi:[[x,y]], color}],
  //         xFmt, yFmt, height, yMin, yMax, xIsDate, zeroLine, xTicks (explicit x positions), endLabels (false: legend only)}
  const lines = (root, opts) => {
    const series = opts.series || [], bands = opts.bands || [];
    const W = 960, H = opts.height || 280, m = {t: 12, r: 96, b: 30, l: 60};
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const xs = [], ys = [];
    for (const s of series) for (const [x, y] of s.points) { if (isNum(y)) { xs.push(+x); ys.push(y); } }
    for (const b of bands) for (const arr of [b.lo, b.hi]) for (const [x, y] of arr) { if (isNum(y)) { xs.push(+x); ys.push(y); } }
    if (!xs.length) { root.innerHTML = '<span class="muted">no data</span>'; return; }
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = opts.yMin ?? Math.min(...ys), y1 = opts.yMax ?? Math.max(...ys);
    if (opts.zeroLine) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
    if (y1 === y0) { y1 = y0 + 1; }
    // data that never goes negative gets an axis that does not either
    const floor0 = opts.yMin == null && y0 >= 0;
    const pad = (y1 - y0) * 0.05; if (opts.yMin == null) y0 = floor0 ? Math.max(0, y0 - pad) : y0 - pad; if (opts.yMax == null) y1 += pad;
    const ticks = niceTicks(y0, y1).filter(t => !floor0 || t >= 0).filter(t => (opts.yMin == null || t >= opts.yMin) && (opts.yMax == null || t <= opts.yMax));
    if (opts.yMin == null) y0 = Math.min(y0, ticks[0]); if (opts.yMax == null) y1 = Math.max(y1, ticks[ticks.length - 1]);
    const X = x => m.l + iw * (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)), Y = y => m.t + ih * (1 - (y - y0) / (y1 - y0));
    const xFmt = opts.xFmt || (opts.xIsDate ? (x => new Date(x).toLocaleDateString('en-US', {month: 'short', year: '2-digit'})) : (x => String(x)));
    const yFmt = opts.yFmt || (y => num(y, 0));
    const xt = []; let lastX = null; for (const t of (opts.xTicks || [0, 1, 2, 3, 4, 5].map(k => x0 + (x1 - x0) * k / 5))) { const lab = xFmt(t); if (lab !== lastX) xt.push(t); lastX = lab; }
    let g = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || 'chart')}">`;
    g += ticks.map(t => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="var(--grid)"/>`).join('');
    g += ticks.map(t => `<text x="${m.l - 8}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc(yFmt(t))}</text>`).join('');
    g += xt.map(t => `<text x="${X(t).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(xFmt(t))}</text>`).join('');
    if (opts.zeroLine) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="var(--muted)" stroke-dasharray="2 3"/>`;
    bands.forEach((b, i) => { const lo = b.lo.filter(p => isNum(p[1])), hi = b.hi.filter(p => isNum(p[1]));
      const path = hi.map((p, j) => (j ? 'L' : 'M') + X(+p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('') + lo.slice().reverse().map(p => 'L' + X(+p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('') + 'Z';
      g += `<path d="${path}" fill="${b.color || S[i % 8]}" opacity="0.18"/>`; });
    series.forEach((s, i) => { const pts = s.points.filter(p => isNum(p[1])); const color = s.color || S[i % 8];
      const d = pts.map((p, j) => (j ? 'L' : 'M') + X(+p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
      if (s.area && pts.length) g += `<path d="${d}L${X(+pts[pts.length - 1][0]).toFixed(1)} ${Y(opts.zeroLine ? 0 : y0).toFixed(1)}L${X(+pts[0][0]).toFixed(1)} ${Y(opts.zeroLine ? 0 : y0).toFixed(1)}Z" fill="${color}" opacity="0.12"/>`;
      g += `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
      if (pts.length && opts.endLabels !== false) { const last = pts[pts.length - 1]; g += `<text x="${W - m.r + 8}" y="${(Y(last[1]) + 4).toFixed(1)}" font-size="11.5" font-weight="600" fill="var(--ink)">${esc(s.name)}</text>`; } });
    g += `<line id="cx" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)" stroke-dasharray="3 3" opacity="0"/>`;
    g += `<rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    root.innerHTML = g;
    if (series.length > 1) { const lg = el('div', {class: 'legend'}); series.forEach((s, i) => lg.appendChild(el('span', {}, `<i style="background:${s.color || S[i % 8]}"></i>${esc(s.name)}`))); root.appendChild(lg); }
    const svg = root.querySelector('svg'), hit = svg.querySelector('#hit'), cx = svg.querySelector('#cx');
    hit.addEventListener('mousemove', ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) * W / r.width; const xv = x0 + (px - m.l) / iw * (x1 - x0);
      cx.setAttribute('x1', px); cx.setAttribute('x2', px); cx.setAttribute('opacity', 1);
      const rows = series.map((s, i) => { let best = null; for (const p of s.points) { if (isNum(p[1]) && (best === null || Math.abs(+p[0] - xv) < Math.abs(+best[0] - xv))) best = p; } return best ? `<div class="r"><span><i style="background:${s.color || S[i % 8]};width:8px;height:8px;display:inline-block;border-radius:2px;margin-right:5px"></i>${esc(s.name)}</span><b>${esc(yFmt(best[1]))}</b></div>` : ''; }).join('');
      tip.show(ev, `<div style="color:var(--ink2);margin-bottom:3px">${esc(xFmt(xv))}</div>${rows}`); });
    hit.addEventListener('mouseleave', () => { cx.setAttribute('opacity', 0); tip.hide(); });
  };
  // heatmap: opts = {rows:[labels], cols:[labels], values:[[..]], fmt, diverging (blue/red around 0), min, max}
  const heatmap = (root, opts) => {
    const {rows, cols, values} = opts; const fmt = opts.fmt || (v => num(v, 2));
    const flat = values.flat().filter(isNum); let lo = opts.min ?? Math.min(...flat), hi = opts.max ?? Math.max(...flat);
    if (opts.diverging) { const a = Math.max(Math.abs(lo), Math.abs(hi)); lo = -a; hi = a; }
    const color = v => { if (!isNum(v)) return 'var(--grid)'; const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      if (opts.diverging) { return t < 0.5 ? `color-mix(in oklab, var(--s1) ${Math.round((0.5 - t) * 2 * 100)}%, var(--grid))` : `color-mix(in oklab, var(--s8) ${Math.round((t - 0.5) * 2 * 100)}%, var(--grid))`; }
      return `color-mix(in oklab, var(--s1) ${Math.round(15 + t * 85)}%, var(--surface))`; };
    let h = '<div class="twrap"><table class="heat"><thead><tr><th class="l"></th>' + cols.map(c => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>';
    rows.forEach((r, i) => { h += `<tr><td class="l">${esc(r)}</td>` + cols.map((c, j) => { const v = values[i][j]; return `<td style="background:${color(v)};text-align:center" data-r="${i}" data-c="${j}">${isNum(v) ? esc(fmt(v)) : '—'}</td>`; }).join('') + '</tr>'; });
    root.innerHTML = h + '</tbody></table></div>';
    root.querySelectorAll('td[data-r]').forEach(td => bindTip(td, `<b>${esc(rows[+td.dataset.r])}</b> × <b>${esc(cols[+td.dataset.c])}</b>: ${esc(isNum(values[+td.dataset.r][+td.dataset.c]) ? fmt(values[+td.dataset.r][+td.dataset.c]) : '—')}`));
  };
  // glossary: FA.term('beta') or FA.term('beta', 'Beta (vs SPY)') -> marked word with hover explanation
  const G = window.GLOSSARY || {};
  const term = (key, label) => { const k = String(key).toLowerCase(); const e = G[k]; const txt = esc(label ?? key);
    if (!e) return txt; return `<span class="term" data-term="${esc(k)}" tabindex="0">${txt}</span>`; };
  const armTerms = root => { (root || document).querySelectorAll('.term[data-term]').forEach(n => { if (n.dataset.armed) return; n.dataset.armed = '1'; const e = G[n.dataset.term]; if (!e) return;
    const show = ev => { tip.show(ev.clientX != null ? ev : {clientX: n.getBoundingClientRect().left, clientY: n.getBoundingClientRect().bottom}, `<div class="wide">${esc(e[0])}</div>`); if (tipEl) tipEl.classList.add('wide'); };
    const hide = () => { tip.hide(); if (tipEl) tipEl.classList.remove('wide'); };
    n.addEventListener('mousemove', show); n.addEventListener('mouseleave', hide); n.addEventListener('focus', show); n.addEventListener('blur', hide); }); };
  // explain: a collapsible "What am I looking at?" box at the top of a page; html may use FA.term()
  // Its first paragraph becomes the one-line lead and every later paragraph a walkthrough step, so the
  // page opens on a sentence rather than a wall. ``steps`` (optional) are extra targeted steps
  // ({target, title, html}) that run after the paragraphs, outlining the sections they explain.
  const explain = (root, html, open = true, steps = []) => {
    const box = document.createElement('div'); box.innerHTML = html;
    const paras = [...box.children].filter(n => n.tagName === 'P' && n.textContent.trim());
    if (!paras.length) { root.innerHTML = `<details class="explain"${open ? ' open' : ''}><summary>What am I looking at?</summary>${html}</details>`; armTerms(root); return; }
    // A long opening paragraph keeps only its first sentence as the lead; the rest become steps, two sentences each.
    const sentences = paras[0].innerHTML.split(/(?<=[.!?])\s+(?=[A-Z<])/);
    const long = paras[0].textContent.length > 240 && sentences.length > 1;
    const lead = long ? sentences[0] : paras[0].innerHTML, extra = [];
    if (long) for (let k = 1; k < sentences.length; k += 2) extra.push(sentences.slice(k, k + 2).join(' '));
    const rest = [...extra, ...paras.slice(1).map(n => n.innerHTML)].map(h => ({target: null, title: 'How to read this page', html: `<p>${h}</p>`}));
    intro(root, {lead, steps: [...rest, ...steps]}); };
  // modal: FA.modal(html) opens an overlay; returns the modal element. Esc / backdrop / × close it.
  const modal = html => { const ov = el('div', {class: 'overlay', role: 'dialog', 'aria-modal': 'true'}); const box = el('div', {class: 'modal'}, `<button class="x" aria-label="Close">×</button>${html}`);
    ov.appendChild(box); document.body.appendChild(ov); const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = e => { if (e.key === 'Escape') close(); }; document.addEventListener('keydown', onKey);
    ov.addEventListener('click', e => { if (e.target === ov) close(); }); box.querySelector('.x').addEventListener('click', close); box.querySelector('.x').focus(); armTerms(box); return box; };
  // card help: FA.help(card, {lead, sections}) -> one ⓘ button in the card's h2 opening a modal with the
  // lead, the sections (html or render(el)) and "Terms on this card"; FA.armHelp gives every card with
  // glossary terms a terms-only button. Both are idempotent; armHelp re-adds a button an h2 rewrite removed.
  const termsIn = card => { const seen = new Set(), out = [];
    card.querySelectorAll('.term[data-term]').forEach(n => { const k = n.dataset.term; if (seen.has(k) || !G[k]) return; seen.add(k);
      // the card's own wording when it names the term ("WACC", "fair value / share"); else the term itself ("Long-term date" -> "Long-term gain")
      const lab = n.textContent.trim(), name = lab.toLowerCase().includes(k) ? lab : k; out.push({key: k, label: name.charAt(0).toUpperCase() + name.slice(1), def: G[k][0], url: G[k][1]}); }); return out; };
  const openHelp = card => { const spec = card._faHelp || {}, secs = spec.sections || [], terms = termsIn(card);
    const box = modal(`<h3>${esc(helpTitle(card.querySelector(':scope > h2')))}</h3>` + (spec.lead ? `<p class="help-lead">${spec.lead}</p>` : '') +
      secs.map((s, i) => `<div class="help-sec"><h4>${esc(s.title)}</h4><div data-sec="${i}">${s.html || ''}</div></div>`).join('') +
      (terms.length ? `<div class="help-terms"><h4>Terms on this card</h4><ul>${terms.map(t => `<li data-term="${esc(t.key)}"><b>${esc(t.label)}</b> — ${esc(t.def)} <a href="${esc(t.url)}" target="_blank" rel="noopener">More ↗</a></li>`).join('')}</ul></div>` : ''));
    secs.forEach((s, i) => { if (!s.render) return; const slot = box.querySelector(`[data-sec="${i}"]`);
      try { s.render(slot); } catch (err) { slot.innerHTML = '<span class="muted">Diagram unavailable.</span>'; } });
    armTerms(box); return box; };
  const helpButton = card => { const h = card.querySelector(':scope > h2'); if (!h || h.querySelector('.card-help')) return;
    const b = el('button', {class: 'card-help', type: 'button', 'aria-label': `Explain: ${helpTitle(h)}`, title: 'Explain this card'}, 'ⓘ');
    b.addEventListener('click', () => openHelp(card)); h.appendChild(b); };
  const help = (card, spec) => { if (!card) return; card._faHelp = spec || {}; helpButton(card); };
  const armHelp = root => { helpTargets(root || document).forEach(c => { if (c.dataset.help === 'none') return;
    if (c._faHelp || c.querySelector('.term[data-term]')) helpButton(c); }); };
  // flow: an arithmetic chain of labelled boxes joined by operators; the last box is the answer
  const flow = (steps, o = {}) => `<div class="flow" role="img" aria-label="${esc(o.label || steps.map(s => `${s.op ? s.op + ' ' : ''}${s.label} ${s.value}`).join(' '))}">` +
    steps.map((s, i) => `${s.op ? `<span class="op">${esc(s.op)}</span>` : ''}<span class="box${i === steps.length - 1 ? ' last' : ''}"><span class="k">${esc(s.label)}</span><span class="v">${esc(s.value)}</span></span>`).join('') + '</div>';
  // readGrid: a 3x3 mini heatmap explaining a sensitivity grid (value rises with the column, falls with the row)
  const readGrid = (o = {}) => { const names = ['lower', 'base', 'higher'];
    let h = `<div class="readgrid"><p class="readgrid-cap">Rows: ${o.rowLabel || 'first assumption'}, lower to higher. Columns: ${o.colLabel || 'second assumption'}, lower to higher.</p><table class="heat mini"><thead><tr><th class="l"></th>${names.map(n => `<th>${n}</th>`).join('')}</tr></thead><tbody>`;
    [0, 1, 2].forEach(i => { h += `<tr><td class="l">${names[i]}</td>` + [0, 1, 2].map(j => { const t = j - i;
      const bg = t > 0 ? `color-mix(in oklab, var(--s1) ${30 + 25 * t}%, var(--surface))` : t < 0 ? `color-mix(in oklab, var(--s8) ${30 - 25 * t}%, var(--surface))` : 'var(--surface)';
      return `<td class="${i === 1 && j === 1 ? 'base' : ''}" style="background:${bg};text-align:center">${t > 0 ? '▲' : t < 0 ? '▼' : i === 1 ? '=' : '≈'}</td>`; }).join('') + '</tr>'; });
    return h + `</tbody></table><ul class="readgrid-notes"><li>${o.highText || 'Blue cells are values above the price.'}</li><li>${o.lowText || 'Red cells are values below the price.'}</li><li>${o.baseText || 'The outlined cell is the base case.'}</li></ul></div>`; };
  // tour: FA.tour(steps) walks the reader through the page one step at a time.
  // steps = [{target: '#css-selector' or null, title, html}]; a missing target is skipped, a null one shows no highlight.
  const tour = steps => {
    const live = steps.filter(st => !st.target || document.querySelector(st.target)); if (!live.length) return;
    document.querySelectorAll('.tour-card').forEach(n => n.remove());
    let i = 0, lit = null; const card = el('div', {class: 'tour-card', role: 'dialog', 'aria-live': 'polite', 'aria-label': 'Page walkthrough'});
    document.body.appendChild(card);
    const close = () => { if (lit) lit.classList.remove('tour-on'); card.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = e => { if (e.key === 'Escape') close(); else if (e.key === 'ArrowRight' && i < live.length - 1) go(i + 1); else if (e.key === 'ArrowLeft' && i > 0) go(i - 1); };
    const go = n => { i = n; const st = live[i]; if (lit) lit.classList.remove('tour-on'); lit = st.target ? document.querySelector(st.target) : null;
      if (lit) { lit.classList.add('tour-on'); if (lit.tagName === 'DETAILS') lit.open = true; lit.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center'}); }
      card.innerHTML = `<button class="x" aria-label="Close walkthrough">×</button><div class="step">Step ${i + 1} of ${live.length}</div><h3>${esc(st.title)}</h3>${st.html}` +
        `<div class="nav"><button class="btn quiet" data-a="back"${i ? '' : ' disabled'}>Back</button><button class="btn" data-a="next">${i === live.length - 1 ? 'Done' : 'Next'}</button></div>`;
      card.querySelector('.x').onclick = close; card.querySelector('[data-a=back]').onclick = () => i && go(i - 1);
      card.querySelector('[data-a=next]').onclick = () => (i === live.length - 1 ? close() : go(i + 1)); card.querySelector('[data-a=next]').focus(); armTerms(card); };
    document.addEventListener('keydown', onKey); go(0); return card; };
  // intro: FA.intro(root, {lead, steps}) -- one plain sentence and a "How to read this page" button that starts the tour.
  const intro = (root, o) => { const has = o.steps && o.steps.length;
    root.innerHTML = `<div class="intro"><p>${o.lead}</p>${has ? `<button class="btn" type="button">${esc(o.label || 'How to read this page')}</button>` : ''}</div>`;
    if (has) root.querySelector('.btn').addEventListener('click', () => tour(o.steps)); armTerms(root); };
  const armAll = () => { armTerms(document); armHelp(document); };
  document.addEventListener('DOMContentLoaded', armAll); setTimeout(armAll, 0);
  // help targets: .card or section with a direct-child h2, outside modals and tour cards
  const helpTargets = root => { root = root || document; const sel = '.card, section';
    const list = [...(root.matches && root.matches(sel) ? [root] : []), ...root.querySelectorAll(sel)];
    return list.filter(n => n.querySelector(':scope > h2') && !n.closest('.modal, .tour-card')); };
  const helpTitle = h => [...h.childNodes].filter(n => !(n.classList && n.classList.contains('card-help'))).map(n => n.textContent).join('').trim();
  // #fa-audit: tests open the page with this hash; the result is written as JSON into the DOM for --dump-dom
  const audit = () => {
    const cards = helpTargets(document).map(c => { const h = c.querySelector(':scope > h2'); const btns = h.querySelectorAll('.card-help');
      const kind = c.dataset.help === 'none' ? 'exempt' : !btns.length ? 'none' : (c._faHelp ? 'authored' : 'fallback');
      let m = null;
      if (btns.length) { btns[0].click(); const box = document.querySelector('.overlay .modal');
        if (box) { m = {title: (box.querySelector('h3') || {}).textContent || '', lead: (box.querySelector('.help-lead') || {}).textContent || '',
          sections: [...box.querySelectorAll('.help-sec > h4')].map(n => n.textContent), terms: [...box.querySelectorAll('.help-terms li')].map(n => n.dataset.term),
          links: [...box.querySelectorAll('.help-terms a')].map(a => a.getAttribute('href')), text: box.textContent,
          authored: [...box.querySelectorAll('.help-lead, .help-sec')].map(n => n.textContent).join(' ')};
          box.querySelector('.x').click(); } }
      return {h2: helpTitle(h), hidden: !!c.closest('[hidden]'), help: kind, buttons: btns.length, modal: m}; });
    const s = document.createElement('script'); s.type = 'application/json'; s.id = 'fa-audit';
    s.textContent = JSON.stringify({help_links: document.querySelectorAll('a.help').length, cards}).replace(/</g, '\\u003c');
    document.body.appendChild(s); };
  if (location.hash === '#fa-audit') setTimeout(audit, 60);
  return { S, money, moneyS, moneyC, niceTicks, tour, intro, pct, num, cls, esc, el, bars, donut, table, lines, heatmap, bindTip, tip, isNum, term, armTerms, explain, modal, help, armHelp, flow, readGrid, glossary: G };
})();
"""


def render(title: str, data: dict, body: str, script: str, description: str | None = None) -> str:
    """One artifact-ready HTML fragment: <title>, tokens and CSS, the body markup, the data, the toolkit, the build script."""
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    glossary = json.dumps({k: list(v) for k, v in GLOSSARY.items()}, separators=(",", ":")).replace("</", "<\\/")
    # ``title`` and ``description`` are the only caller-supplied strings that land
    # in markup rather than in JSON, and callers pass live values into them -- a
    # symbol, a fund name. Escaping here rather than at each call site is the only
    # placement a new renderer cannot forget: an unescaped symbol of
    # ``X</title><h1>...</h1><script>...</script><title>y`` closed the title and put
    # both an arbitrary heading and an executable script at the top of the page.
    # ``quote=False`` is correct only because both land in TEXT below -- it keeps an
    # apostrophe in ``Moody's Baa`` readable. Anything that moves either into an
    # attribute (``<meta content=...>``, ``title=``, ``aria-label=``) needs
    # ``quote=True`` in the same edit, or this escape stops closing the hole.
    title = html_mod.escape(title, quote=False)
    desc = (
        f'<p class="sub" id="fa-desc">{html_mod.escape(description, quote=False)}</p>'
        if description
        else ""
    )
    return (
        f"<title>{title}</title>\n<style>{CSS}</style>\n"
        f"{desc}{body}\n"
        f"<script>window.DATA = {payload}; window.GLOSSARY = {glossary};</script>\n"
        f"<script>{JS}</script>\n"
        f"<script>{script}</script>\n"
    )


def write(path: str | Path, html: str) -> Path:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p
