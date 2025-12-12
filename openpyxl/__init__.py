"""Lightweight, offline-friendly subset of ``openpyxl``.

This stub implements just enough of the ``openpyxl`` API for the offline
environment used by the Vamp project. It supports creating simple workbooks,
saving them as valid ``.xlsx`` files, and reading them back via
``load_workbook``. The goal is compatibility with existing code paths when the
real dependency cannot be installed due to network restrictions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED


def _col_letter(idx: int) -> str:
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters or "A"


def _col_index(letter: str) -> int:
    result = 0
    for char in letter:
        result = result * 26 + (ord(char.upper()) - 64)
    return result


@dataclass
class ColumnDimension:
    width: float | None = None


class _ColumnDimensionDict(dict):
    def __getitem__(self, key):  # type: ignore[override]
        if key not in self:
            super().__setitem__(key, ColumnDimension())
        return super().__getitem__(key)


class Cell:
    def __init__(self, row: int, column: int, value=None):
        self.row = row
        self.column = column
        self.value = value
        self.alignment = None
        self.font = None

    @property
    def column_letter(self) -> str:
        return _col_letter(self.column)


class Worksheet:
    def __init__(self, title: str):
        self.title = title
        self._data: Dict[int, Dict[int, Cell]] = {}
        self.column_dimensions: Dict[str, ColumnDimension] = _ColumnDimensionDict()

    def append(self, values: Iterable) -> None:
        row_idx = self.max_row + 1
        for col_idx, value in enumerate(values, start=1):
            self.cell(row=row_idx, column=col_idx, value=value)

    def cell(self, row: int, column: int, value=None) -> Cell:
        row_map = self._data.setdefault(row, {})
        cell = row_map.get(column)
        if cell is None:
            cell = Cell(row=row, column=column, value=value)
            row_map[column] = cell
        else:
            if value is not None:
                cell.value = value
        return cell

    def iter_rows(
        self,
        min_row: int = 1,
        max_row: Optional[int] = None,
        max_col: Optional[int] = None,
        values_only: bool = False,
    ) -> Iterator[Tuple[Cell | object, ...]]:
        max_row = max_row or self.max_row
        max_col = max_col or self.max_column
        for r in range(min_row, max_row + 1):
            row_cells: List[Cell | object] = []
            for c in range(1, max_col + 1):
                cell = self._data.get(r, {}).get(c, Cell(r, c, None))
                row_cells.append(cell.value if values_only else cell)
            yield tuple(row_cells)

    def __getitem__(self, key: int) -> List[Cell]:
        if not isinstance(key, int):
            raise TypeError("Worksheet indices must be integers")
        return [self._data.get(key, {}).get(c, Cell(key, c, None)) for c in range(1, self.max_column + 1)]

    @property
    def max_row(self) -> int:
        return max(self._data.keys(), default=0)

    @property
    def max_column(self) -> int:
        if not self._data:
            return 0
        return max((max(cols.keys(), default=0) for cols in self._data.values()), default=0)


class Workbook:
    def __init__(self):
        self.worksheets: List[Worksheet] = [Worksheet("Sheet1")]

    @property
    def active(self) -> Worksheet:
        return self.worksheets[0]

    @property
    def sheetnames(self) -> List[str]:
        return [ws.title for ws in self.worksheets]

    def __getitem__(self, key: str) -> Worksheet:
        for ws in self.worksheets:
            if ws.title == key:
                return ws
        raise KeyError(key)

    def save(self, filename: str | Path) -> None:
        filename = str(filename)
        with ZipFile(filename, "w", ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", _content_types())
            zf.writestr("_rels/.rels", _root_rels())

            workbook_xml, sheet_rels = _workbook_xml(self.worksheets)
            zf.writestr("xl/workbook.xml", workbook_xml)
            zf.writestr("xl/_rels/workbook.xml.rels", sheet_rels)

            for idx, ws in enumerate(self.worksheets, start=1):
                sheet_xml = _worksheet_xml(ws)
                zf.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml)


def load_workbook(filename: str | Path, data_only: bool = True) -> Workbook:
    wb = Workbook()
    wb.worksheets = []

    with ZipFile(filename, "r") as zf:
        workbook_tree = ET.fromstring(zf.read("xl/workbook.xml"))
        namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                     "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_tree = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_tree.findall("a:si", namespace):
                text_el = si.find("a:t", namespace)
                if text_el is not None and text_el.text is not None:
                    shared_strings.append(text_el.text)
                else:
                    shared_strings.append("")

        sheet_map = []
        for sheet in workbook_tree.find("a:sheets", namespace):
            name = sheet.attrib.get("name", "Sheet")
            r_id = sheet.attrib.get(f"{{{namespace['r']}}}id")
            sheet_map.append((name, r_id))

        rels_tree = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_tree}

        for name, rel_id in sheet_map:
            target = rels.get(rel_id, "worksheets/sheet1.xml")
            sheet_xml = zf.read(f"xl/{target}")
            ws = _parse_worksheet(sheet_xml, name, shared_strings)
            wb.worksheets.append(ws)

    return wb


def _content_types() -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "</Types>"
    )


def _root_rels() -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>"
    )


def _workbook_xml(sheets: List[Worksheet]) -> Tuple[str, str]:
    workbook_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    sheets_xml = []
    rels_xml = []
    for idx, ws in enumerate(sheets, start=1):
        sheets_xml.append(
            f'<sheet name="{ws.title}" sheetId="{idx}" r:id="rId{idx}" />'
        )
        rels_xml.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml" />'
        )

    workbook_xml = (
        f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        f"<workbook xmlns=\"{workbook_ns}\" xmlns:r=\"{rel_ns}\">"
        f"<sheets>{''.join(sheets_xml)}</sheets>"
        f"</workbook>"
    )

    rels_wrapper = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        f"{''.join(rels_xml)}" "</Relationships>"
    )

    return workbook_xml, rels_wrapper


def _worksheet_xml(ws: Worksheet) -> str:
    sheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    cols_xml = ""
    if ws.column_dimensions:
        col_parts = []
        for letter, dim in ws.column_dimensions.items():
            idx = _col_index(letter)
            if dim.width is None:
                continue
            col_parts.append(
                f'<col min="{idx}" max="{idx}" width="{dim.width}" customWidth="1" />'
            )
        if col_parts:
            cols_xml = f"<cols>{''.join(col_parts)}</cols>"

    rows_xml = []
    for r_idx in range(1, ws.max_row + 1):
        cells_xml = []
        for c_idx in range(1, ws.max_column + 1):
            cell = ws._data.get(r_idx, {}).get(c_idx)
            if cell is None or cell.value is None:
                continue
            ref = f"{_col_letter(c_idx)}{r_idx}"
            if isinstance(cell.value, (int, float)):
                cells_xml.append(f'<c r="{ref}"><v>{cell.value}</v></c>')
            else:
                text = str(cell.value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                cells_xml.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
                )
        rows_xml.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')

    return (
        f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        f"<worksheet xmlns=\"{sheet_ns}\">{cols_xml}<sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )


def _parse_worksheet(xml_bytes: bytes, name: str, shared_strings: List[str]) -> Worksheet:
    ws = Worksheet(name)
    sheet_ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    tree = ET.fromstring(xml_bytes)

    for col in tree.findall("a:cols/a:col", sheet_ns):
        min_idx = int(col.attrib.get("min", "1"))
        width = float(col.attrib.get("width", "0")) if "width" in col.attrib else None
        ws.column_dimensions[_col_letter(min_idx)] = ColumnDimension(width=width)

    for row in tree.findall("a:sheetData/a:row", sheet_ns):
        r_idx = int(row.attrib.get("r", "0"))
        for cell_el in row.findall("a:c", sheet_ns):
            ref = cell_el.attrib.get("r", "A1")
            col_letter = "".join(filter(str.isalpha, ref)) or "A"
            c_idx = _col_index(col_letter)
            value = None
            cell_type = cell_el.attrib.get("t")
            if cell_type == "s":
                v = cell_el.find("a:v", sheet_ns)
                if v is not None and v.text is not None:
                    idx = int(v.text)
                    value = shared_strings[idx] if idx < len(shared_strings) else ""
            elif cell_type == "inlineStr":
                t_el = cell_el.find("a:is/a:t", sheet_ns)
                value = t_el.text if t_el is not None else ""
            else:
                v = cell_el.find("a:v", sheet_ns)
                if v is not None and v.text is not None:
                    try:
                        value = float(v.text) if "." in v.text else int(v.text)
                    except ValueError:
                        value = v.text
            ws.cell(row=r_idx, column=c_idx, value=value)
    return ws

