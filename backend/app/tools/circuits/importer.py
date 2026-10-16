"""Reads the master circuit list (an .xlsx workbook or a CSV file), and the rules for
linking a row to a device and interface.

The header is found by its column names (not by position), so column order and
the coloured band rows above it don't matter. Columns an admin adds (``ct_fields``)
are read by their name too; their values are kept in ``Circuit.custom``."""

import csv
import hashlib
import io
import ipaddress
import re
import zipfile
from dataclasses import dataclass, field

FIELDS = (
    "ip_partition", "service", "eng_prefix", "device_name", "device_type", "manufacturer",
    "mac", "site", "floor", "room", "ip", "mask", "gateway", "vlan", "conn_type", "port", "switch",
    "drawing_number", "drawing_ref",
)

# The column names in exports and blank templates (each is also a header the import knows).
LABELS = {
    "ip_partition": "IP Partition", "service": "Service", "eng_prefix": "Engineering prefix",
    "device_name": "Device Name", "device_type": "Device Type", "manufacturer": "Manufacturer",
    "mac": "Hardware Mac Address", "site": "Site", "floor": "Floor Level", "room": "Room / Area",
    "ip": "IP Address", "mask": "Subnet Mask", "gateway": "Default Gateway", "vlan": "VLAN",
    "conn_type": "TYPE", "port": "PORT", "switch": "DEVICE", "drawing_number": "Drawing Number",
    "drawing_ref": "Device Drawing Reference",
}

# Header text (normalised: lower case, letters/digits only, single spaces) -> field
_HEADERS = {
    "ip partition": "ip_partition", "partition": "ip_partition",
    "service": "service",
    "engineering prefix": "eng_prefix", "eng prefix": "eng_prefix",
    "device name": "device_name",
    "device type": "device_type",
    "manufacturer": "manufacturer", "manufacture": "manufacturer",
    "hardware mac address": "mac", "mac address": "mac", "mac": "mac",
    "site": "site", "site name": "site", "site code": "site",
    "floor level": "floor", "floor": "floor",
    "room area": "room", "room": "room",
    "ip address": "ip", "ip": "ip",
    "subnet mask": "mask", "mask": "mask",
    "default gateway": "gateway", "gateway": "gateway",
    "vlan": "vlan", "vlan id": "vlan",
    "type": "conn_type",
    "port": "port", "switch port": "port",
    "device": "switch", "switch": "switch",
    # common names in other people's lists (asset registers, switch port exports)
    "name": "device_name", "hostname": "device_name", "asset": "device_name",
    "asset name": "device_name", "end device": "device_name",
    "mac addr": "mac", "ethernet address": "mac", "physical address": "mac",
    "ip addr": "ip", "ipv4 address": "ip", "ipv4": "ip",
    "switch name": "switch", "access switch": "switch", "switch hostname": "switch",
    "interface": "port", "switchport": "port", "port number": "port", "switch interface": "port",
    "vendor": "manufacturer", "make": "manufacturer", "model": "device_type",
    "location": "room", "building": "site", "level": "floor",
    "drawing number": "drawing_number",
    "device drawing reference": "drawing_ref", "drawing reference": "drawing_ref",
}
# DEVICE and PORT are optional: NetOps finds the switch port from the MAC (or IP).
REQUIRED: tuple[str, ...] = ()
MIN_HEADER_MATCHES = 6


class CircuitImportError(Exception):
    pass


@dataclass
class ParsedRow:
    row_no: int
    values: dict[str, str]
    switch_norm: str
    port_norm: str
    mac_norm: str
    warnings: list[str] = field(default_factory=list)
    custom: dict[str, str] = field(default_factory=dict)  # custom column key -> value


@dataclass
class ParsedSheet:
    sheet: str
    header_row: int
    columns: dict[str, str]  # field (or x_<custom key>) -> header text found
    rows: list[ParsedRow]
    headers: list[str] = field(default_factory=list)  # the header row's cells
    mapping: dict[int, str] = field(default_factory=dict)  # column index -> field used


@dataclass
class Mapping:
    """Which column is which, chosen by a person for a sheet whose headers aren't known."""
    header_row: int  # 0-based row of the sheet that holds the column names
    columns: dict[int, str]  # column index -> field or x_<custom key>; others are ignored
    sheet: str = ""  # workbook sheet ("" = the first one; CSV has one)


class NeedsMapping(CircuitImportError):
    """No header row could be recognised: the person picks the columns (``read_head``)."""


def _norm_header(text) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def header_signature(cells) -> str:
    """Identity of a spreadsheet layout: its header row, normalised (case, spaces and
    punctuation don't matter), as SHA-256 hex."""
    names = [_norm_header(c) for c in cells]
    while names and not names[-1]:
        names.pop()
    return hashlib.sha256("|".join(names).encode()).hexdigest()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


# --- normalisation used for matching ----------------------------------------

_PORT_PREFIXES = (  # longest first
    ("twentyfivegige", "twe"), ("hundredgigabitethernet", "hu"), ("hundredgige", "hu"),
    ("fortygigabitethernet", "fo"), ("tengigabitethernet", "te"), ("twogigabitethernet", "tw"),
    ("fivegigabitethernet", "fi"), ("gigabitethernet", "gi"), ("fastethernet", "fa"),
    ("port-channel", "po"), ("ethernet", "eth"), ("twe", "twe"), ("gig", "gi"),
    ("ten", "te"), ("eth", "eth"), ("gi", "gi"), ("te", "te"), ("tw", "tw"), ("fi", "fi"),
    ("fa", "fa"), ("fo", "fo"), ("hu", "hu"), ("po", "po"), ("port", "port"), ("e", "eth"),
    ("et", "eth"),  # Arista Et5 = Ethernet5
    ("ge", "gi"), ("xgigabitethernet", "xge"),  # Huawei GE0/0/5 = GigabitEthernet0/0/5
)


def normalize_port(port: str) -> str:
    """'Gi2/0/13', 'GigabitEthernet2/0/13' and 'gi 2/0/13' -> 'gi2/0/13';
    AlliedWare Plus 'port1.0.1' -> 'port1.0.1'; Junos 'ge-0/0/5.0' -> 'ge-0/0/5'."""
    p = re.sub(r"\s+", "", (port or "").lower())
    p = re.sub(r"^([a-z]{2,3}-\d+/\d+/\d+|ae\d+)\.\d+$", r"\1", p)  # Junos logical unit
    m = re.match(r"^([a-z-]+)(\d.*)$", p)
    if not m:
        return p
    name, rest = m.groups()
    for long, short in _PORT_PREFIXES:
        if name == long:
            return short + rest
    return p


def normalize_switch(name: str) -> str:
    return (name or "").strip().lower()


def normalize_mac(mac: str) -> str:
    hexdigits = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    if len(hexdigits) != 12:
        return ""
    return ":".join(hexdigits[i:i + 2] for i in range(0, 12, 2))


def switch_matches(device_name: str, key: str) -> bool:
    """Does a NetOps device name match a circuit-list switch name?

    'ACC-SW01' matches 'ACC-SW01', 'acc-sw01.corp.local' and 'SITEA-ACC-SW01'."""
    d, k = device_name.lower(), key.lower()
    if not k:
        return False
    return d == k or d.split(".")[0] == k or d.endswith("-" + k) or d.endswith("_" + k)


def match_switches(device_names: dict[int, str], keys: set[str]) -> dict[str, tuple[str, list[int]]]:
    """For each switch key: ('matched', [id]) / ('ambiguous', [ids]) / ('unmatched', [])."""
    result = {}
    for key in keys:
        ids = [i for i, name in device_names.items() if switch_matches(name, key)]
        exact = [i for i in ids if device_names[i].lower().split(".")[0] == key]
        if exact:
            ids = exact
        result[key] = ("matched", ids) if len(ids) == 1 else (
            ("ambiguous", ids) if ids else ("unmatched", []))
    return result


# --- validation -------------------------------------------------------------

def _validate(v: dict[str, str]) -> list[str]:
    w = []
    if not v["mac"] and not v["ip"]:
        w.append("no MAC or IP address, so it can't be found on the network")
    if bool(v["switch"]) != bool(v["port"]):
        w.append("only one of NETWORK PORT DEVICE and PORT is filled in")
    for key, label in (("ip", "IP address"), ("gateway", "default gateway")):
        if v[key]:
            try:
                ipaddress.ip_address(v[key])
            except ValueError:
                w.append(f"{label} '{v[key]}' is not a valid IP")
    if v["mask"]:
        try:
            ipaddress.ip_network(f"0.0.0.0/{v['mask']}")
        except ValueError:
            w.append(f"subnet mask '{v['mask']}' is not valid")
    if v["vlan"] and not (v["vlan"].isdigit() and 1 <= int(v["vlan"]) <= 4094):
        w.append(f"VLAN '{v['vlan']}' is not 1-4094")
    if v["mac"] and not normalize_mac(v["mac"]):
        w.append(f"MAC '{v['mac']}' is not a valid MAC address")
    return w


# --- reading the workbook ---------------------------------------------------

def _find_header(rows: list[tuple], custom: dict[str, str] | None = None
                 ) -> tuple[int, dict[int, str], dict[str, str]] | None:
    """The header row: one with at least MIN_HEADER_MATCHES known column names, or one
    where every name is known (a blank template with only a few columns ticked).
    ``custom`` maps a custom column's normalised name to ``x_<key>``."""
    known = {**_HEADERS, **(custom or {})}
    for idx, row in enumerate(rows):
        mapping, found, unknown = {}, {}, 0
        for col, cell in enumerate(row):
            name = _norm_header(cell)
            fld = known.get(name)
            if fld and fld not in found:
                mapping[col], found[fld] = fld, _cell(cell)
            elif name and not fld:
                unknown += 1
        standard = sum(1 for f in found if not f.startswith("x_"))
        if standard >= MIN_HEADER_MATCHES or (
                not unknown and len(found) >= 2 and ("mac" in found or "ip" in found)):
            return idx, mapping, found
    return None


# A workbook is a zip file; refuse one that would unpack to more than this.
MAX_UNPACKED = 500 * 2**20


def _check_unpacked_size(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
    except (zipfile.BadZipFile, ValueError):
        raise CircuitImportError("Not a readable .xlsx workbook (not a zip file)") from None
    if total > MAX_UNPACKED:
        raise CircuitImportError(
            f"The workbook unpacks to more than {MAX_UNPACKED // 2**20} MB; save it again in "
            "Excel without unused rows, columns or pictures")


_NOT_FOUND = ("No sheet has the circuit list header (e.g. 'Device Name', 'IP Address', 'VLAN', "
              "'PORT', 'DEVICE') in its first 15 rows")


def _apply_mapping(head: list[tuple], header_idx: int, columns: dict[int, str],
                   known: set[str]) -> tuple[int, dict[int, str], dict[str, str]]:
    if not 0 <= header_idx < len(head):
        raise CircuitImportError("The header row chosen isn't in the first 15 rows")
    row, mapping, found = head[header_idx], {}, {}
    for col, fld in sorted(columns.items()):
        if fld not in known:
            raise CircuitImportError(f"Unknown column '{fld}'")
        if fld in found:
            raise CircuitImportError(f"'{LABELS.get(fld, fld)}' is chosen for more than one column")
        mapping[col] = fld
        found[fld] = _cell(row[col]) if col < len(row) else ""
    return header_idx, mapping, found


def _read_sheet(title: str, head: list[tuple], rows_after, custom: dict[str, str] | None,
                max_rows: int, mapping: Mapping | None = None,
                saved: dict[str, dict[int, str]] | None = None) -> ParsedSheet | None:
    """One sheet: ``head`` is its first 15 rows, ``rows_after(n)`` its rows from row n
    (1-based). None when the sheet has no circuit list header. ``mapping`` (chosen by a
    person) is used instead of finding the header; ``saved`` (header signature -> columns)
    holds the layouts people chose before."""
    known = set(FIELDS) | set((custom or {}).values())
    if mapping is not None:
        found = _apply_mapping(head, mapping.header_row, mapping.columns, known)
    else:
        found = _find_header(head, custom)
        if not found and saved:
            for idx, row in enumerate(head):
                cols = saved.get(header_signature(row))
                if cols:  # a custom column deleted since then is skipped
                    found = _apply_mapping(head, idx, {c: f for c, f in cols.items()
                                                       if f in known}, known)
                    break
    if not found:
        return None
    header_idx, mapping_used, columns = found
    missing = [f for f in REQUIRED if f not in columns]
    if missing:
        raise CircuitImportError(f"Sheet '{title}': columns {', '.join(missing)} not found")
    if "mac" not in columns and "ip" not in columns:
        raise CircuitImportError(
            f"Sheet '{title}': no MAC address or IP address column (such as 'Hardware Mac "
            "Address' or 'IP Address') - one of them is needed to find each circuit")
    rows = []
    start = header_idx + 2  # 1-based row number of the first data row
    for row_no, raw in enumerate(rows_after(start), start):
        values = {f: "" for f in FIELDS}
        extra = {}
        for col, fld in mapping_used.items():
            if col < len(raw):
                if fld.startswith("x_"):
                    extra[fld[2:]] = _cell(raw[col])[:500]
                else:
                    values[fld] = _cell(raw[col])
        if not any(values.values()) and not any(extra.values()):
            continue
        if len(rows) >= max_rows:
            raise CircuitImportError(f"More than {max_rows} rows - is this the right sheet?")
        rows.append(ParsedRow(
            row_no=row_no, values=values, switch_norm=normalize_switch(values["switch"]),
            port_norm=normalize_port(values["port"]), mac_norm=normalize_mac(values["mac"]),
            warnings=_validate(values), custom={k: v for k, v in extra.items() if v}))
    return ParsedSheet(sheet=title, header_row=header_idx + 1, columns=columns, rows=rows,
                       headers=[_cell(c) for c in head[header_idx]], mapping=mapping_used)


def _open_workbook(data: bytes):
    from openpyxl import load_workbook

    _check_unpacked_size(data)
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - zip/xml errors of a non-xlsx file
        raise CircuitImportError(f"Not a readable .xlsx workbook ({type(exc).__name__})") from None


def parse_workbook(data: bytes, max_rows: int = 50000, custom: dict[str, str] | None = None,
                   mapping: Mapping | None = None,
                   saved: dict[str, dict[int, str]] | None = None) -> ParsedSheet:
    wb = _open_workbook(data)
    try:
        sheets = wb.worksheets
        if mapping is not None:
            sheets = [ws for ws in sheets if ws.title == mapping.sheet] if mapping.sheet else sheets[:1]
            if not sheets:
                raise CircuitImportError(f"The workbook has no sheet '{mapping.sheet}'")
        for ws in sheets:
            head = [tuple(r) for r in ws.iter_rows(min_row=1, max_row=15, values_only=True)]
            parsed = _read_sheet(ws.title, head,
                                 lambda n, ws=ws: ws.iter_rows(min_row=n, values_only=True),
                                 custom, max_rows, mapping, saved)
            if parsed:
                return parsed
    finally:
        wb.close()
    raise NeedsMapping(_NOT_FOUND)


def _csv_table(data: bytes, max_rows: int) -> list[tuple]:
    if data[:2] == b"PK":
        raise CircuitImportError("This is an Excel workbook: name it .xlsx, or save it as CSV")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=first.count) if first else ","
    try:
        table = []
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            table.append(tuple(row))
            if len(table) > max_rows + 20:
                break
    except csv.Error as exc:
        raise CircuitImportError(f"Not a readable CSV file ({exc})") from None
    return table


def parse_csv(data: bytes, max_rows: int = 50000, custom: dict[str, str] | None = None,
              mapping: Mapping | None = None,
              saved: dict[str, dict[int, str]] | None = None) -> ParsedSheet:
    """A CSV file: comma, semicolon or tab separated (Excel uses ';' in some countries),
    UTF-8 or Windows text."""
    table = _csv_table(data, max_rows)
    parsed = _read_sheet("CSV", table[:15], lambda n: table[n - 1:], custom, max_rows,
                         mapping, saved)
    if parsed is None:
        raise NeedsMapping(_NOT_FOUND.replace("No sheet has", "The file doesn't have"))
    return parsed


HEAD_ROWS, HEAD_COLS, HEAD_CELL = 15, 60, 120


def read_head(data: bytes, csv_file: bool) -> list[dict]:
    """The first rows of each sheet, as text, for a person to pick the header row and say
    which column is which."""
    def clip(rows):
        out = [[_cell(c)[:HEAD_CELL] for c in r[:HEAD_COLS]] for r in rows[:HEAD_ROWS]]
        width = max((len(r) for r in out), default=0)
        return [r + [""] * (width - len(r)) for r in out]

    if csv_file:
        return [{"name": "CSV", "rows": clip(_csv_table(data, HEAD_ROWS))}]
    wb = _open_workbook(data)
    try:
        return [{"name": ws.title, "rows": clip([tuple(r) for r in ws.iter_rows(
            min_row=1, max_row=HEAD_ROWS, values_only=True)])} for ws in wb.worksheets]
    finally:
        wb.close()


def guess(rows: list[list[str]], custom: dict[str, str] | None = None) -> dict:
    """A starting point for the person: the row with the most column names we know, and
    which of its columns we recognise."""
    known = {**_HEADERS, **(custom or {})}
    best, best_idx = {}, None
    for idx, row in enumerate(rows):
        cols, used = {}, set()
        for col, cell in enumerate(row):
            fld = known.get(_norm_header(cell))
            if fld and fld not in used:
                cols[col] = fld
                used.add(fld)
        if len(cols) > len(best):
            best, best_idx = cols, idx
    if best_idx is None:  # nothing known: the first row with text in it
        best_idx = next((i for i, r in enumerate(rows) if any(r)), 0)
    return {"header_row": best_idx, "columns": best}


# --- comparing two versions of the list -------------------------------------

def row_key(values: dict[str, str], mac_norm: str) -> str:
    """Identity of a row across imports: its MAC, else its device name, else its port."""
    if mac_norm:
        return "mac:" + mac_norm
    if values.get("device_name"):
        return "name:" + values["device_name"].lower()
    return f"port:{normalize_switch(values.get('switch', ''))}/{normalize_port(values.get('port', ''))}"


def diff(old: list[tuple[str, dict]], new: list[tuple[str, dict]], sample: int = 50,
         fields: tuple[str, ...] | list[str] = FIELDS) -> dict:
    """Compare (key, values) lists on ``fields``. Duplicate keys are compared in order."""
    def index(rows):
        out, seen = {}, {}
        for key, values in rows:
            n = seen.get(key, 0)
            seen[key] = n + 1
            out[f"{key}#{n}"] = values
        return out

    o, n = index(old), index(new)
    added = [k for k in n if k not in o]
    removed = [k for k in o if k not in n]
    changed = []
    for k in n.keys() & o.keys():
        diffs = [f for f in fields if (o[k].get(f) or "") != (n[k].get(f) or "")]
        if diffs:
            changed.append((k, diffs))

    def label(values):
        return values.get("device_name") or values.get("mac") or \
            f"{values.get('switch')} {values.get('port')}"

    return {
        "added": len(added), "removed": len(removed), "changed": len(changed),
        "unchanged": len(n) - len(added) - len(changed),
        "added_sample": [label(n[k]) for k in added[:sample]],
        "removed_sample": [label(o[k]) for k in removed[:sample]],
        "changed_sample": [{"row": label(n[k]), "fields": f,
                            "before": {x: o[k].get(x, "") for x in f},
                            "after": {x: n[k].get(x, "") for x in f}}
                           for k, f in sorted(changed)[:sample]],
    }
