# Network inventory

One list of everything on the network: switches, routers and firewalls, and also servers,
storage, racks, PDUs, UPSs, patch panels, cameras… whatever you want to keep track of.
Find it under **Inventory** in the top bar.

## Managed and inventory only

* **Managed** rows are the devices the tools work with (backups, firmware, upgrades,
  syslog). Every device added on Config backups appears here by itself. If the inventory
  already has an item with the same name or management address, the device is linked
  to it, so importing your inventory first and adding devices later works.
* **Inventory only** rows are just recorded. **Manage this device…** (in an item's form,
  for users with *Devices and credentials: addresses*) asks for the platform, the
  management address and the login, and turns it into a managed device.
* **Only managed devices count towards the licence.** Record as much as you like.
* Managed rows show their backup state and firmware compliance, with **Backups** (history
  and configs) and **Logs** (syslog) buttons.
* For managed rows, the **model, serial number, software version, manufacturer, platform,
  address and site come from the device itself** (shown in grey) wherever you haven't
  typed something. What you type always wins.
* A managed device is renamed or deleted on **Config backups**. When a device is deleted
  there, its inventory row stays, as inventory only.

## The columns

| Group | Columns |
|---|---|
| Identity | Name, Type, Role, Manufacturer, Model, Serial number, Asset tag |
| Software | OS / platform, Version |
| Network | Management IP, Management VLAN, MAC address |
| Location | Site, Building, Floor, Room, Rack, Position (U), Height (U), Rack face (front, rear), Depth (full, half) |
| Lifecycle | Status (in service, spare, planned, faulty, retired), Purchase date, Warranty end, Support contract, End of support, Supplier |
| Other | Owner / team, Notes |

* **Columns** (everyone): tick the columns you want to see and put them in order. Your
  choice is remembered for you, in your browser. Other people keep their own.
* **Custom columns** (admins): add your own columns, as text, number, date, or a
  pick-list. They are there for everyone at this site: in the item form, in **Columns**,
  and in imports and exports. Renaming one keeps what was typed in it; deleting one
  deletes its values.

## Import and export

* **CSV** and **Excel** export every column, including custom ones, and say which rows
  are managed. Exports are safe to open in Excel.
* **Import** (*Devices and credentials: manage*) takes an Excel (.xlsx) or CSV file with
  the column names in the first row, the same names as in an export.
  1. It shows what would happen first: new items, items to update (with the columns that
     change), and rows with errors. Nothing changes until you press **Import**.
  2. Rows are matched to the inventory by **serial number**, then **asset tag**, then
     **name**. Anything not matched is added. Empty cells leave a value as it is.
  3. A file with errors isn't imported: fix the rows it lists and choose the file again.
  4. Columns it doesn't know are listed. An admin can add them as custom columns first.
* An export imported back changes nothing, so you can export, edit in Excel and import.
* **Blank template** gives a sheet with only the column names, as CSV or Excel: **the
  columns I see** or **every column**. *Name* is always in it. The Excel version has
  pick-lists for *Type*, *Status* and pick-list custom columns, and a second sheet on how
  to fill it in. Fill it in and **Import** it.

## Racks

Rack, Position (U), Height (U), Rack face and Depth draw the rack elevations on each site's
page ([racks.md](racks.md)). A Rack value is a link to its rack, and the form has **Show in
its rack**. A height of 0 is a zero-U item, such as a vertical PDU.

## Sites

The **Sites** page lists the sites themselves (data centres, offices, branches...). An item
is at a site when its *Site* is the site's **name or code**. See [sites.md](sites.md). In
the item form, *Site* suggests the names on the site list.

## Who can do what

The *Devices and credentials* permission (Users page):

| Level | Inventory |
|---|---|
| view | See the inventory, choose columns, export |
| manage | Add, change, delete and import items |
| addresses | Also **Manage this device…** |

Adding custom columns needs an **admin**. Every change is in the activity report.

## Later

Site plans: a floor plan picture per floor, with rooms to click into.
