# Branding

**Name: NetCairn** (owner's choice, 2026-10-14). A cairn is the pile of stones that marks
the way on a hill so nobody gets lost: the product does that for a network (what's where,
how it connects, what changed). Not final until the trademark check is done (see the end).
The owner is buying **netcairn.ie** (.ie and .co.uk were free on 2026-10-14).

The name is one setting, `NETOPS_PRODUCT_NAME`, whose default is now NetCairn; a customer can
still show their own name. Internal names (the `netops` service and account, `NETOPS_`
settings, `/etc/netops`, `netops-cli`) are unchanged: renaming them needs a careful upgrade
path for installed servers, so it waits until the name is cleared.

## The logo

| File | Use |
|---|---|
| `netcairn-mark.svg` | The mark alone. The product's `favicon.svg` (browser tab, sign-in page, top bar) and the wall display's `mark.svg` are copies of it without the name. |
| `netcairn-logo.svg` | Mark + name + strapline, on light backgrounds (website, documents, reports). |
| `netcairn-logo-dark.svg` | The same on dark navy (slides, dark pages). |
| `preview.png` | All of them, the mark at 16, 32, 64 and 160 px. |

The mark is a cairn of four stones with the top stone lit, and an amber trail linking a
point on each stone, like a path through a network.

* Colours: navy `#1b2a4a` (stones, "Net"), amber `#d98a00` on light / `#ffc24a` on dark
  ("Cairn", the top stone and the trail `#ffbd3d`), strapline grey `#5b6478`.
* Type: Inter (free, SIL Open Font Licence), bold for the name. The SVGs fall back to
  Segoe UI / Helvetica / Arial; for print, convert the text to outlines first.
* Strapline: *Every network, mapped and kept.*

Drafts: good enough to use now; a designer can refine them before a launch.

## Name check (web, 2026-10-14)

Nothing called **NetLantern** or **NetSteward** came up as a trademark, but both have
neighbours in the same field. A trademark attorney should judge them.

**NetLantern**
* **LANtern** by Spectrum (Spectrum Communications, UK): a network monitoring service
  (on-site probe, cloud dashboards, SNMP, syslog, ping, VoIP quality), launched in 2023
  ([lanterntech.co.uk](https://lanterntech.co.uk/),
  [spectrum-coms.co.uk](https://spectrum-coms.co.uk/products/lantern/)). The same field
  and market, and a similar-sounding name: **the main risk**.
* Lantern (lantern.io): a well-known censorship-circumvention VPN. A different field.
* Small open-source projects: *network-lantern* (diagnostics toolkit, GitHub) and *lantern*
  (network mapping, Go). Low risk.
* LANTERN trademark of The Lantern Group, LLC (US, cannabis-information software): a
  different field.
* Novell's 1990s LANtern network monitor: long gone.
* Owner: a `.ie` domain is free.

**NetSteward**
* **NetSteward** by Network Stewards (Pearland, Texas): a web-based network monitoring and
  management platform for building your own NOC (auto-discovery, configuration auditing,
  ticketing), founded 2010, about one employee
  ([networkstewards.com](http://www.networkstewards.com/monitor.html)). **The exact name in
  the same field.** It may be dormant, but a prior user of the exact name is the bigger risk.
* ZoomInfo also lists a "NetSteward" monitoring tool under Falcon Peak Networks (perhaps the
  same product).
* IANA lists `netsteward` (port 2810) and `net-steward` (port 2128) as port names: not
  trademarks, but they show the name has been used in networking before.
* A developer's handle (@netsteward) and a personal website (netsteward.net): low risk.

**So:** NetLantern looks the safer of the two (similar name in the field, not the exact one),
but neither is clear. Next: the UK IPO, EUIPO and USPTO registers in classes 9 and 42, the
.ie/.com/.co.uk domains, then a trademark attorney's clearance search, before spending
on a logo or registering a company name.

## Other names (web check, 2026-10-14)

The owner ruled out NetSteward (the exact name is a US network-monitoring product) and
NetLantern (too close to Spectrum's LANtern). Fresh names, searched for software, network
products, trademarks and companies:

| Name | Idea | Found |
|---|---|---|
| **Netcairn** | a cairn is the pile of stones that marks the way on a hill: the network's landmarks, so nobody gets lost | nothing at all (only CAIRN, a US research network that closed in 2001, and CAIRN trademarks for clothing and a hiking app) |
| **NetKeel** | the keel keeps a boat steady: backups, safe upgrades, nothing drifting | nothing (Keel Marine and Keela are other fields) |
| **Netquay** | a quay: where everything is moored and tied up | an Australian NETQUAY PTY LTD in an insolvency list (likely closed); nothing in software |
| **Linkhaven** | a safe harbour for the links | UK property companies (Linkhaven Ltd, Salford), so a UK company of that name can't be registered |
| NetFathom | understanding the network's depths | nothing as "NetFathom", but "Fathom" is a busy brand (finance and web-analytics software) |
| Halyard | the rope that raises the sail | no software, but Halyard Health is a large medical brand |
| Portlight | lights up the ports | **avoid**: a homelab dashboard of the same name shows which ports are in use |
| Netloom | weaves it together | a network traffic tool called *loom* (Go, 2026) is close |

Best: **Netcairn**, then **NetKeel**. The owner chose **NetCairn** (2026-10-14). It still
needs the registers and an attorney's search.
