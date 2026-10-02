"""Pure 13F work: information-table XML to holdings by CUSIP, and the quarter-over-quarter diff."""
from __future__ import annotations

from second_opinion import thirteenf

XML = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>ALLY FINL INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>02005N100</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>DFND</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>ALLY FINL INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>02005N100</cusip><value>50</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>DFND</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>1000</value>
    <shrsOrPrnAmt><sshPrnamt>4</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>30</value>
    <shrsOrPrnAmt><sshPrnamt>7</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><putCall>Put</putCall><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
</informationTable>"""


def test_parse_information_table_aggregates_by_cusip_and_keeps_options_apart() -> None:
    holdings = thirteenf.parse_information_table(XML)
    assert holdings == {
        "02005N100": {"cusip": "02005N100", "issuer": "ALLY FINL INC", "class": "COM", "value": 150, "shares": 15, "put_call": None},
        "037833100": {"cusip": "037833100", "issuer": "APPLE INC", "class": "COM", "value": 1000, "shares": 4, "put_call": None},
        "037833100:PUT": {"cusip": "037833100", "issuer": "APPLE INC", "class": "COM", "value": 30, "shares": 7, "put_call": "PUT"},
    }


def test_parse_information_table_rejects_non_xml() -> None:
    import pytest

    with pytest.raises(ValueError):
        thirteenf.parse_information_table(b"<html>blocked</html>")


def _h(cusip: str, issuer: str, value: int, shares: int, put_call: str | None = None) -> dict:
    return {"cusip": cusip, "issuer": issuer, "class": "COM", "value": value, "shares": shares, "put_call": put_call}


def test_diff_holdings_classifies_new_exited_increased_trimmed_and_unchanged() -> None:
    current = {"A": _h("A", "ALPHA", 1000, 100), "B": _h("B", "BETA", 600, 60), "C": _h("C", "GAMMA", 300, 30), "E": _h("E", "EPSILON", 50, 5)}
    previous = {"A": _h("A", "ALPHA", 800, 80), "B": _h("B", "BETA", 700, 100), "D": _h("D", "DELTA", 200, 20), "E": _h("E", "EPSILON", 40, 5)}
    out = thirteenf.diff_holdings(current, previous)
    assert out["totals"] == {"value": 1950, "previous_value": 1740, "positions": 4, "previous_positions": 4, "value_change_pct": 12.07}
    assert out["new"] == [{"cusip": "C", "issuer": "GAMMA", "class": "COM", "put_call": None, "shares": 30, "value": 300, "weight_pct": 15.38}]
    assert out["exited"] == [{"cusip": "D", "issuer": "DELTA", "class": "COM", "put_call": None, "previous_shares": 20, "previous_value": 200}]
    assert out["increased"] == [{"cusip": "A", "issuer": "ALPHA", "class": "COM", "put_call": None, "shares": 100, "previous_shares": 80, "shares_change_pct": 25.0, "value": 1000, "weight_pct": 51.28}]
    assert out["trimmed"] == [{"cusip": "B", "issuer": "BETA", "class": "COM", "put_call": None, "shares": 60, "previous_shares": 100, "shares_change_pct": -40.0, "value": 600, "weight_pct": 30.77}]
    assert out["unchanged"] == 1
    assert [t["cusip"] for t in out["top"]] == ["A", "B", "C", "E"] and out["top"][0]["weight_pct"] == 51.28
    assert out["concentration"] == {"top_5_pct": 100.0, "top_10_pct": 100.0}


def test_diff_holdings_orders_by_value_and_caps_lists() -> None:
    current = {f"C{i}": _h(f"C{i}", f"N{i}", 100 * i, i) for i in range(1, 8)}
    out = thirteenf.diff_holdings(current, {}, limit=3)
    assert [n["cusip"] for n in out["new"]] == ["C7", "C6", "C5"] and out["truncated"] == {"new": 4}
    assert out["totals"]["previous_value"] is None and out["totals"]["value_change_pct"] is None


def test_manager_aliases_resolve_case_insensitively_and_by_substring() -> None:
    assert thirteenf.resolve_manager("Berkshire") == (1067983, "berkshire")
    assert thirteenf.resolve_manager("pershing square") == (1336528, "pershing-square")
    assert thirteenf.resolve_manager("1067983") == (1067983, "berkshire")
    assert thirteenf.resolve_manager("nobody-here") is None
    assert all(isinstance(cik, int) for cik in thirteenf.MANAGERS.values())
