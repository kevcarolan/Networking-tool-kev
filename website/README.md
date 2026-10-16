# The website

The public website: plain HTML pages with no scripts, cookies or trackers, and fonts and images served from the site itself. It isn't part of the product, and it's left out of the install bundles (`.gitattributes`).

| Page | File |
|---|---|
| Home | `src/index.html` |
| Features, with the vendor table | `src/features.html` |
| Security | `src/security.html` |
| Pricing (the price table comes from `site.json`) | `src/pricing.html` |
| Free trial | `src/trial.html` |
| Privacy (a draft until a solicitor has checked it) | `src/privacy.html` |
| Page not found | `src/404.html` |

The top and bottom of every page are `src/_header.html` and `src/_footer.html`. The styles are in `assets/site.css`.

## Change something

* **Email address, company name, prices, Stripe links:** edit `site.json`.
  * A price of `null` shows "Ask us".
  * A number such as `12` shows "€12 / device / year".
  * A Stripe Payment Link (`"https://buy.stripe.com/..."`) adds a **Buy** button under that price.
* **Text:** edit the page in `src/`. Anything in `{{ }}` comes from `site.json`, for example `{{email}}`.
* **Screenshots:** in `assets/img/`. They come from the demo (`python -m app.demo`) at 1440 px wide. Retake them when the product's look changes.

Then build:

```bash
python3 website/build.py
```

This writes the finished site to `website/public/`. That folder isn't kept in Git; build it again whenever you need it.

The build stops if a `{{ }}` name is wrong, so a typo never reaches the live site.

## Where it's hosted: Render

The site is a **Static Site** on the owner's Render account (set up 2026-10-15). Render builds it from this repository by itself, so nothing is uploaded by hand.

When a change to `website/` is merged into `main`, Render runs the build and publishes it within a couple of minutes.

| Render setting | Value |
|---|---|
| Branch | `main` |
| Root Directory | `website` |
| Build Command | `python3 build.py` |
| Publish Directory | `public` |
| Build Filters, included paths | `website/**` (product changes don't rebuild the site) |
| Headers, path `/*` | `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, with the values in `htaccess` |
| Custom domains | `netcairn.ie` and `www.netcairn.ie`, using the DNS records Render shows; Render issues the HTTPS certificate |

Render ignores `.htaccess`. The file is kept for any Apache-based host (cPanel and similar) the site might move to: upload `public/`, including the hidden `.htaccess`.

## Before it goes live

- [ ] `email` in `site.json` is a real mailbox that someone reads (currently `hello@netcairn.ie`)
- [ ] `company`: the registered company name, once there is one
- [ ] Prices in `site.json`, or leave them as "Ask us"
- [ ] Stripe Payment Links, one per edition and band, if customers should be able to buy online
- [ ] A solicitor has checked `privacy.html` (and the EULA it will link to)
- [ ] The trademark check on the name is done (docs/branding/README.md)
