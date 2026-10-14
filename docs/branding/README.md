# Branding (draft)

**Working name: NetLantern** (owner's choice, 2026-10-14). Not final until the trademark
check below is done. The name is one setting, `NETOPS_PRODUCT_NAME`; the demo uses
NetLantern (`app/demo/seed.py`, `PRODUCT_NAME`).

## The logo

| File | Use |
|---|---|
| `netlantern-mark.svg` | The mark alone: favicon, app icon, wall display corner. Reads at 16 px. |
| `netlantern-logo.svg` | Mark + name + strapline, on light backgrounds (sign-in page, reports, documents). |
| `netlantern-logo-dark.svg` | The same on the dark navy (dark mode, slides, the wall display). |

The mark is a lantern whose light is a small network: four devices and five links,
"see your whole network". It is drawn with plain shapes, so it prints in one colour too
(all navy, the glass left white).

* Colours: navy `#1b2a4a` (frame, "Net"), amber `#d98a00` on light / `#ffc24a` on dark
  ("Lantern"), glow `#fff1c4` → `#ffbd3d`, strapline grey `#5b6478`.
* Type: Inter (free, SIL Open Font Licence), bold for the name. The SVGs fall back to
  Segoe UI / Helvetica / Arial; for print, convert the text to outlines first.
* Strapline: *See your whole network.*

`preview.png` shows them all: the mark at 16, 32, 64 and 160 px, then both logos.

These are drafts to judge the idea. A designer can refine them once the name is cleared.

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

Best: **Netcairn**, then **NetKeel**. Both still need the registers, the domains and an
attorney's search.
