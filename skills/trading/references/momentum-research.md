# Momentum and Reversal: Research Notes for Trade Timing

Peer-reviewed findings that bear directly on entry/exit-timing questions. Use
them as context for analysis — they describe historical statistical patterns,
not predictions. Read this file before quoting a figure, a sample period or a
source for a momentum, reversal or lead-lag pattern.

## The horizon map — effects reverse depending on lookback
- **Days–weeks: weak mean reversion, mostly illusory for single names.** Average
  weekly autocorrelation of an individual US stock is about −3.4% (R² of 0–4%) —
  last week's move says almost nothing about next week's [LoMacKinlay90].
  Measured short-term reversal is further inflated by bid-ask bounce, and a
  one-way transaction cost of just 0.40% erases roughly half of gross weekly
  contrarian profits [Lehmann88 via LoMacKinlay90].
- **3–12 months: continuation (momentum).** Mutual funds tilting toward recent
  winners earned ~2.6%/yr risk-adjusted excess return vs ~0.1% for contrarian
  funds (155 funds, 1975–84) [GrinblattTitmanWermers95], consistent with the
  Jegadeesh–Titman momentum effect. The edge came almost entirely from *buying
  recent winners* — systematic selling of losers was statistically
  insignificant — and was concentrated in large-cap winners. Figures are gross
  of costs; momentum is high-turnover and prone to sharp "momentum crashes."
- **3–5 years: long-horizon reversal is fragile.** The often-cited 91-pct-pt
  winner/loser gap drops to 57% when portfolios form in June instead of
  December, the median gap is only 14% (extreme right skew from penny-stock
  recoveries), and June-formation risk-adjusted returns are ~−2.5%/yr. Loser
  portfolios are dominated by low-price distressed stocks (median price $5.00)
  where a $0.125 microstructure error moves 5-yr returns by 25+ pct pts
  [BallKothariShanken95].

## Index patterns are not stock patterns
- The equal-weighted market index has weekly autocorrelation near +30% while
  the average individual stock sits at −3.4% [LoMacKinlay90]. The gap comes
  entirely from cross-stock effects — never infer single-name behavior from
  index trends, or vice versa.
- **Lead-lag: large caps lead small caps.** Correlation of last week's
  largest-quintile return with this week's smallest-quintile return: 27.6%;
  the reverse direction: 2.0% [LoMacKinlay90]. A small cap that "hasn't moved
  yet" after a large-cap peer move is a documented historical pattern — but the
  profits concentrate in exactly the stocks with the widest spreads and least
  liquidity.
- More than half of weekly contrarian profits come from this lead-lag
  cross-autocorrelation, NOT from individual stocks overreacting and snapping
  back [LoMacKinlay90].

## Implications for timing analysis
- Always state the horizon when discussing momentum or reversal — the sign of
  the effect flips with the lookback window.
- Strong 3–12-month relative strength is a documented continuation signal; a
  bad week alone is not a reversal signal.
- "Everyone is piling in" is not an independent signal: fund herding is modest
  (~2.5 extra same-side funds per 100 trading a stock) and adds no explanatory
  power once the momentum tilt is controlled for [GrinblattTitmanWermers95].
- Round-trip costs and turnover dominate short-horizon effects at retail
  scale; surface them whenever a short-horizon strategy comes up.
- All figures come from specific historical samples (1962–87 weekly data,
  1975–84 funds); regimes change, and none of this guarantees future behavior.

Sources: Grinblatt, Titman & Wermers (AER 1995); Lo & MacKinlay (RFS 1990);
Ball, Kothari & Shanken (JFE 1995); Jegadeesh & Titman (JF 1993).
