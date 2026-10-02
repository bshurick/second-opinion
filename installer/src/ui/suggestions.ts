/** First things to ask Claude, chosen from the skills that were actually installed. */
export interface Suggestion {
  prompt: string;
  note?: string;
}

const BY_SKILL: [skill: string, needsKeys: boolean, suggestion: Suggestion][] = [
  ["connect", true, { prompt: "connect my brokerage", note: "SANDBOX is a safe read-only test broker" }],
  ["portfolio-snapshot", true, { prompt: "how is my portfolio?" }],
  ["valuation", false, { prompt: "what is AAPL worth?" }],
  ["market-analysis", false, { prompt: "how is the market today?" }],
  ["watchlist", false, { prompt: "watch NVDA and alert me if it drops 5%" }],
  ["retirement", true, { prompt: "am I on track to retire?" }],
  ["real-estate", false, { prompt: "should I rent or buy?" }],
  ["options", false, { prompt: "show me the AAPL options chain" }],
  ["financial-education", false, { prompt: "teach me about diversification" }],
  ["personal-finance", false, { prompt: "help me build a budget" }],
];

const CONNECT_ETRADE: Suggestion = {
  prompt: "Connect E*Trade",
  note: "opens the E*Trade login; paste the 5-character code back in the chat",
};

/**
 * `smoke` carries just enough of the smoke result to decide whether the direct E*Trade
 * connection still needs a browser login; the done screen and the plain driver share it
 * so both surfaces agree on when to prompt for it.
 */
export function suggestions(installed: Iterable<string>, hasKeys: boolean, smoke?: { etradeNeedsLogin: boolean }, limit = 2): Suggestion[] {
  const have = new Set(installed);
  const out: Suggestion[] = [];
  if (smoke?.etradeNeedsLogin) out.push(CONNECT_ETRADE);
  for (const [skill, needsKeys, s] of BY_SKILL) {
    if (!have.has(skill) || (needsKeys && !hasKeys)) continue;
    out.push(s);
    if (out.length === limit + (smoke?.etradeNeedsLogin ? 1 : 0)) break;
  }
  return out;
}
