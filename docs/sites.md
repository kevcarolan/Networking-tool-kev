# Sites

The **Sites** page is the list of your sites: data centres, offices, campuses, branches,
warehouses, remote cabinets... For each one it shows what the inventory has there.

## How items and devices belong to a site

An inventory row (and so a device) is **at a site** when its *Site* is the site's **name**
or its **site code**, in upper or lower case. A device's site comes from Config backups
unless someone typed a different one on its inventory row.

* Give each site a short **site code** (e.g. `DC1`, `HQ`) and use either the code or the
  name on items and devices.
* Names and codes are unique across the list, so a *Site* value always means one site.
* **Renaming** a site, or changing its code, changes the *Site* on the items, devices and
  the live circuit list that used the old value, so nothing loses its site. The activity report says how many.
* **Deleting** a site only removes it from this list: items keep their *Site* value.

When the inventory uses a site that isn't on the list, the page says so above the table.
**Add them to the list** adds them all (as *live*), and you fill in the details after.

## The page

* Tiles: sites, live sites, items at a site, managed devices, backups failing.
* Search any column, filter by type, region and status.
* Counts per site: **Items**, **Managed devices**, **Backups failing**, **Firmware behind**
  and **Circuits** (backups, firmware and circuits only count when those tools are
  licensed). How a circuit gets its site: [circuits.md](circuits.md#which-site-a-circuit-is-at). Click a count or a name to open the
  site: its details, and a table of everything at the site with its backup and firmware
  state and buttons to its backups and logs. Click an item to open it in the Inventory.

## Linked everywhere

A Site value that is on the list is a link to its site on every page: **Config backups**,
**Firmware**, **Inventory** and **Circuits**. The **Circuits** count, and **Circuits at
this site** in the site view, open the Circuits page filtered to that site.

## The columns

| Group | Columns |
|---|---|
| Site | Name, Site code, Type (data centre, office, campus, branch, warehouse, factory, colocation, remote cabinet, other), Status (live, planned, being built, closing, closed), Region |
| Address | Address, Town / city, Postcode, Country |
| Contact | Site contact, Phone, Email |
| Other | Access and opening hours, WAN / internet circuits, Notes |

* **Columns** (everyone): tick and order the columns you see, including the counts.
  Remembered for you, in your browser.
* **Custom columns** (admins): text, number, date or pick-list, for everyone. They are in
  the site form, **Columns**, imports, exports and the blank template.

## Spreadsheets

* **CSV** / **Excel**: every column, custom ones too, and the counts.
* **Blank template**: the column names only, as CSV or Excel, for **the columns I see** or
  **every column** (*Name* is always in it). The Excel version has pick-lists for *Type*,
  *Status* and pick-list custom columns, and a sheet on how to fill it in.
* **Import** (Excel or CSV, names in the first row): shows what would change first. Rows
  are matched to the list by **site code**, then **name**; anything else is added. Empty
  cells leave a value as it is. A file with errors isn't imported. The counts columns of an
  export are ignored, so an export imported back changes nothing.

## Who can do what

Sites use the *Devices and credentials* permission, like the inventory:

| Level | Sites |
|---|---|
| view | See the list and what's at each site, choose columns, export |
| manage | Add, change, delete and import sites |

Adding custom columns needs an **admin**. Sites are part of every licence. Every change is
in the activity report.
