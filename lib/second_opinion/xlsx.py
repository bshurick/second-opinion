"""Read an .xlsx worksheet with the standard library.

A workbook is a zip of XML parts. This reader resolves the sheet list from ``xl/workbook.xml``
and its relationships, shared strings from ``xl/sharedStrings.xml``, and date styles from
``xl/styles.xml`` (built-in number formats 14-22 and 45-47, plus any custom format whose code
contains a day, month or year token). Cells come back as strings: dates as ``MM/DD/YYYY``,
numbers as their shortest plain form (``240`` not ``240.0``), everything else verbatim.
Missing rows and cells are empty. Formulas contribute their cached value only.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_M = "{%s}" % _NS["m"]
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_EPOCH = date(1899, 12, 30)
_BUILTIN_DATE_IDS = set(range(14, 23)) | set(range(45, 48))


def _open(path: Path) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"{path} is not an xlsx workbook: {exc}") from exc
    if "xl/workbook.xml" not in z.namelist():
        raise ValueError(f"{path} is not an xlsx workbook: no xl/workbook.xml")
    return z


def _sheets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(name, part path)] in workbook order."""
    rels = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            target = rel.get("Target") or ""
            rels[rel.get("Id")] = target if target.startswith("/") else "xl/" + target
    out = []
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(_M + "sheet"):
        rid = sheet.get(_REL_NS + "id")
        part = rels.get(rid, "").lstrip("/")
        if not part:
            n = len(out) + 1
            part = f"xl/worksheets/sheet{n}.xml"
        out.append((sheet.get("name") or f"Sheet{len(out) + 1}", part))
    return out


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    strings = []
    for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_M + "si"):
        strings.append("".join(t.text or "" for t in si.iter(_M + "t")))
    return strings


def _date_styles(z: zipfile.ZipFile) -> set[int]:
    """Indexes into cellXfs whose number format is a date."""
    if "xl/styles.xml" not in z.namelist():
        return set()
    root = ET.fromstring(z.read("xl/styles.xml"))
    custom = {}
    for fmt in root.iter(_M + "numFmt"):
        custom[int(fmt.get("numFmtId"))] = fmt.get("formatCode") or ""
    out = set()
    xfs = root.find("m:cellXfs", _NS)
    for i, xf in enumerate(xfs if xfs is not None else []):
        fid = int(xf.get("numFmtId") or 0)
        code = custom.get(fid, "")
        if fid in _BUILTIN_DATE_IDS or (code and re.search(r"[dmy]", code.lower()) and "general" not in code.lower()):
            out.add(i)
    return out


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _number_text(raw: str) -> str:
    try:
        value = float(raw)
    except ValueError:
        return raw
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def sheet_names(path: Path) -> list[str]:
    with _open(Path(path)) as z:
        return [name for name, _ in _sheets(z)]


def read_sheet(path: Path, sheet: str | None = None) -> list[list[str]]:
    with _open(Path(path)) as z:
        sheets = _sheets(z)
        if sheet is None:
            name, part = sheets[0]
        else:
            match = [s for s in sheets if s[0] == sheet]
            if not match:
                raise ValueError(f"no sheet named {sheet!r}; sheets: {', '.join(n for n, _ in sheets)}")
            name, part = match[0]
        strings = _shared_strings(z)
        date_styles = _date_styles(z)
        root = ET.fromstring(z.read(part))
        rows: list[list[str]] = []
        running_width = 0
        for row in root.iter(_M + "row"):
            r = int(row.get("r") or (len(rows) + 1))
            while len(rows) < r - 1:
                rows.append([])
            cells: dict[int, str] = {}
            for c in row.findall("m:c", _NS):
                ref = c.get("r") or ""
                kind = c.get("t")
                style = c.get("s")
                v = c.find("m:v", _NS)
                text = (v.text or "") if v is not None else ""
                if kind == "s":
                    idx = int(text) if text else -1
                    text = strings[idx] if 0 <= idx < len(strings) else ""
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(_M + "t"))
                elif kind in ("str", "b", "e"):
                    pass
                elif text and style is not None and int(style) in date_styles:
                    try:
                        text = (_EPOCH + timedelta(days=int(float(text)))).strftime("%m/%d/%Y")
                    except (ValueError, OverflowError):
                        pass
                elif text:
                    text = _number_text(text)
                cells[_col_index(ref) if ref else len(cells)] = text
            # Pad to the widest row seen so far (a short trailing column, e.g. an empty
            # Category, still lines up under its header) without disturbing earlier, narrower
            # rows such as a single-cell title above the header.
            running_width = max(running_width, (max(cells) + 1) if cells else 0)
            rows.append([cells.get(i, "") for i in range(running_width)])
        return rows


def to_csv_text(path: Path, sheet: str | None = None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in read_sheet(path, sheet):
        writer.writerow(row)
    return buf.getvalue()
