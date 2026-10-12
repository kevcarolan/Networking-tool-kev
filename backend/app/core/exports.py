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
