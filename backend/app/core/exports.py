"""Spreadsheet-safe exports (CSV and XLSX).

Cells in the exports can hold text from outside: a username typed at the sign-in page,
a circuit sheet someone uploaded, or a switch's own output. Excel runs a cell that starts
with = + - @ as a formula, so such text could open links or run commands on the computer
of whoever opens the export. Text cells that start that way get a leading apostrophe in
CSV (Excel shows the text as typed) and are stored as plain text in XLSX.
"""

import csv
import re

_RISKY = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def risky(value) -> bool:
    return (isinstance(value, str) and value[:1] in _RISKY and value != "-"
            and not _NUMBER.match(value))


def safe(value):
    return "'" + value if risky(value) else value


class _Writer:
    def __init__(self, out):
        self._w = csv.writer(out)

    def writerow(self, row):
        return self._w.writerow([safe(v) for v in row])


def csv_writer(out) -> _Writer:
    """csv.writer that neutralises formula-like text."""
    return _Writer(out)


def append_row(ws, values) -> None:
    """ws.append, keeping formula-like text as text (openpyxl would make it a formula)."""
    ws.append(values)
    for cell in ws[ws.max_row]:
        if risky(cell.value):
            cell.data_type = "s"


# --- blank templates -------------------------------------------------------------------------

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def template(fmt: str, labels: list[str], name: str, notes: list[str] = (),
             choices: dict[str, list[str]] | None = None, sheet: str = "Sheet1"):
    """A blank spreadsheet with only the column names, for people to fill in and import.

    ``fmt`` is "csv" or "xlsx". The workbook also gets a pick-list on columns with
    ``choices`` and a second sheet, "How to fill in", with ``notes`` (imports read the
    first sheet). Returns a FastAPI Response."""
    import io

    from fastapi import Response

    if fmt == "csv":
        out = io.StringIO()
        csv_writer(out).writerow(labels)
        return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    append_row(ws, labels)
    for i, label in enumerate(labels, 1):
        ws.cell(1, i).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(label) + 4))
        options = (choices or {}).get(label)
        listed = ",".join(o.replace('"', "") for o in options or ())
        if options and len(listed) <= 250:  # Excel's limit for a typed-in list
            dv = DataValidation(type="list", formula1=f'"{listed}"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(i)}2:{get_column_letter(i)}5000")
    ws.freeze_panes = "A2"
    if notes:
        help_ws = wb.create_sheet("How to fill in")
        for line in notes:
            append_row(help_ws, [line])
        help_ws.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
