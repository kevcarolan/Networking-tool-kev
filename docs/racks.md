# Site layout and rack elevations

Each site has a **layout**: its buildings, the floors in each building, and the rooms on each
floor (or straight in a building that has no floors). The racks in a room are drawn as
**rack elevations**, built from what the inventory says about each item. Move an item in
the picture and the inventory is updated; change the inventory and the picture follows.

Open it from **Sites**: click a site's name. Site names and Rack values on other pages
link here too, and an item's form has **Show in its rack** (or **Show the rack**).

## The layout

On the left of a site's page is its tree: the site, its buildings, floors and rooms, with
how many items and racks are in each. Click any of them to see the racks there.

* **+ building**, **+ floor**, **+ room**, **✎** (rename) and **✕** (delete) appear on a
  place when you point at it (*Devices and credentials: manage*).
* An item is in a place when its **Building**, **Floor** and **Room** (in the inventory)
  are the place's names, in any case. Its **Site** says which site.
* An item in a rack is wherever its rack is.
* **Renaming** a building, floor or room changes that value on the items there.
* **Deleting** one removes it (and what's inside it) from the layout only: items keep their
  values and show as *not in the layout*.
* When items use a building, floor or room that isn't in the tree, the page lists them:
  **Add them** builds the tree from the inventory. That's the quickest way to start:
  import the inventory with Building, Floor and Room filled in, then click **Add them**.

## Racks

A rack is an inventory item of type **rack**. Its **Height (U)** is its size (42U is drawn
when it's empty). An item is in the rack when its **Rack** is the rack's name, at the same
site. Each rack shows:

* the **front** and the **rear**, U1 at the bottom;
* each item from its **Position (U)** (its lowest U) up its **Height (U)**:
  * **Depth** *full* (the default) fills the U at the front and the rear (seen dashed from
    the other side); *half* only fills its **Rack face** (*front* or *rear*), so a
    half-depth patch panel at the front and another at the rear can share a U;
  * **Height 0** is a zero-U item (a vertical PDU), drawn beside the rack;
* items in the rack with no position, below it;
* U used and U free, and any **problems**: two items in the same space, an item past the top
  of the rack, an item or rack with no height (drawn as 1U and 42U).

Colours: red, backup failing; an orange edge, firmware behind; a grey edge, inventory only.
Click an item to open its form (backups and logs from there).

### Moving things (*Devices and credentials: manage*)

* **Drag** an item to a new U on the front or rear of any rack on the page. Where you drop
  the part you picked up is where it goes.
* A move that would overlap another item or go past the top of the rack is refused, with
  the reason.
* Drag an item to *In the rack, not placed* to keep it in the rack without a position, or to
  *Here, not in a rack* to take it out.
* A moved item gets the rack's site, building, floor and room, so the inventory says where
  it is. Each move is in the activity report.
* **+ Add a rack here** (in a room) adds a rack item there. Racks that items name but that
  aren't in the inventory are listed with an **Add** button.
* Renaming a rack, or changing its building, floor or room, carries its items with it.

**Print** prints the racks shown (without the menus), for site visits and change requests.

## Later

Site plans: a floor plan picture per floor, with the rooms marked on it and clicked into.
