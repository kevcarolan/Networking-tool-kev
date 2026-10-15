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

## Put it on the web host

The site is plain files, so any host works.

On a cPanel-style host (as for the other site):

1. **Add the domain.** Add `netcairn.ie` to the hosting account as an **addon domain**. Point the domain's DNS at the host, as the host's instructions say.
2. **Switch on HTTPS.** Turn on the free certificate for the domain. In cPanel this is **SSL/TLS Status** or **Let's Encrypt**.
3. **Upload the site.** Upload **everything inside** `website/public/` into the domain's folder, using **File Manager** or FTP.
   * Include the hidden `.htaccess` file. It forces HTTPS, adds the security headers and sets the "page not found" page.
   * In File Manager, choose *Settings › Show hidden files* to see it.
4. **Check it.** Open `https://netcairn.ie` and click through every page.

To update the site: change, build, and upload `public/` again, replacing the old files.

## Before it goes live

- [ ] `email` in `site.json` is a real mailbox that someone reads (currently `hello@netcairn.ie`)
- [ ] `company`: the registered company name, once there is one
- [ ] Prices in `site.json`, or leave them as "Ask us"
- [ ] Stripe Payment Links, one per edition and band, if customers should be able to buy online
- [ ] A solicitor has checked `privacy.html` (and the EULA it will link to)
- [ ] The trademark check on the name is done (docs/branding/README.md)
