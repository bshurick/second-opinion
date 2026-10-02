#!/usr/bin/env python3
"""Rebuilds docs/samples/valuation.json for the README screenshot.

The financials below are invented, COST-shaped figures for the sample page; they are not reported
results. They go through the valuation skill's real intrinsic, DCF, comps and DDM functions, which
only do arithmetic, so the fixture has exactly the keys and flags the scripts produce. No network.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from scripts_util import load_script, PLUGIN_ROOT

B = 1e9
cols = ["fiscal_year","revenue","net_income","eps_diluted","equity","operating_income","operating_cash_flow","capex","free_cash_flow","depreciation_amortization","current_assets","current_liabilities","total_assets","total_liabilities","long_term_debt","cash","dividends_paid","diluted_shares"]
raw = [
 (2021,196.0,5.00,11.27,17.6,6.70, 8.9,3.6,5.3,1.78,29.5,29.4,59.3,41.2,6.7,11.3,5.7,443.9e6),
 (2022,227.0,5.84,13.14,20.6,7.80, 7.4,3.9,3.5,1.90,32.7,31.9,64.2,43.5,6.5,10.2,1.5,444.8e6),
 (2023,242.3,6.29,14.16,25.1,8.10,11.1,4.3,6.8,2.08,35.9,35.5,69.0,43.9,6.0,13.7,1.7,444.5e6),
 (2024,254.5,7.37,16.56,23.6,9.30,11.3,4.7,6.6,2.24,34.2,35.5,69.8,46.2,5.8, 9.9,8.6,444.1e6),
 (2025,271.2,8.02,18.03,28.4,10.1,13.3,5.2,8.1,2.43,38.1,38.9,76.6,48.2,5.7,14.1,2.3,443.5e6),
]
annual = []
for r in raw:
    row = {}
    for c, v in zip(cols, r):
        row[c] = v if c in ("fiscal_year","eps_diluted","diluted_shares") else v * B
    annual.append(row)

price = 915.0
intr = load_script("valuation/scripts/intrinsic.py").run_intrinsic({"annual": annual, "price": price, "aaa_yield": 0.054, "treasury_10y": 0.043})
dcfm = load_script("valuation/scripts/dcf.py")
shares = 443.5e6
net_debt = (5.7 - 14.1) * B
dcf = dcfm.run_dcf({"fcf0": 8.1*B, "growth_rate": 0.10, "stage1_growth": [0.16,0.15,0.13,0.12,0.10,0.09,0.08,0.07,0.06,0.05], "years": 10, "terminal_growth": 0.03, "wacc": 0.075, "net_debt": net_debt, "shares_outstanding": shares, "current_share_price": price})
oe = dcfm.run_dcf(intr["buffett"]["dcf_input"])
mid = dcfm.run_dcf(intr["normalized"]["dcf_input_mid_cycle"])
comps = load_script("valuation/scripts/comps.py").run_comps({
  "target": {"metric_values": {"pe": 50.7, "ev_ebitda": 31.7, "ps": 1.50, "pb": 14.3, "fcf_yield": 0.020}},
  "peers": [
    {"name": "WMT", "pe": 36.0, "ev_ebitda": 19.5, "ps": 0.95, "pb": 8.1, "fcf_yield": 0.022},
    {"name": "TGT", "pe": 13.5, "ev_ebitda": 8.2, "ps": 0.55, "pb": 4.1, "fcf_yield": 0.045},
    {"name": "BJ",  "pe": 24.0, "ev_ebitda": 14.6, "ps": 0.62, "pb": 6.9, "fcf_yield": 0.030},
    {"name": "DG",  "pe": 18.5, "ev_ebitda": 11.2, "ps": 0.62, "pb": 2.9, "fcf_yield": 0.050},
    {"name": "KR",  "pe": 17.0, "ev_ebitda": 8.9, "ps": 0.31, "pb": 3.9, "fcf_yield": 0.055}],
  "target_financials": {"eps": 18.03, "ebitda_per_share": 28.25, "sales_per_share": 611.50, "book_value_per_share": 64.04, "fcf_per_share": 18.26, "net_debt_per_share": -18.94}})
ddm = load_script("valuation/scripts/ddm.py").run_ddm({"model": "two_stage", "dividend0": 5.20, "required_return": 0.08, "terminal_growth": 0.05, "growth_rate": 0.12, "years": 10})
data = {"symbol": "COST", "price": price, "dcf": dcf, "dcf_owner_earnings": oe, "dcf_mid_cycle": mid, "intrinsic": intr, "comps": comps, "ddm": ddm}
out = PLUGIN_ROOT / "docs/samples/valuation.json"
out.write_text(json.dumps(data, indent=2) + "\n")
print(f"wrote {out}")
