"""second_opinion.holdings: the shared holding classification."""

from second_opinion import holdings


def test_classify_buckets_by_quote_type() -> None:
    pos = [{"symbol": s, "units": 1, "price": 10.0, "account": "a"} for s in ("VTI", "AAPL", "SPAXX", "AMZN", "WEIRD")]
    info = {"VTI": {"quote_type": "ETF"}, "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            "SPAXX": {"quote_type": "MONEYMARKET"}, "AMZN": {"quote_type": "EQUITY", "sector": "Consumer Cyclical"},
            "WEIRD": {"quote_type": "OPTION"}}
    out, unknown = holdings.classify(pos, info, "AMZN")
    assert {p["symbol"]: p["bucket"] for p in out} == {"VTI": "core", "AAPL": "satellite", "SPAXX": "cash", "AMZN": "employer"}
    assert unknown == ["WEIRD"]


def test_employer_with_a_deep_pick_is_a_satellite() -> None:
    pos = [{"symbol": "AMZN", "units": 1, "price": 10.0, "account": "a"}]
    out, _ = holdings.classify(pos, {"AMZN": {"quote_type": "EQUITY", "sector": "x"}}, "AMZN", {"AMZN"})
    assert out[0]["bucket"] == "satellite"


def test_sweep_copy_is_dropped_once() -> None:
    pos = [{"symbol": "SPAXX", "units": 500, "price": 1.0, "account": "a", "bucket": "cash"},
           {"symbol": "VTI", "units": 1, "price": 10.0, "account": "a", "bucket": "core"}]
    assert [p["symbol"] for p in holdings.drop_sweep_copies(pos, {"a": 500.0})] == ["VTI"]


def test_core_rank_orders_bonds_last() -> None:
    pos = [{"symbol": "BND", "bucket": "core", "name": "Vanguard Total Bond Market ETF"},
           {"symbol": "VTI", "bucket": "core", "name": "Vanguard Total Stock Market ETF"}]
    ranks = holdings.core_rank(pos, {"BND": {"name": "Vanguard Total Bond Market ETF", "quote_type": "ETF"},
                                     "VTI": {"name": "Vanguard Total Stock Market ETF", "quote_type": "ETF"}})
    assert ranks["BND"] > ranks["VTI"]
