"""Uploading a file that updates the circuit list instead of replacing it."""

from app.tools.circuits.api import merge_rows
from app.tools.circuits.importer import parse_csv
from tests.test_circuits import ROWS, _upload, make_xlsx, switch  # noqa: F401 - fixture


def _update(client, data, filename="changes.csv"):
    return client.put("/api/circuits/imports/upload",
                      params={"filename": filename, "mode": "update"}, content=data)


def _live(admin, rows=ROWS):
    imp = _upload(admin, make_xlsx(rows=rows)).json()
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")


def test_update_changes_adds_and_keeps(admin, switch):  # noqa: F811
    _live(admin)
    # one row changed (by MAC), one new row; the other four aren't in the file
    data = (b"Hardware Mac Address,Device Name,PORT,Room / Area\n"
            b"02:00:5e:10:c0:2f,,Gi2/0/20,New room\n"
            b"02:00:5e:aa:bb:cc,NEW-CAM-01,Gi1/0/9,\n")
    r = _update(admin, data)
    assert r.status_code == 201, r.text
    imp = r.json()
    s = imp["summary"]
    assert s["update"]["updated"] == 1 and s["update"]["added"] == 1 and s["update"]["kept"] == 4
    assert s["diff"]["removed"] == 0 and s["diff"]["added"] == 1 and s["diff"]["changed"] == 1
    assert imp["row_count"] == 6
    admin.post(f"/api/circuits/imports/{imp['id']}/commit")
    rows = {c["mac"].lower().replace(":", ""): c for c in admin.get("/api/circuits").json()["circuits"]}
    door = rows["02005e10c02f"]
    # changed where the file has a value; the empty Device Name cell kept the old name
    assert door["port"] == "Gi2/0/20" and door["room"] == "New room"
    assert door["device_name"] == "DC-SITEA-GF-03" and door["switch"] == "ACC-SW01"
    assert rows["02005eaabbcc"]["device_name"] == "NEW-CAM-01"
    assert len(rows) == 6


def test_replace_is_still_the_default(admin, switch):  # noqa: F811
    _live(admin)
    data = b"Hardware Mac Address,Device Name\n02:00:5e:10:c0:2f,ONLY-ONE\n"
    imp = _upload(admin, data, filename="one.csv").json()
    assert imp["summary"]["diff"]["removed"] == 4 and imp["summary"]["update"] is None


def test_matching_by_name_then_port():
    current = parse_csv(b"Device Name,Hardware Mac Address,DEVICE,PORT\n"
                        b"PRN-01,,SW1,Gi1/0/1\n"
                        b"PRN-02,,SW1,Gi1/0/2\n"
                        b",00:11:22:33:44:55,SW1,Gi1/0/3\n").rows
    incoming = parse_csv(b"Device Name,Hardware Mac Address,DEVICE,PORT,VLAN\n"
                         b"prn-01,aa:aa:aa:aa:aa:01,,,70\n"     # by name: gets its MAC
                         b",,SW1,Gi1/0/2,71\n"                  # by switch and port
                         b"PRN-03,00:11:22:33:44:66,SW1,Gi1/0/3,72\n").rows  # other MAC: new
    rows, updated, added = merge_rows(current, incoming, {"device_name": "", "mac": "",
                                                          "switch": "", "port": "", "vlan": ""})
    assert (updated, added) == (2, 1) and len(rows) == 4
    assert rows[0].mac_norm == "aa:aa:aa:aa:aa:01" and rows[0].values["vlan"] == "70"
    assert rows[0].values["device_name"] == "prn-01"
    assert rows[1].values["vlan"] == "71" and rows[1].values["device_name"] == "PRN-02"
    assert rows[2].values["vlan"] == "" and rows[3].values["device_name"] == "PRN-03"
    assert rows[3].row_no == max(r.row_no for r in current) + 1


def test_update_with_a_mapped_layout(admin, switch):  # noqa: F811
    import json

    _live(admin)
    data = b"Kit,Mac addr x\nDOOR-RENAMED,02:00:5e:10:c0:2f\n"
    m = {"sheet": "", "header_row": 0, "columns": {"0": "device_name", "1": "mac"}}
    r = admin.put("/api/circuits/imports/upload", params={
        "filename": "kit.csv", "mode": "update", "map": json.dumps(m)}, content=data)
    assert r.status_code == 201, r.text
    s = r.json()["summary"]
    assert s["update"]["updated"] == 1 and s["diff"]["removed"] == 0
    assert admin.put("/api/circuits/imports/upload", params={"filename": "k.csv", "mode": "merge"},
                     content=data).status_code == 422
