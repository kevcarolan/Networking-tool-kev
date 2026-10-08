# Software licence agreement: DRAFT

> **Draft for discussion only. This is not legal advice.** It is a starting point that
> matches how the software works today (yearly licences priced by number of devices, a
> 60-day trial, installed on the customer's own servers). **Have a solicitor review it**
> for the country you sell in before anyone signs it. Words in [square brackets] need to be
> filled in or decided.

---

**Between:** [Licensor legal name], [address] ("we", "us")
**and:** the customer named in the order ("you").

## 1. Definitions

* **Software:** [Product name], the network operations platform, in object and source
  form as we supply it, including updates we provide, its documentation, and the
  installer.
* **Order:** the quote, order form or invoice that names you, the licence term, the number
  of devices and the fee.
* **Licence key:** the signed licence text we issue for the Order.
* **Device:** a network device (switch, router, firewall, controller or similar) entered
  in the Software's inventory.
* **Installation:** one running server instance of the Software, identified by its
  installation ID.

## 2. Licence

2.1 Subject to this agreement and payment of the fees, we grant you a non-exclusive,
non-transferable licence. It lets you install and use the Software, for the term in the
Order, on [one Installation / the number of Installations in the Order], to manage up to
the number of Devices in the Order, for your own internal business purposes.

2.2 **Trial.** A new Installation may be used for 60 days without a licence key, to
evaluate the Software. Trial use is "as is" (clause 8.3), and only for evaluation.

2.3 **Copies.** You may make copies needed for installation, backup, disaster recovery and
testing (for example a lab or standby server that manages no production Devices).

2.4 **Contractors.** Your contractors may use the Software on your behalf. You are
responsible for their use.

## 3. Restrictions

You must not, except as the law expressly allows:

* (a) sell, rent, sublicense or provide the Software to third parties, or use it to
  provide managed services to third parties, [unless the Order allows this];
* (b) remove or get around the licence checks, or alter licence keys;
* (c) use the Software for more Devices or Installations than the Order allows;
* (d) remove proprietary notices.

[Decide: may customers modify the source code for their own use? If yes, say so here and
that support doesn't cover modified copies.]

## 4. What happens when the term ends

4.1 When the licence term ends without renewal, the Software stops allowing new devices
and new upgrade jobs. Config backups, version checks, viewing and access to your data
continue, so that your network is not left without backups. Nothing is deleted.

4.2 Your rights to use the Software for production purposes end with the term, except to
export your data. [Decide: how long after expiry may the customer keep running backups?]

## 5. Your data

5.1 The Software runs on your servers. We do not receive your device configurations,
credentials, circuit lists or any other data. The Software sends nothing to us: no
telemetry, no licence check over the network.

5.2 You are responsible for:
* the security of the server, including following the hardening guide;
* backing up the server and the encryption key;
* who you give access to.

5.3 If you send us data for support (for example logs or device output), we will use it
only to give that support, keep it confidential, and delete it when the support case is
closed. [Add: data-protection terms (for example a GDPR processing agreement) if support
data may contain personal data.]

## 6. Support and updates

6.1 During the term we will provide [updates and fixes] and [support by email, during
business hours, with the response targets in the Order]. [Or: support is a separate
agreement.]

6.2 We support the current release and the [one] before it, on the operating system
versions named in the documentation.

## 7. Network changes are your responsibility

7.1 The Software can change network devices (copy files, change boot settings, reload,
install firmware), but **only when your users tell it to**. It is designed with dry runs,
pre-checks, change windows and confirmations, but you remain responsible for:

* testing each platform and upgrade path in a lab before live use, as described in the
  documentation, and deciding which platforms may run live upgrades;
* your change management: approvals, maintenance windows and roll-back plans;
* checking firmware images and their checksums, which you obtain from the device vendors
  under their own terms;
* reviewing and acting on check results and overrides.

7.2 Firmware images and device software are third-party products, licensed to you by
their vendors. Nothing in this agreement licenses them.

## 8. Warranty

8.1 We warrant that, for [90 days] from delivery, the Software will perform substantially
as described in its documentation. If it doesn't, and you tell us within that time, we
will at our option fix it, replace it, or refund the fees paid for the affected Software.
This is your only remedy under this warranty.

8.2 We do not warrant that the Software is error-free, or that it will work with every
device, software version or configuration.

8.3 Except as stated in 8.1, and to the extent the law allows, the Software is provided
"as is", without other warranties, express or implied, including fitness for a particular
purpose.

## 9. Liability

9.1 Nothing limits liability for death or personal injury caused by negligence, for fraud,
or for anything that cannot be limited by law.

9.2 Subject to 9.1, neither party is liable for:
* loss of profit, revenue, business or data;
* network outages, or the cost of restoring service;
* any indirect or consequential loss.

9.3 Subject to 9.1, each party's total liability under this agreement is limited to [the
fees paid in the 12 months before the claim].

## 10. Intellectual property

The Software is licensed, not sold. We (and our licensors) keep all rights in it.
Feedback you give may be used by us freely.

## 11. Open-source components

The Software includes open-source components, each under its own licence. The list of
components and versions is in each release's `MANIFEST.txt`. Their licence texts are in
the installed release.

Nothing in this agreement limits your rights under those licences. In particular, you may
replace the components licensed under the LGPL (ldap3, paramiko, scp) with modified
versions.

## 12. Term and termination

12.1 This agreement lasts for the term in the Order, and renews [as set out in the
Order].

12.2 Either party may end it by notice if the other materially breaches it and doesn't fix
the breach within 30 days of being told.

12.3 On termination you must stop using the Software, except to export your data within
[30] days. Clauses 5, 7, 9, 10 and 13 survive.

## 13. General

* **Confidentiality:** each party keeps the other's confidential information confidential.
* **Export:** you will comply with export-control laws that apply to the Software.
* **Assignment:** you may not assign this agreement without our consent, which we will not
  unreasonably refuse in a merger or sale of your business.
* **Entire agreement:** this agreement and the Order are the whole agreement. If they
  conflict, the Order wins.
* **Governing law:** [the laws of …] and the courts of [...].

---

## Notes for the owner (not part of the agreement)

* **Things to decide:**
  * per-Installation or per-site licensing (2.1);
  * whether managed-service providers can use it for their customers (3(a));
  * whether source changes are allowed (3);
  * the support terms (6);
  * the warranty period (8.1);
  * the liability cap (9.3);
  * the governing law.
* **Open-source licences checked for this release:**
  * Almost all components are permissive (MIT, BSD, Apache-2.0).
  * ldap3 (LGPL-3.0), paramiko and scp (LGPL-2.1) and certifi (MPL-2.0) allow use in
    commercial software, provided:
    * they are shipped unmodified, as separate packages (which the install does);
    * their licences are included;
    * customers can replace them.
  * There are no GPL components. Check again when dependencies change: `MANIFEST.txt`
    lists them, and `pip show <package>` gives each one's licence.
* The licence check is a deterrent, not a lock: someone with root on the server could
  change the code. Clause 3(b) is what makes that a breach.
