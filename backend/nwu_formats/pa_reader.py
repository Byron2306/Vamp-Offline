"""Parser for NWU Performance Agreement spreadsheets."""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional


XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    """Return the workbook shared strings table or an empty list if missing."""

    try:
        xml_data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_data)
    shared: List[str] = []
    for si in root.findall("main:si", XML_NS):
        text_parts = [t.text or "" for t in si.findall(".//main:t", XML_NS)]
        shared.append("".join(text_parts))
    return shared


def _get_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    """Resolve the worksheet path for the requested sheet name."""

    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets_parent = workbook.find("main:sheets", XML_NS)
    if sheets_parent is None:
        raise ValueError("Workbook is missing sheets definition")

    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    for sheet in sheets_parent.findall("main:sheet", XML_NS):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id or rel_id not in rel_map:
            break
        target = rel_map[rel_id]
        return f"xl/{target}"

    raise ValueError(f"Sheet '{sheet_name}' not found")


def _column_index(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def _clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("_x000D_", "\n").replace("\r", "\n")
    return text.strip()


def _split_lines(text: str):
    if not text:
        return ""
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    if len(parts) > 1:
        return parts
    return parts[0] if parts else ""


def _parse_numeric(text: str) -> Optional[float]:
    try:
        return float(text)
    except Exception:
        return None


def _iter_rows(zf: zipfile.ZipFile, sheet_path: str, shared: List[str]) -> Iterable[Dict[str, str]]:
    sheet = ET.fromstring(zf.read(sheet_path))
    for row in sheet.findall("main:sheetData/main:row", XML_NS):
        values: Dict[str, str] = {}
        for cell in row.findall("main:c", XML_NS):
            ref = cell.attrib.get("r", "")
            col = _column_index(ref)
            cell_type = cell.attrib.get("t")
            value_el = cell.find("main:v", XML_NS)
            raw_value = value_el.text if value_el is not None else None

            if cell_type == "s":
                resolved = shared[int(raw_value)] if raw_value is not None else ""
            elif cell_type == "inlineStr":
                inline = cell.find("main:is", XML_NS)
                resolved = "".join(t_el.text or "" for t_el in inline.findall(".//main:t", XML_NS)) if inline is not None else ""
            else:
                resolved = raw_value or ""

            values[col] = _clean_text(resolved)
        yield values


def read_nwu_pa(path_to_xlsx) -> Dict[str, Dict[str, object]]:
    """Read a NWU Performance Agreement workbook into a structured dictionary.

    Args:
        path_to_xlsx: Path to the Performance Agreement .xlsx file.

    Returns:
        A dictionary keyed by KPA name (column A) where each value is another
        dictionary keyed by the column headers from row 2 (columns B–G). Multi-
        line cell values are split on ``\n``.
    """

    path = Path(path_to_xlsx)
    if not path.exists():
        raise FileNotFoundError(path_to_xlsx)

    with zipfile.ZipFile(path) as zf:
        shared_strings = _load_shared_strings(zf)
        sheet_path = _get_sheet_path(zf, "pa-report")

        headers: List[str] = []
        result: Dict[str, Dict[str, object]] = {}

        for idx, row_values in enumerate(_iter_rows(zf, sheet_path, shared_strings), start=1):
            if idx == 1:
                continue  # Title row
            if idx == 2:
                headers = [row_values.get(col, "").strip() for col in ("A", "B", "C", "D", "E", "F", "G")]
                continue

            kpa_name_raw = row_values.get("A", "")
            kpa_name = _clean_text(kpa_name_raw)
            if not kpa_name:
                continue

            row_data: Dict[str, object] = {}
            for col_letter, raw_value in zip(["B", "C", "D", "E", "F", "G"], headers[1:]):
                header = raw_value or col_letter
                cleaned = _clean_text(row_values.get(col_letter, ""))
                value: object = _split_lines(cleaned)
                if col_letter in {"D", "E"}:
                    numeric_value = _parse_numeric(cleaned)
                    if numeric_value is not None:
                        value = numeric_value
                row_data[header] = value

            result[kpa_name] = row_data

    return result
