#!/usr/bin/env python3
"""Builds the website into website/public/, ready to upload to the web host.

    python3 website/build.py

Each page in src/ starts with two comment lines, its title and its description:

    <!-- title: Pricing -->
    <!-- description: Editions and prices, per device per year. -->

and is put between src/_header.html and src/_footer.html. In any of them, {{name}} is a
value from site.json ({{email}}, {{domain}}...), {{page}} the page's file name, and
{{pricing_table}} the price table made from site.json. Anything left in {{ }} stops the
build, so a typo never reaches the live site. Only the Python standard library is used.
"""

import html
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, OUT = HERE / "src", HERE / "public"
META = re.compile(r"\A\s*<!--\s*title:\s*(.*?)\s*-->\s*<!--\s*description:\s*(.*?)\s*-->\s*", re.S)
EDITIONS = [
    ("essentials", "Essentials", "Backups, compliance, syslog, inventory, sites and racks"),
    ("professional", "Professional", "Essentials, plus firmware, upgrade jobs and circuits"),
    ("complete", "Complete", "Everything, monitoring included"),
]
BAND_NAMES = {"50": "Up to 50 devices", "250": "Up to 250", "1000": "Up to 1,000", "unlimited": "Unlimited"}


def money(site: dict, value) -> str:
    if value is None:
        return '<span class="ask">Ask us</span>'
    return f'{html.escape(site["currency"])}{value:,}<small> / device / year</small>' if isinstance(
        value, (int, float)) else html.escape(str(value))


def pricing_table(site: dict) -> str:
    bands = site["bands"]
    head = "".join(f"<th scope=\"col\">{BAND_NAMES.get(b, b)}</th>" for b in bands)
    rows = []
    for key, name, what in EDITIONS + [("monitoring", "Monitoring add-on", "Adds monitoring to Essentials or Professional")]:
        cells = []
        for b in bands:
            price = money(site, site["prices"].get(key, {}).get(b))
            link = site.get("stripe_links", {}).get(key, {}).get(b)
            buy = f'<a class="buy" href="{html.escape(link)}">Buy</a>' if link else ""
            cells.append(f"<td>{price}{buy}</td>")
        rows.append(f'<tr><th scope="row"><b>{name}</b><span>{what}</span></th>{"".join(cells)}</tr>')
    return (f'<div class="table-wrap"><table class="prices"><thead><tr><th scope="col">Edition</th>{head}'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def fill(text: str, values: dict, where: str) -> str:
    def one(m):
        key = m.group(1)
        if key not in values:
            raise SystemExit(f"{where}: unknown {{{{{key}}}}}")
        return str(values[key])
    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", one, text)


def build() -> list[str]:
    site = json.loads((HERE / "site.json").read_text(encoding="utf-8"))
    header = (SRC / "_header.html").read_text(encoding="utf-8")
    footer = (SRC / "_footer.html").read_text(encoding="utf-8")
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(HERE / "assets", OUT / "assets")
    made = []
    for page in sorted(SRC.glob("[!_]*.html")):
        text = page.read_text(encoding="utf-8")
        m = META.match(text)
        if not m:
            raise SystemExit(f"{page.name}: start with <!-- title: ... --> and <!-- description: ... -->")
        values = {k: v for k, v in site.items() if isinstance(v, str)}
        values.update(title=m.group(1), description=m.group(2), page=page.name,
                      pricing_table=pricing_table(site))
        out = fill(header + text[m.end():] + footer, values, page.name)
        # The current page's menu link is marked for screen readers and the styles.
        out = out.replace(f'href="{page.name}"', f'href="{page.name}" aria-current="page"', 1) \
            if page.name != "index.html" else out
        (OUT / page.name).write_text(out, encoding="utf-8")
        made.append(page.name)
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site['base_url']}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{site['base_url']}/{'' if p == 'index.html' else p}</loc></url>"
                   for p in made if p != "404.html")
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns='
                                     f'"http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    shutil.copy(HERE / "htaccess", OUT / ".htaccess")
    return made


if __name__ == "__main__":
    pages = build()
    print(f"Built {len(pages)} pages into {OUT}: {', '.join(pages)}")
