# Selling licences: the owner's runbook

How a customer buys, gets the software and gets their licence; where everything is kept;
renewals and upgrades. For the owner only. How licences work inside the product is in
[licensing.md](licensing.md).

## What is kept where

| What | Where | Who sees it |
|---|---|---|
| Customers, payments, invoices, VAT | **Stripe** (your account) | You |
| Every licence made: customer, contact, Stripe ID, edition, devices, end date, server | **The ledger**, `licences.csv` in your OneDrive folder `NetCairn/` (written by `licence_tool`) | You |
| The signing key | Your PC and your password vault. **Never** in OneDrive, email or the repository | You |
| The install bundles | OneDrive `NetCairn/releases/<version>/`: the `.tar.gz`, its `.sha256` and `MANIFEST.txt` | Customers, through a share link per customer |
| The licence itself | Emailed to the customer; pasted on their Settings page | The customer |

The ledger holds personal data (names and email addresses): keep the OneDrive folder
private (not shared), with two-step sign-in on the account. Customer servers never contact
you or OneDrive by themselves: the licence is checked offline, so air-gapped sites work.

## Once: set up

1. **Signing key**: `python -m app.licence_tool keygen --out ~/licence-signing.key`, put the
   public key in `backend/app/core/licence_keys.txt` and commit it ([licensing.md](licensing.md#one-time-make-the-signing-key)).
2. **OneDrive**: a folder `NetCairn/` with `releases/`. Point the tool at the ledger once:
   `export NETCAIRN_LEDGER=~/OneDrive/NetCairn/licences.csv` (on Windows, the path of your
   OneDrive folder).
3. **Stripe**: one product per edition (Essentials, Professional, Complete) and the
   Monitoring add-on, each with a yearly price per device band (50, 250, 1,000, unlimited).
   Switch on **Stripe Tax** (Irish, UK and EU VAT) and **Invoicing** (many businesses pay by
   bank transfer against an invoice or a purchase order). Payment Links work for card
   payments straight from your website or an email.

## A sale, step by step

1. **The customer tries it**: they download the latest bundle (a share link to the
   release folder) and install it. Every install has a **60-day trial** with everything on.
2. **They buy**: a Stripe Payment Link (card) or a Stripe invoice (bank transfer), for the
   edition, add-on and device band, yearly.
3. **They send their installation ID**, shown on their Settings page (it ties the licence
   to that server; leave it out only for a customer with several servers you agreed on).
4. **When Stripe shows it paid**, make the licence, with the end date one year on:

   ```bash
   python -m app.licence_tool sign --key ~/licence-signing.key \
       --customer "Acme Ltd" --edition professional --add monitoring --devices 250 \
       --expires 2027-10-31 --install-id 1CED-A204-C5AB-0B11 \
       --email it@acme.example --stripe sub_1Q2w3E --out acme-2027.lic
   ```

   It adds a line to the ledger.
5. **Email them** the `.lic` file (it isn't secret) and, if they don't have it, the share
   link to the release they should install and its SHA-256. Their admin pastes the licence
   on the Settings page.

## Downloads (OneDrive)

* **Each release**: build the bundle from its tag (`git checkout v2.1.0`, then
  `sudo deploy/airgap/build-bundle.sh` on an Ubuntu server of the release your customers use)
  and upload the `.tar.gz`, `.sha256` and `MANIFEST.txt` to `NetCairn/releases/2.1.0/`.
  Write the SHA-256 in the release notes on GitHub too.
* **Share links**: share the release folder with **people you choose** (their email
  addresses), or a link that **expires**; not "anyone with the link" without an end date.
  The customer checks the SHA-256 against the one you sent, which proves the file wasn't
  changed on the way ([install-airgap.md](install-airgap.md)).
* The customer installs the bundle the same way on a connected or an air-gapped server:
  check the checksum, unpack, run `install.sh` ([install-airgap.md](install-airgap.md)).
  (`deploy/install-online.sh`, which builds from the repository, is for your own servers.)

## Renewal

Stripe renews the yearly subscription (or you send the invoice). When it is paid:

```bash
python -m app.licence_tool ledger --customer acme          # find the licence ID
python -m app.licence_tool sign --key ~/licence-signing.key --from 3F2A91C0 \
    --expires 2028-10-31 --out acme-2028.lic
```

Everything else (edition, add-ons, devices, server, contact) comes from the ledger. Email
the new licence; pasted in, it replaces the old one. Admins see a notice 30 days before the
end date, and if a licence lapses nothing stops: only adding devices and new upgrade jobs
are blocked until the new one is pasted in.

## Upgrade (more devices, another edition, the add-on)

Change the subscription in Stripe (it charges the difference for the rest of the year),
then make a licence **from the old one**, keeping its end date:

```bash
python -m app.licence_tool sign --key ~/licence-signing.key --from 3F2A91C0 \
    --expires 2027-10-31 --devices 1000 --add monitoring --out acme-2027-b.lic
```

The ledger marks the old licence as replaced.

## A new server (the customer moved)

Make a licence `--from` the old one with the new `--install-id` and the same end date. The
old server keeps working until its licence ends; ask the customer to remove it.

## Your own servers

`python -m app.licence_tool sign --key ~/licence-signing.key --internal --out internal.lic`:
no end date, any number of devices, every tool. One per server, or one without
`--install-id` for all of yours. Not for resale.

## Later: a customer portal

When the number of customers grows: a small portal where a Stripe payment makes the licence
itself (the signing key kept in a key vault, not the portal's code), and customers sign in
to download their licence and the bundles. Until then, the steps above take a few minutes
per sale.
