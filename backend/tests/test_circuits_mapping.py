"""Any spreadsheet layout: when the headers aren't known, the person says which column is
which, and the layout is remembered for the next upload."""

import json

from tests.test_circuits import _upload, switch  # noqa: F401 - fixture

OTHER = (b"Asset register export\n"
         b"Asset,Mac,Switch Name,Interface,Location,Owner\n"
         b"CAM-01,00:11:22:33:44:01,SITEA-ACC-SW01,Gi1/0/5,Car park,Security\n"
         b"CAM-02,00:11:22:33:44:02,SITEA-ACC-SW01,Gi1/0/6,Lobby,Security\n")
MAP = {"sheet": "", "header_row": 1,
       "columns": {"0": "device_name", "1": "mac", "2": "switch", "3": "port", "4": "room",
                   "5": "ignore"}}


def _send(client, data, mapping=None, save=False, filename="assets.csv"):
    params = {"filename": filename}
    if mapping is not None:
        params["map"] = json.dumps(mapping)
    if save:
        params["save"] = "true"
    return client.put("/api/circuits/imports/upload", params=params, content=data)


def test_unknown_layout_asks_for_the_columns(admin):
    r = _send(admin, OTHER)
    assert r.status_code == 200
    body = r.json()
    assert body["needs_mapping"] is True
    sheet = body["sheets"][0]
    assert sheet["rows"][1][:3] == ["Asset", "Mac", "Switch Name"]
    assert sheet["guess"]["header_row"] == 1
    assert sheet["guess"]["columns"] == {"0": "device_name", "1": "mac", "2": "switch", "3": "port",
                                         "4": "room"}  # common names are recognised
    assert any(f["key"] == "device_name" for f in body["fields"])


def test_mapping_reads_rows_and_is_remembered(admin, switch):  # noqa: F811
    r = _send(admin, OTHER, MAP, save=True)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["row_count"] == 2 and imp["summary"]["header_row"] == 2
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")
    rows = admin.get("/api/circuits").json()["circuits"]
    assert [(c["device_name"], c["mac"], c["port"], c["room"]) for c in rows] == [
        ("CAM-01", "00:11:22:33:44:01", "Gi1/0/5", "Car park"),
        ("CAM-02", "00:11:22:33:44:02", "Gi1/0/6", "Lobby")]
    assert rows[0]["switch_device_id"] == switch["id"]

    layouts = admin.get("/api/circuits/column-maps").json()
    assert len(layouts) == 1 and layouts[0]["name"] == "assets.csv"
    assert {c["header"]: c["field"] for c in layouts[0]["columns"]}["Mac"] == "mac"

    # the same layout again (other rows, header case and spacing differ): no question asked
    again = OTHER.replace(b"Switch Name", b"switch  name").replace(b"CAM-02", b"CAM-03")
    r = _send(admin, again)
    assert r.status_code == 201 and r.json()["row_count"] == 2

    assert admin.delete(f"/api/circuits/column-maps/{layouts[0]['id']}").status_code == 204
    assert _send(admin, again).json()["needs_mapping"] is True


def test_mapping_must_find_devices_and_be_consistent(admin):
    no_address = {**MAP, "columns": {"0": "device_name", "2": "switch"}}
    r = _send(admin, OTHER, no_address)
    assert r.status_code == 422 and "MAC" in r.json()["detail"]
    twice = {**MAP, "columns": {"0": "mac", "1": "mac"}}
    assert _send(admin, OTHER, twice).status_code == 422
    assert _send(admin, OTHER, {**MAP, "columns": {"1": "nonsense"}}).status_code == 422
    assert _send(admin, OTHER, {**MAP, "header_row": 40}).status_code == 422
    r = admin.put("/api/circuits/imports/upload", params={"filename": "a.csv", "map": "{bad"},
                  content=OTHER)
    assert r.status_code == 422


def test_a_custom_column_can_be_chosen(admin):
    admin.post("/api/circuits/fields", json={"label": "Owner"})
    m = {**MAP, "columns": {**MAP["columns"], "5": "x_owner"}}
    imp = _send(admin, OTHER, m).json()
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")
    assert admin.get("/api/circuits").json()["circuits"][0]["x_owner"] == "Security"


def test_workbook_sheet_is_chosen(admin):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Cover"
    wb.active.append(["Nothing here"])
    ws = wb.create_sheet("Kit")
    ws.append(["Tag", "Hardware"])
    ws.append(["PRN-1", "0080.77a1.0b01"])
    buf = io.BytesIO()
    wb.save(buf)
    body = _send(admin, buf.getvalue(), filename="kit.xlsx").json()
    assert [s["name"] for s in body["sheets"]] == ["Cover", "Kit"]
    r = _send(admin, buf.getvalue(), {"sheet": "Kit", "header_row": 0,
                                      "columns": {"0": "device_name", "1": "mac"}},
              filename="kit.xlsx")
    assert r.status_code == 201 and r.json()["sheet"] == "Kit"


def test_layouts_need_manage(client, app, admin):
    from app.core.auth import VIEWER, User

    app.state.authenticator.authenticate = lambda u, p: User(username=u, role=VIEWER)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "v", "password": "x"})
    assert client.get("/api/circuits/column-maps").status_code == 200
    assert client.delete("/api/circuits/column-maps/1").status_code == 403
    assert _send(client, OTHER).status_code == 403
