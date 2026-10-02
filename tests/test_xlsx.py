"""Stdlib xlsx reader used by the spending importer."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from second_opinion import xlsx

_CT = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""
_WB = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Transactions" sheetId="1" r:id="rId1"/><sheet name="Summary" sheetId="2" r:id="rId2"/></sheets></workbook>"""
_WB_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
_SS = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">
<si><t>Transaction Details</t></si><si><t>Date</t></si><si><t>Description</t></si><si><t>Amount</t></si>
<si><r><t>SQ *BLUE </t></r><r><t>BOTTLE</t></r></si><si><t>Category</t></si></sst>"""
# style 0 = General, style 1 = built-in date format 14 (m/d/yyyy), style 2 = custom "mm/dd/yyyy"
_STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="mm/dd/yyyy"/></numFmts>
<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs>
</styleSheet>"""
_S1 = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c></row>
<row r="3"><c r="A3" t="s"><v>1</v></c><c r="B3" t="s"><v>2</v></c><c r="C3" t="s"><v>3</v></c><c r="D3" t="s"><v>5</v></c></row>
<row r="4"><c r="A4" s="1"><v>46246</v></c><c r="B4" t="s"><v>4</v></c><c r="C4"><v>6.5</v></c><c r="D4" t="inlineStr"><is><t>Restaurant-Bar</t></is></c></row>
<row r="5"><c r="A5" s="2"><v>46247</v></c><c r="B5" t="str"><v>COSTCO WHSE</v></c><c r="C5"><v>240</v></c></row>
</sheetData></worksheet>"""
_S2 = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>Total</t></is></c><c r="B1"><v>246.5</v></c></row>
</sheetData></worksheet>"""


@pytest.fixture
def workbook(tmp_path) -> Path:
    path = tmp_path / "activity.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", _WB)
        z.writestr("xl/_rels/workbook.xml.rels", _WB_RELS)
        z.writestr("xl/sharedStrings.xml", _SS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", _S1)
        z.writestr("xl/worksheets/sheet2.xml", _S2)
    return path


def test_sheet_names(workbook) -> None:
    assert xlsx.sheet_names(workbook) == ["Transactions", "Summary"]


def test_read_first_sheet_renders_dates_numbers_and_strings(workbook) -> None:
    rows = xlsx.read_sheet(workbook)
    assert rows[0] == ["Transaction Details"]
    assert rows[1] == []                       # row 2 is absent from the sheet: an empty row
    assert rows[2] == ["Date", "Description", "Amount", "Category"]
    assert rows[3] == ["08/12/2026", "SQ *BLUE BOTTLE", "6.5", "Restaurant-Bar"]
    assert rows[4] == ["08/13/2026", "COSTCO WHSE", "240", ""]


def test_read_named_sheet_and_missing_sheet(workbook) -> None:
    assert xlsx.read_sheet(workbook, "Summary") == [["Total", "246.5"]]
    with pytest.raises(ValueError, match="sheet"):
        xlsx.read_sheet(workbook, "Nope")


def test_to_csv_text_round_trips_through_csv(workbook) -> None:
    import csv
    import io

    text = xlsx.to_csv_text(workbook)
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[2] == ["Date", "Description", "Amount", "Category"]
    assert parsed[3][1] == "SQ *BLUE BOTTLE"


def test_not_a_workbook(tmp_path) -> None:
    bad = tmp_path / "x.xlsx"
    bad.write_text("not a zip")
    with pytest.raises(ValueError, match="workbook"):
        xlsx.read_sheet(bad)


def test_shared_string_cell_without_shared_strings_part_reads_empty(tmp_path) -> None:
    """A t="s" cell with no xl/sharedStrings.xml (or an out-of-range index) is "", not an IndexError."""
    path = tmp_path / "no-strings.xlsx"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>5</v></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    assert xlsx.read_sheet(path) == [["", "5"]]
