#!/usr/bin/env python3
"""Rebuilds docs/samples/rebalancing.json for the README screenshot.

The sample household's holdings, cash, lots and targets go through the rebalancing skill's real
planning math (rebalance.run_rebalance) with a 5,000 contribution. The keys plan.py adds around that
result (sources, accounts, holdings by account, lot sources) and the suggested bands are filled in
by hand because they come from live data. No network and no user targets.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "rebalancing" / "scripts"))
import rebalance  # noqa: E402
BRK, ROTH, K401 = "Sample Brokerage", "Sample Roth IRA", "Sample 401(k)"
H = [  # account, symbol, units, price, cost basis
 (BRK,"VTI",220,312.0,52800),(BRK,"AAPL",120,232.0,19200),(BRK,"MSFT",55,505.0,18150),(BRK,"COST",22,915.0,15400),(BRK,"SCHD",400,28.5,10400),
 (ROTH,"VXUS",600,68.0,34200),(ROTH,"JNJ",100,165.0,15800),(ROTH,"VNQ",150,92.0,13050),
 (K401,"VTI",300,312.0,66000),(K401,"BND",950,74.0,72200)]
positions = [{"symbol":s,"units":u,"price":p,"account":a} for a,s,u,p,_ in sorted(H, key=lambda h:(h[1],h[0]))]
lots = {}
for a,s,u,p,c in H:
    if (a,s) == (BRK,"VTI"):  # two long-term lots, 120 @ 225 + 100 @ 258 = 52,800
        lots.setdefault(s,[]).extend([{"units":120,"cost_per_unit":225.0,"term":"long","account":a},{"units":100,"cost_per_unit":258.0,"term":"long","account":a}])
    else:
        lots.setdefault(s,[]).append({"units":u,"cost_per_unit":c/u,"term":"long","account":a})
classes = {s:"US equities" for s in ["VTI","AAPL","MSFT","COST","SCHD","JNJ","VNQ"]}
classes.update({"VXUS":"international","BND":"bonds"})


def plan(contribution: float = 5000.0, only_if_breached: bool = False) -> dict:
    """The rebalancing math for the sample household (also used by gen_portfolio_brief.py)."""
    return rebalance.run_rebalance(_params(contribution, only_if_breached))


def _params(contribution: float, only_if_breached: bool) -> dict:
    return {"positions":positions,"cash":21715.0,"targets":{"US equities":0.55,"international":0.15,"bonds":0.25,"CASH":0.05},
  "classes":classes,"contribution":contribution,"allow_sells":True,"whole_shares":True,"min_trade":0.0,
  "only_if_breached":only_if_breached,"lots":lots,"rates":{"short_term":0.24,"long_term":0.15},
  "accounts":{BRK:{"taxable":True},K401:{"taxable":False},ROTH:{"taxable":False}}}


def main() -> None:
    res = plan()
    out = {"sources":{"holdings":"snaptrade","prices":"yahoo","targets":"targets.json","lots":"ledger"},
     "accounts":[BRK,ROTH,K401],
     "holdings_by_account":{K401:["BND","VTI"],BRK:["AAPL","COST","MSFT","SCHD","VTI"],ROTH:["JNJ","VNQ","VXUS"]},
     "lot_sources":{s:"ledger" for s in sorted({h[1] for h in H})}, **res,
     "suggested_bands":[{"key":"US equities","vol_annual":0.1624,"absolute":0.04,"relative":0.24},
       {"key":"bonds","vol_annual":0.0581,"absolute":0.01,"relative":0.1},
       {"key":"international","vol_annual":0.1482,"absolute":0.04,"relative":0.22}]}
    dest = ROOT / "docs" / "samples" / "rebalancing.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
