from __future__ import annotations

from datetime import date

from second_opinion.headlines import debt as DB
from second_opinion.headlines import journal as J
from second_opinion.headlines import ledger as L
from second_opinion.headlines import spending as SP

CTX = {"today": date(2026, 9, 14)}


def test_journal_price_through_stop_is_alert_and_review_flags_are_notices() -> None:
    review = {"entries": [{"id": "j-1", "symbol": "PEP", "side": "long", "exit": "open", "live_price": 64.0, "live_rr": -1.25},
                          {"id": "j-2", "symbol": "KO", "side": "short", "exit": "open", "live_price": 31.0, "live_rr": -0.8},
                          {"id": "j-3", "symbol": "AAPL", "side": "long", "exit": "open", "live_price": None},
                          {"id": "j-4", "symbol": "XOM", "side": "long", "exit": "stopped", "live_price": None}],
              "flags": [{"code": "STALE_OPEN", "message": "j-3 AAPL open 200 days past horizon"}, {"code": "LOW_PLANNED_RR", "message": "x"}]}
    opened = {"entries": [{"id": "j-1", "symbol": "PEP", "side": "long", "stop": 65.0, "status": "open", "entry_price": 70.0, "target": 55.0},
                          {"id": "j-2", "symbol": "KO", "side": "short", "stop": 30.0, "status": "open", "entry_price": 28.0, "target": 20.0},
                          {"id": "j-3", "symbol": "AAPL", "side": "long", "stop": 100.0, "status": "open"}]}
    hs = J.extract({"review": review, "open": opened}, CTX)
    assert [h["key"] for h in hs] == ["trade-journal:STOP_HIT:PEP:j-1", "trade-journal:STOP_HIT:KO:j-2", "trade-journal:STALE_OPEN:-:"]
    assert hs[0]["severity"] == "alert" and hs[0]["title"] == "PEP at 64.00 is through its 65.00 stop (journal j-1)"
    assert hs[1]["title"] == "KO at 31.00 is through its 30.00 stop (journal j-2)"
    assert hs[2]["severity"] == "notice" and hs[2]["title"] == "j-3 AAPL open 200 days past horizon"
    assert hs[0]["ask"] == "Am I following my plan on PEP?" and hs[2]["ask"] == "Which journal entries are past their horizon?"
    assert hs[0]["url"] == "https://finance.yahoo.com/quote/PEP"
    assert hs[0]["answer"] == "Entry 70.00, stop 65.00, target 55.00, live R:R -1.25"
    assert hs[0]["why"] == "Your journal's stop for this trade has been crossed; the plan called for an exit or a re-think."
    assert hs[2]["url"] == "" and hs[2]["answer"] == "j-3 AAPL open 200 days past horizon"
    assert hs[2]["why"] == "An open trade past its planned horizon."


def test_journal_without_open_list_still_reports_flags() -> None:
    hs = J.extract({"review": {"entries": [], "flags": [{"code": "OVERSTAYED", "message": "m"}]}}, CTX)
    assert len(hs) == 1 and hs[0]["code"] == "OVERSTAYED"
    assert hs[0]["answer"] == "m" and hs[0]["why"] == "An open trade past its planned horizon."


def test_journal_stop_drifted_headlines_keyed_by_entry() -> None:
    flags = [{"code": "STOP_DRIFTED", "message": "j-1 (AAPL): the stop was revised from 90.00 to 80.00"},
             {"code": "STOP_DRIFTED", "message": "j-2 (MSFT): the stop was revised from 300.00 to 280.00"}]
    hs = J.extract({"review": {"entries": [], "flags": flags}}, CTX)
    assert len(hs) == 2
    assert [h["key"] for h in hs] == ["trade-journal:STOP_DRIFTED:AAPL:j-1", "trade-journal:STOP_DRIFTED:MSFT:j-2"]
    assert hs[0]["severity"] == "notice" and hs[0]["title"] == "j-1 (AAPL): the stop was revised from 90.00 to 80.00"
    assert hs[1]["severity"] == "notice" and hs[1]["title"] == "j-2 (MSFT): the stop was revised from 300.00 to 280.00"
    assert hs[0]["ask"] == "Which stops have I moved since entry?" and hs[1]["ask"] == "Which stops have I moved since entry?"
    assert hs[0]["answer"] == flags[0]["message"] and hs[1]["answer"] == flags[1]["message"]
    assert hs[0]["why"] == "The stop was moved after entry, which weakens the original plan."


def test_debt_past_due_due_soon_utilization_and_stale() -> None:
    res = {"main": {"accounts": [
        {"id": "amex", "name": "Amex Gold", "due_date": "2026-09-12", "days_to_due": -2, "utilization": 0.1, "statement_age_days": 10, "flags": ["PAST_DUE"],
         "minimum_payment": 45.0, "balance": 1200.0, "apr": 0.2499, "monthly_interest_run_rate": 24.99, "credit_limit": 12000.0, "period_end": "2026-08-25"},
        {"id": "chase", "name": "Chase Sapphire", "due_date": "2026-09-19", "days_to_due": 5, "utilization": 0.42, "statement_age_days": 12, "flags": ["HIGH_UTILIZATION"],
         "minimum_payment": 90.0, "balance": 4200.0, "apr": 0.2199, "monthly_interest_run_rate": 76.99, "credit_limit": 10000.0, "period_end": "2026-08-30"},
        {"id": "mortgage", "name": "Sample Mortgage", "due_date": "2026-10-01", "days_to_due": 17, "utilization": None, "statement_age_days": 70, "flags": ["STALE"],
         "minimum_payment": 2900.0, "balance": 420000.0, "apr": 0.0475, "monthly_interest_run_rate": 1662.5, "period_end": "2026-07-05"},
        {"id": "auto", "name": "Auto loan", "due_date": "2026-09-30", "days_to_due": 16, "utilization": None, "statement_age_days": 5, "flags": []}]}}
    hs = DB.extract(res, CTX)
    assert [h["key"] for h in hs] == ["debt-tracker:PAST_DUE:-:amex:2026-09-12", "debt-tracker:DUE_SOON:-:chase:2026-09-19",
                                       "debt-tracker:HIGH_UTILIZATION:-:chase", "debt-tracker:STALE:-:mortgage"]
    assert hs[0]["severity"] == "alert" and hs[0]["title"] == "Amex Gold payment was due 2026-09-12 (2 days ago)"
    assert hs[1]["severity"] == "alert" and hs[1]["title"] == "Chase Sapphire payment is due 2026-09-19 (5 days)"
    assert hs[2]["severity"] == "notice" and hs[2]["title"] == "Chase Sapphire utilization is 42.0%"
    assert hs[3]["title"] == "Sample Mortgage statement is 70 days old" and hs[3]["ask"] == "What do I owe across all my accounts?"
    assert hs[0]["ask"] == "How much interest am I paying on Amex Gold?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "Minimum $45.00 on $1,200.00 at 25.0% APR ($24.99 interest a month)"
    assert hs[0]["why"] == "A payment past its due date accrues interest and can be reported late."
    assert hs[1]["answer"] == "Minimum $90.00 on $4,200.00 at 22.0% APR ($76.99 interest a month)"
    assert hs[1]["why"] == "A statement payment falls due within a week."
    assert hs[2]["answer"] == "$4,200.00 of a $10,000.00 limit"
    assert hs[2]["why"] == "Utilization above 30% weighs on credit scores."
    assert hs[3]["answer"] == "Last statement 2026-07-05"
    assert hs[3]["why"] == "The debt picture is only as fresh as the last statement recorded."


def test_spending_category_moves_and_new_recurring() -> None:
    changes = {"month": "2026-09",
               "categories": [{"category": "Dining", "amount": 940.0, "avg_prior": 610.0, "delta": 330.0, "delta_pct": 0.541, "new": False,
                               "explained_by": [{"date": "2026-09-10", "merchant": "Chez Panisse", "amount": 210.0, "description": "dinner"},
                                                 {"date": "2026-09-03", "merchant": "Tartine", "amount": 85.0, "description": "brunch"},
                                                 {"date": "2026-09-01", "merchant": "Blue Bottle", "amount": 12.0, "description": "coffee"}]},
                              {"category": "Groceries", "amount": 500.0, "avg_prior": 450.0, "delta": 50.0, "delta_pct": 0.111, "new": False},
                              {"category": "Travel", "amount": 0.0, "avg_prior": 800.0, "delta": -800.0, "delta_pct": -1.0, "new": False, "explained_by": []},
                              {"category": "Pets", "amount": 260.0, "avg_prior": 200.0, "delta": 60.0, "delta_pct": 0.30, "new": False}],
               "new_recurring": [{"merchant": "Peloton", "typical_amount": 44.0, "cadence": "monthly", "first_date": "2026-07-14",
                                   "category": "Subscriptions", "annual_cost": 528.0, "next_expected": "2026-10-14"},
                                  {"merchant": "McDonald's", "typical_amount": 12.0, "cadence": "weekly", "first_date": "2026-07-20",
                                   "category": "Dining", "annual_cost": 624.0, "next_expected": "2026-09-21"}]}
    hs = SP.extract({"changes": changes, "recurring": {"series": []}}, CTX)
    assert [h["key"] for h in hs] == ["spending:CATEGORY_MOVE:-:2026-09:Dining", "spending:CATEGORY_MOVE:-:2026-09:Travel", "spending:NEW_RECURRING:-:Peloton:2026-07-14"]
    assert hs[0]["severity"] == "notice" and hs[0]["title"] == "Dining is up 54.1% this month ($940.00 vs $610.00 average)"
    assert hs[1]["title"] == "Travel is down 100.0% this month ($0.00 vs $800.00 average)"
    assert hs[2]["title"] == "New recurring charge: Peloton $44.00 monthly"
    assert hs[0]["ask"] == "What drove Dining spending in 2026-09?" and hs[2]["ask"] == "What are all my recurring charges?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "Largest: Chez Panisse $210.00 on 2026-09-10; Tartine $85.00"
    assert hs[0]["why"] == "A category that moved 25% and $200 against its three-month average."
    assert hs[1]["answer"] == ""
    assert hs[2]["answer"] == "$528.00 a year; next expected 2026-10-14"
    assert hs[2]["why"] == "A charge that now repeats on a schedule and did not a month ago."


def test_spending_new_recurring_skips_everyday_categories() -> None:
    changes = {"month": "2026-09", "categories": [],
               "new_recurring": [{"merchant": "McDonald's", "typical_amount": 12.0, "cadence": "weekly", "first_date": "2026-07-20",
                                   "category": "Dining", "annual_cost": 624.0, "next_expected": "2026-09-21"},
                                  {"merchant": "Peloton", "typical_amount": 44.0, "cadence": "monthly", "first_date": "2026-07-14",
                                   "category": "Subscriptions", "annual_cost": 528.0, "next_expected": "2026-10-14"}]}
    hs = SP.extract({"changes": changes}, CTX)
    assert len(hs) == 1 and "Peloton" in hs[0]["title"] and "McDonald's" not in hs[0]["title"]


def test_spending_category_move_answer_skips_incomplete_charges_and_omits_missing_date() -> None:
    changes = {"month": "2026-09",
               "categories": [{"category": "Dining", "amount": 940.0, "avg_prior": 610.0, "delta": 330.0, "delta_pct": 0.541, "new": False,
                               "explained_by": [{"date": None, "merchant": "Chez Panisse", "amount": 210.0, "description": "dinner"},
                                                 {"date": "2026-09-03", "merchant": None, "amount": 85.0, "description": "no merchant"},
                                                 {"date": "2026-09-01", "merchant": "Blue Bottle", "amount": None, "description": "no amount"}]}]}
    hs = SP.extract({"changes": changes}, CTX)
    assert hs[0]["answer"] == "Largest: Chez Panisse $210.00"


def test_ledger_stale_import_is_a_notice() -> None:
    res = {"main": {"count": 4213, "imports": [{"source": "x.csv", "at": "2026-07-01T10:00:00+00:00", "added": 88}],
                    "date_range": {"start": "2024-01-01", "end": "2026-06-28"}}}
    hs = L.extract(res, CTX)
    assert len(hs) == 1 and hs[0]["key"] == "statement-import:STALE_LEDGER:-:2026-07-01" and hs[0]["severity"] == "notice"
    assert hs[0]["title"] == "Ledger last imported 2026-07-01 (75 days ago)" and hs[0]["ask"] == "How recent is my imported activity?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "4213 transactions through 2026-06-28; last import x.csv added 88"
    assert hs[0]["why"] == "Tax, trade-review and journal analysis read this ledger; a stale ledger makes them stale."
    assert L.extract({"main": {"imports": [{"at": "2026-09-01T10:00:00+00:00"}], "date_range": None}}, CTX) == []
    assert L.extract({"main": {"imports": [], "date_range": {"start": "2024-01-01", "end": "2026-06-28"}}}, CTX)[0]["key"] == "statement-import:STALE_LEDGER:-:2026-06-28"


def test_ledger_answer_omits_last_import_clause_when_source_or_added_is_bad() -> None:
    res = {"main": {"count": 4213, "imports": [{"source": None, "at": "2026-07-01T10:00:00+00:00", "added": "n/a"}],
                    "date_range": {"start": "2024-01-01", "end": "2026-06-28"}}}
    hs = L.extract(res, CTX)
    assert hs[0]["answer"] == "4213 transactions through 2026-06-28"
