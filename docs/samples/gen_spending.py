#!/usr/bin/env python3
"""Rebuilds docs/samples/spending-month.json and spending-changes.json for the README screenshot.

The ledger below is invented (made-up merchants on the sample household's accounts). It goes through
the spending skill's real report code, so every total, change and recurring series is consistent.
No network and no user ledger.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/spending/scripts"))
import spendreport  # noqa: E402

ACCOUNTS = {
    "sample-visa": {"id": "sample-visa", "name": "Sample Visa", "kind": "card"},
    "sample-amex": {"id": "sample-amex", "name": "Sample Amex", "kind": "card"},
    "sample-checking": {"id": "sample-checking", "name": "Sample Checking", "kind": "checking"},
}
V, A, CK = "sample-visa", "sample-amex", "sample-checking"
ROWS = []


def add(d, merchant, amount, category, acct, desc=None, detail=None, items=None, transfer=False):
    row = {
        "id": f"tx-{len(ROWS) + 1:04d}", "date": d, "merchant": merchant,
        "description": desc or merchant.upper(), "amount": round(-amount, 2), "category": category,
        "category_source": "rule", "detail": detail, "account_id": acct, "transfer": transfer,
    }
    if items:
        row["items"] = [{"name": n, "amount": round(-a, 2), "category": c, "detail": dt} for n, a, c, dt in items]
    ROWS.append(row)


# ---- fixed monthly items, Mar..Aug 2026 -------------------------------------------------
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
for i, m in enumerate(MONTHS):
    add(f"{m}-01", "Sample Employer Payroll", -4900.00, "Income", CK, "SAMPLE EMPLOYER PAYROLL DIRECT DEP")
    add(f"{m}-15", "Sample Employer Payroll", -4900.00, "Income", CK, "SAMPLE EMPLOYER PAYROLL DIRECT DEP")
    add(f"{m}-01", "Sample Mortgage", 3200.00, "Housing", CK, "SAMPLE MORTGAGE AUTOPAY", "Housing/Mortgage")
    for d, a in [[(2, 40.0), (13, 25.0), (24, 35.0)], [(4, 50.0), (19, 45.0)], [(1, 30.0), (12, 40.0), (26, 25.0)], [(3, 60.0), (21, 35.0)], [(6, 25.0), (15, 50.0), (27, 30.0)], [(2, 40.0), (13, 25.0), (24, 35.0)]][i]:
        add(f"{m}-{d:02d}", "City Transit", a, "Transport", V, "CITY TRANSIT FARE TOP-UP", "Transport/Transit")
    add(f"{m}-03", "Sample Gym", 49.00, "Health", A, "SAMPLE GYM MEMBERSHIP", "Health/Fitness")
    add(f"{m}-05", "Sample Insurance", 95.00, "Health", CK, "SAMPLE INSURANCE PREMIUM", "Health/Dental and vision")
    streaming = 15.99 if i < 3 else 17.99  # price went up in June
    add(f"{m}-08", "Sample Streaming", streaming, "Subscriptions", V, "SAMPLE STREAMING MONTHLY", "Subscriptions/Video")
    for d, a in [[(9, 4.99), (22, 59.99)], [(14, 34.99), (27, 12.99)], [(6, 49.99), (19, 9.99)], [(11, 24.99), (25, 44.99)], [(8, 64.99)], [(14, 29.99), (27, 36.00)]][i]:
        add(f"{m}-{d:02d}", "Sample App Store", a, "Subscriptions", A, "SAMPLE APP STORE PURCHASE", "Subscriptions/Apps")
    if m <= "2026-07":  # cancelled after July: due in August, not charged
        add(f"{m}-21", "Sample Magazine", 8.99, "Subscriptions", V, "SAMPLE MAGAZINE MONTHLY", "Subscriptions/News")
    if m >= "2026-06":  # third charge lands in August: newly recurring
        add(f"{m}-24", "Sample Cloud", 9.99, "Subscriptions", V, "SAMPLE CLOUD STORAGE", "Subscriptions/Storage")
    util = [251.30, 236.85, 224.10, 231.65, 246.20, 240.00][i]
    add(f"{m}-12", "Sample Utilities", util, "Utilities", CK, "SAMPLE UTILITIES ELEC WATER", "Utilities/Electric and water")

# ---- prior months, variable spend (Mar..Jul) ---------------------------------------------
PRIOR = {
    "2026-03": dict(groc=[112.4, 98.2, 121.7, 104.9, 47.3, 38.6, 52.1, 41.8, 44.0], dining=[(4, "Bistro 42", 71.2), (11, "Noodle House", 38.4), (19, "Coffee Cart", 6.25), (26, "Taco Window", 24.8), (27, "Coffee Cart", 5.75)], shop=[(6, "Online Megastore", 212.4), (13, "Hardware Depot", 96.3), (22, "Sample Outfitters", 184.0), (28, "Online Megastore", 118.6)], fuel=[51.2, 47.9, 55.4], pharm=18.4),
    "2026-04": dict(groc=[118.9, 102.3, 96.8, 115.2, 44.7, 49.1, 39.9, 46.2, 51.6], dining=[(3, "Bistro 42", 84.6), (10, "Coffee Cart", 6.25), (17, "Noodle House", 41.2), (24, "Taco Window", 22.6), (29, "Bistro 42", 66.0)], shop=[(4, "Online Megastore", 164.2), (15, "Sample Outfitters", 238.5), (23, "Online Megastore", 142.8), (27, "Hardware Depot", 71.4)], fuel=[49.6, 53.1, 50.8], pharm=24.1),
    "2026-05": dict(groc=[109.5, 121.4, 99.7, 108.3, 42.6, 47.8, 51.3, 38.4, 45.9], dining=[(2, "Bistro 42", 76.4), (9, "Coffee Cart", 5.75), (16, "Noodle House", 39.8), (23, "Taco Window", 26.4), (30, "Bistro 42", 81.2), (31, "Coffee Cart", 6.25)], shop=[(3, "Online Megastore", 248.9), (12, "Sample Outfitters", 212.0), (19, "Online Megastore", 176.3), (26, "Hardware Depot", 164.8)], fuel=[54.2, 48.3, 52.6], pharm=21.7),
    "2026-06": dict(groc=[115.8, 104.2, 112.6, 97.4, 48.2, 43.5, 50.7, 44.1, 39.8], dining=[(6, "Bistro 42", 69.8), (13, "Coffee Cart", 6.25), (20, "Noodle House", 44.6), (27, "Taco Window", 23.9), (28, "Bistro 42", 88.4)], shop=[(7, "Online Megastore", 286.4), (14, "Hardware Depot", 118.2), (21, "Sample Outfitters", 196.0), (28, "Online Megastore", 204.7)], fuel=[52.8, 50.1, 47.6], pharm=19.9),
    "2026-07": dict(groc=[121.3, 108.7, 101.9, 114.6, 46.8, 51.2, 42.3, 48.9, 43.6], dining=[(4, "Bistro 42", 74.2), (11, "Coffee Cart", 5.75), (18, "Noodle House", 42.1), (25, "Taco Window", 25.3), (31, "Bistro 42", 79.6)], shop=[(5, "Online Megastore", 231.8), (12, "Sample Outfitters", 224.5), (19, "Online Megastore", 189.4), (26, "Hardware Depot", 142.6)], fuel=[50.4, 55.7, 49.2], pharm=23.5),
}
for m, p in PRIOR.items():
    p["groc"] = p["groc"] + [96.0]
    for d, c in [(5, 5.75), (14, 6.25), (21, 9.85), (28, 6.25)]:
        add(f"{m}-{d:02d}", "Coffee Cart", c, "Dining", V, None, "Dining/Coffee")
    days = [2, 6, 9, 13, 16, 20, 23, 27, 29, 30]
    for k, (d, a) in enumerate(zip(days, p["groc"])):
        merchant = "Neighborhood Grocer" if a > 80 else "Corner Market"
        add(f"{m}-{d:02d}", merchant, a, "Groceries", A if merchant == "Neighborhood Grocer" else V, None, f"Groceries/{merchant}")
    for d, merchant, a in p["dining"]:
        if (merchant == "Noodle House" and m in ("2026-04", "2026-06")) or (merchant == "Taco Window" and m in ("2026-04", "2026-06")):
            continue
        add(f"{m}-{d:02d}", merchant, a, "Dining", V, None, "Dining/Restaurants" if merchant != "Coffee Cart" else "Dining/Coffee")
    for d, merchant, a in p["shop"]:
        add(f"{m}-{d:02d}", merchant, a, "Shopping", A if merchant == "Online Megastore" else V)
    for d, a in zip([7, 17, 28], p["fuel"]):
        add(f"{m}-{d:02d}", "Corner Fuel", a, "Transport", V, None, "Transport/Fuel")
    if m in ("2026-03", "2026-06"):
        add(f"{m}-15", "Corner Pharmacy", p["pharm"], "Health", V, None, "Health/Pharmacy")
    else:
        add(f"{m}-15", "Sample Clinic", 25.0 + 10 * len(m[-1]), "Health", V, "SAMPLE CLINIC COPAY", "Health/Doctor")
    add(f"{m}-25", "Sample Visa", 1400.00, "Transfer", CK, "SAMPLE VISA PAYMENT", transfer=True)
    add(f"{m}-25", "Sample Visa", -1400.00, "Transfer", V, "PAYMENT THANK YOU", transfer=True)
    add(f"{m}-26", "Sample Amex", 1250.00, "Transfer", CK, "SAMPLE AMEX PAYMENT", transfer=True)
    add(f"{m}-26", "Sample Amex", -1250.00, "Transfer", A, "PAYMENT RECEIVED", transfer=True)

# ---- August 2026 ---------------------------------------------------------------------------
M = "2026-08"
for d, merchant, a in [(2, "Neighborhood Grocer", 118.42), (5, "Corner Market", 46.18), (9, "Neighborhood Grocer", 104.77),
                       (12, "Corner Market", 38.95), (16, "Neighborhood Grocer", 126.30), (19, "Corner Market", 52.64),
                       (23, "Neighborhood Grocer", 111.08), (26, "Corner Market", 44.21), (29, "Neighborhood Grocer", 97.15),
                       (31, "Corner Market", 42.30)]:
    add(f"{M}-{d:02d}", merchant, a, "Groceries", A if merchant == "Neighborhood Grocer" else V, None, f"Groceries/{merchant}")
for d, merchant, a in [(1, "Coffee Cart", 5.75), (4, "Bistro 42", 92.40), (6, "Coffee Cart", 6.25), (8, "Noodle House", 46.80),
                       (11, "Coffee Cart", 5.75), (14, "Bistro 42", 78.50), (15, "Taco Window", 28.60), (18, "Coffee Cart", 6.25),
                       (21, "Bistro 42", 64.20), (22, "Sunday Brunch Co", 58.40), (25, "Coffee Cart", 5.75),
                       (30, "Coffee Cart", 6.25)]:
    add(f"{M}-{d:02d}", merchant, a, "Dining", V, None, "Dining/Coffee" if merchant == "Coffee Cart" else "Dining/Restaurants")
add(f"{M}-07", "Online Megastore", 186.43, "Shopping", A, "ONLINE MEGASTORE ORDER 114-0001", "Shopping/Online",
    items=[("Desk lamp", 42.99, "Shopping", "Shopping/Home"), ("Printer paper, 2 reams", 18.49, "Shopping", "Shopping/Office"),
           ("Kids' rain boots", 34.95, "Shopping", "Shopping/Clothing"), ("Vitamin D, 180 ct", 13.60, "Health", "Health/Pharmacy"),
           ("Laundry detergent", 24.99, "Groceries", "Groceries/Household"), ("Phone charger", 19.99, "Shopping", "Shopping/Electronics")])
add(f"{M}-17", "Online Megastore", 64.97, "Shopping", A, "ONLINE MEGASTORE ORDER 114-0002", "Shopping/Online",
    items=[("Storage bins, set of 3", 29.98, "Shopping", "Shopping/Home"), ("Paperback novel", 14.99, "Shopping", "Shopping/Books"),
           ("Dish soap, 3 pack", 11.49, "Groceries", "Groceries/Household")])
add(f"{M}-20", "Online Megastore", -29.99, "Shopping", A, "ONLINE MEGASTORE RETURN", "Shopping/Online")
add(f"{M}-10", "Hardware Depot", 88.20, "Shopping", V)
add(f"{M}-24", "Sample Outfitters", 142.00, "Shopping", V)
add(f"{M}-27", "Garden Supply", 76.40, "Shopping", V, "GARDEN SUPPLY CO")
add(f"{M}-28", "Online Megastore", 42.18, "Shopping", A, "ONLINE MEGASTORE ORDER 114-0003", "Shopping/Online")
for d, a in [(6, 52.30), (16, 48.75), (27, 58.95)]:
    add(f"{M}-{d:02d}", "Corner Fuel", a, "Transport", V, None, "Transport/Fuel")
add(f"{M}-15", "Corner Pharmacy", 22.40, "Health", V, None, "Health/Pharmacy")
add(f"{M}-21", "Harbor Inn", 124.00, "Travel", A, "HARBOR INN ONE NIGHT", "Travel/Lodging")
add(f"{M}-21", "Sample Rail", 36.00, "Travel", V, "SAMPLE RAIL ROUND TRIP", "Travel/Rail")
add(f"{M}-25", "Sample Visa", 1500.00, "Transfer", CK, "SAMPLE VISA PAYMENT", transfer=True)
add(f"{M}-25", "Sample Visa", -1500.00, "Transfer", V, "PAYMENT THANK YOU", transfer=True)
add(f"{M}-26", "Sample Amex", 1300.00, "Transfer", CK, "SAMPLE AMEX PAYMENT", transfer=True)
add(f"{M}-26", "Sample Amex", -1300.00, "Transfer", A, "PAYMENT RECEIVED", transfer=True)

base = {"as_of": "2026-09-15", "accounts": ACCOUNTS, "transactions": ROWS, "month": M, "items": True}
extra = {"accounts": ACCOUNTS, "spending_path": "/home/sample/second-opinion/spending.json"}
month = {**spendreport.run_spendreport({**base, "report": "month"}), **extra}
changes = {**spendreport.run_spendreport({**base, "report": "changes"}), **extra}
out = ROOT / "docs/samples"
(out / "spending-month.json").write_text(json.dumps(month, indent=2) + "\n")
(out / "spending-changes.json").write_text(json.dumps(changes, indent=2) + "\n")
print(f"wrote {out}/spending-month.json and spending-changes.json")
