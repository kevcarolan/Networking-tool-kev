// Browser frontend (plain JavaScript, no build step).
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  user: null,
  rows: [],
  platforms: [],
  credentials: [],
  view: "backups",
  refreshTimer: null,
  detailDevice: null,
};

// ---------- helpers ----------

/** Create an element: h("td", {class: "x"}, "text", childNode, ...) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

async function api(path, options = {}) {
  const opts = { credentials: "same-origin", headers: {}, ...options };
  if (opts.body !== undefined && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && path !== "/api/auth/login") {
    showLogin();
    throw new Error("Session expired - please sign in again");
  }
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = data && data.detail !== undefined ? data.detail : data;
    if (Array.isArray(msg)) msg = msg.map((e) => `${e.loc.slice(-1)[0]}: ${e.msg}`).join("; ");
    throw new Error(msg || res.statusText);
  }
  return data;
}

function fmtTime(value) {
  if (!value) return "—";
  const d = new Date(value.endsWith("Z") || value.includes("+") ? value : value + "Z");
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function fmtAgo(value) {
  if (!value) return "never";
  const d = new Date(value.endsWith("Z") || value.includes("+") ? value : value + "Z");
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} days ago`;
}

function fmtFreq(mins) {
  const named = { 15: "15 min", 60: "Hourly", 240: "4 hours", 720: "12 hours", 1440: "Daily", 10080: "Weekly" };
  if (named[mins]) return named[mins];
  return mins % 1440 === 0 ? `${mins / 1440} days` : mins % 60 === 0 ? `${mins / 60} hours` : `${mins} min`;
}

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 4000);
}

const isAdmin = () => state.user && state.user.role === "admin";
const canUpgrade = () => !!(state.user && state.user.can_upgrade);
// Permission levels per area (app/core/permissions.py): each includes the ones before it.
function can(area, level) {
  const u = state.user;
  if (!u || !u.perms || !u.levels || !u.levels[area]) return false;
  const order = u.levels[area];
  return order.indexOf(u.perms[area]) >= order.indexOf(level);
}
// data-perm="area:level" (or several, separated by |: any one is enough)
const permitted = (spec) => spec.split("|").some((p) => { const [a, l] = p.split(":"); return can(a, l); });
// Tools the licence unlocks (app/core/licence.py MODULES); everything until the licence is read.
const hasModule = (m) => !state.licence || state.licence.modules.includes(m);
const VIEW_MODULE = { firmware: "firmware", circuits: "circuits", syslog: "syslog", monitoring: "monitoring" };

/** Locked tools: greyed out in the top bar, other controls of theirs hidden. */
function applyModules() {
  $$("[data-module]").forEach((el) => {
    const ok = hasModule(el.dataset.module);
    if (el.closest("#nav")) {
      el.classList.toggle("locked", !ok);
      el.title = ok ? "" : "Not in your licence";
    } else if (!ok) {
      el.hidden = true;
    }
  });
  $("#bk-unlicensed").hidden = hasModule("backups");
}

function showLocked(view) {
  const l = state.licence;
  const name = l.module_labels[VIEW_MODULE[view]];
  $("#locked-title").textContent = `${name} isn't in your licence`;
  $("#locked-text").textContent = `This tool is installed but not unlocked. Ask your supplier to add ${name} to the licence; ` +
    "an admin adds the new licence on the Settings page, and it unlocks straight away.";
  $("#locked-have").textContent = `Your licence unlocks: ${l.modules.map((m) => l.module_labels[m]).join(", ") || "no tools"}.`;
  $$(".view").forEach((s) => (s.hidden = s.id !== "view-locked"));
}

const canRunJob = (j) => canUpgrade() && (j.dry_run || can("upgrades", "live"));

// ---------- auth ----------

function showLogin() {
  state.user = null;
  clearInterval(state.refreshTimer);
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
}

async function showApp(user) {
  state.user = user;
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#whoami").textContent = `${user.display_name || user.username}${isAdmin() ? " (admin)" : ""}`;
  $("#change-password").hidden = user.source !== "local";
  $("#two-factor").hidden = !user.user_id;
  $("#site-name").textContent = user.site_name || "";
  $("#site-name").hidden = !user.site_name;
  $("#demo-banner").hidden = !user.demo;
  $("#app-version").textContent = user.version && user.version !== "dev" ? `v${user.version}` : "";
  $$("[data-admin]").forEach((el) => (el.hidden = !isAdmin()));
  $$("[data-upgrader]").forEach((el) => (el.hidden = !canUpgrade()));
  $$("[data-perm]").forEach((el) => (el.hidden = !permitted(el.dataset.perm)));
  state.platforms = await api("/api/platforms");
  state.licence = await api("/api/licence").catch(() => null);
  await loadSiteIndex();
  applyModules();
  showLicenceBanner();
  const first = $$("#nav button").find((b) => !b.hidden && !b.classList.contains("locked"));
  if (first) switchView(first.dataset.view);
  clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    if (document.hidden) return;
    if (state.view === "backups") loadBackups();
    else if (state.view === "firmware" && fw.tab === "versions") loadFwVersions();
    else if (state.view === "monitoring" && !$("#mon-dialog").open && !$("#mon-p-dialog").open && !$("#mon-if-dialog").open && !$("#mk-dialog").open && !$("#sn-dialog").open) loadMonitoring();
  }, 15000);
}

$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const err = $("#login-error");
  err.hidden = true;
  try {
    const user = await api("/api/auth/login", {
      method: "POST",
      body: { username: form.username.value, password: form.password.value },
    });
    form.password.value = "";
    if (user.two_factor === "code") return loginStep("code");
    if (user.two_factor === "setup") return loginStep("setup");
    await showApp(user);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
});

// ---------- two-factor sign-in ----------

/** The sign-in page's second step: a code, or setting two-factor up when it's required. */
function loginStep(step) {
  $("#login-form").hidden = step !== "password";
  $("#login-code-form").hidden = step !== "code";
  $("#login-setup").hidden = step !== "setup";
  if (step === "code") { $("#login-code-form").reset(); $("#login-code-form .error").hidden = true; $("#login-code-form").code.focus(); }
  if (step === "setup") tfSetup($("#login-setup"), (user) => { loginStep("password"); showApp(user); }, true);
}
$$(".login-back").forEach((b) => b.addEventListener("click", () => loginStep("password")));
$("#login-code-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, err = $(".error", form);
  err.hidden = true;
  try {
    const user = await api("/api/auth/login/code", { method: "POST", body: { code: form.code.value } });
    loginStep("password");
    await showApp(user);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    if (/sign in again/i.test(e.message)) setTimeout(() => loginStep("password"), 1500);
  }
});

function svgFrom(text) {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  return document.importNode(doc.documentElement, true);
}

function showRecoveryCodes(box, codes, done) {
  box.replaceChildren(
    h("h2", {}, "Your recovery codes"),
    h("p", {}, "Each one signs you in once if you lose your phone. Keep them somewhere safe (a password manager, or printed). They won't be shown again."),
    h("div", { class: "tf-codes" }, codes.map((c) => h("span", {}, c))),
    h("div", { class: "dialog-actions" },
      h("button", { onclick: () => navigator.clipboard?.writeText(codes.join("\n")).then(() => toast("Copied")) }, "Copy"),
      h("button", { class: "primary", onclick: done }, "I've saved them")));
}

/** Set two-factor up in `box`: QR code, a code from the app, then the recovery codes. */
async function tfSetup(box, finished, signingIn = false) {
  let s;
  try { s = await api("/api/auth/two-factor/start", { method: "POST" }); } catch (e) { return toast(e.message); }
  const code = h("input", { name: "code", autocomplete: "one-time-code", inputmode: "numeric", maxlength: 6, required: true });
  const err = h("p", { class: "error", hidden: true });
  box.replaceChildren(...[
    h("h2", {}, signingIn ? "Set up two-factor sign-in" : "Turn on two-factor sign-in"),
    signingIn ? h("p", { class: "muted" }, "Your admin requires a code from an authenticator app when you sign in. It takes a minute:") : null,
    h("ol", { class: "tf-steps" },
      h("li", {}, "Install an authenticator app on your phone if you don't have one (Microsoft Authenticator, Google Authenticator, Authy…)."),
      h("li", {}, "In the app, add an account and scan this code:")),
    h("div", { class: "tf-qr" }, svgFrom(s.qr_svg)),
    h("p", { class: "muted" }, "Can't scan it? Type this key in instead: ", h("span", { class: "tf-secret" }, s.secret)),
    h("form", { class: "form", onsubmit: async (ev) => {
      ev.preventDefault();
      err.hidden = true;
      try {
        const r = await api("/api/auth/two-factor/enable", { method: "POST", body: { code: code.value } });
        showRecoveryCodes(box, r.recovery_codes, () => finished(r.user));
      } catch (e) { err.textContent = e.message; err.hidden = false; }
    } }, h("label", {}, "3. Enter the 6-digit code the app shows", code), err,
      h("div", { class: "dialog-actions" },
        signingIn ? h("button", { type: "button", class: "ghost", onclick: () => loginStep("password") }, "Back") : null,
        h("button", { type: "submit", class: "primary" }, "Turn on")))].filter(Boolean));
  code.focus();
}

async function openTwoFactor() {
  const box = $("#tf-body");
  let st;
  try { st = await api("/api/auth/two-factor"); } catch (e) { return toast(e.message); }
  const close = () => $("#tf-dialog").close();
  if (!$("#tf-dialog").open) $("#tf-dialog").showModal();
  if (!st.available) return box.replaceChildren(h("p", {}, st.enabled ? "On." : "Off.", " ", st.note));
  if (!st.enabled) {
    box.replaceChildren(
      h("p", {}, "Off. With it on, signing in also needs a 6-digit code from an app on your phone, so a stolen password isn't enough."),
      h("div", { class: "dialog-actions" }, h("button", { class: "primary", onclick: () => tfSetup(box, () => { close(); toast("Two-factor sign-in is on"); }) }, "Turn on")));
    return;
  }
  const code = h("input", { autocomplete: "one-time-code", inputmode: "numeric", maxlength: 20, placeholder: "code from the app" });
  const pw = h("input", { type: "password", autocomplete: "current-password", placeholder: "your password" });
  const err = h("p", { class: "error", hidden: true });
  const fail = (e) => { err.textContent = e.message; err.hidden = false; };
  box.replaceChildren(...[
    h("p", {}, `On since ${fmtTime(st.since)}. ${st.recovery_left} recovery code(s) left.`),
    st.required ? h("p", { class: "muted" }, "Your admin requires it for local users, so it can't be turned off.") : null,
    h("div", { class: "form" },
      h("label", {}, "Code from the app", code),
      state.user.source === "local" && !st.required ? h("label", {}, "Password (to turn it off)", pw) : null, err,
      h("div", { class: "dialog-actions" },
        st.required ? null : h("button", { class: "danger", onclick: async () => {
          try { await api("/api/auth/two-factor/disable", { method: "POST", body: { code: code.value, password: pw.value } }); close(); toast("Two-factor sign-in is off"); } catch (e) { fail(e); }
        } }, "Turn off"),
        h("button", { onclick: async () => {
          try { const r = await api("/api/auth/two-factor/recovery-codes", { method: "POST", body: { code: code.value } }); showRecoveryCodes(box, r.recovery_codes, close); } catch (e) { fail(e); }
        } }, "New recovery codes")))].filter(Boolean));
}
$("#two-factor").addEventListener("click", openTwoFactor);
$("#tf-close").addEventListener("click", () => $("#tf-dialog").close());

$("#logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  showLogin();
});

// ---------- navigation ----------

function switchView(view) {
  state.view = view;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (VIEW_MODULE[view] && !hasModule(VIEW_MODULE[view])) return showLocked(view);
  $$(".view").forEach((s) => (s.hidden = s.id !== `view-${view}`));
  state.viewLoading = ({ backups: loadBackups, inventory: loadInventory, sites: loadSites, monitoring: loadMonitoring, firmware: loadFirmware, circuits: loadCircuits, syslog: loadSyslog, calendar: loadCalendar, credentials: loadCredentials,
    audit: loadAudit, users: loadUsers, settings: loadSettings })[view]();
}
$$("#nav button").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));

// ---------- search box (top bar) ----------

const gs = { timer: null, seq: 0, items: [], sel: -1 };

const GS_GROUPS = [
  ["devices", "Devices", (d) => [d.name, [d.address, d.site, d.platform, d.serial && `serial ${d.serial}`]], (d) => openDevice(d)],
  ["items", "Inventory items", (i) => [i.name, [i.type, i.site, i.rack && `rack ${i.rack}`, i.model, i.serial && `serial ${i.serial}`]], (i) => openItem(i.id)],
  ["sites", "Sites", (s) => [s.name, [s.code, s.city]], (s) => openSite(s.id)],
  ["circuits", "Circuits", (c) => [c.name, [c.service, c.ip, c.mac, c.switch && `${c.switch} ${c.port}`]], (c) => openCircuit(c)],
  ["carriers", "Carrier circuits", (c) => [`${c.provider} ${c.circuit_ref}`.trim(), [c.service, c.site, c.wan_ip]], (c) => openCarrier(c.id)],
  ["network", "Seen on the network (last scan)", (n) => [n.mac, [n.ip, n.device ? `on ${n.device} ${n.port}` : "not on an edge port", n.vlan && `VLAN ${n.vlan}`, n.seen_at && fmtAgo(n.seen_at)]],
    (n) => n.device_id ? openPorts({ id: n.device_id, name: n.device }) : toast("Not seen on a switch's edge port")],
];

function gsClose() {
  $("#gs-results").hidden = true;
  $("#gs").setAttribute("aria-expanded", "false");
  gs.sel = -1;
}

async function gsRun() {
  const q = $("#gs").value.trim();
  const box = $("#gs-results");
  if (q.length < 2) return gsClose();
  const seq = ++gs.seq;
  let res;
  try { res = await api(`/api/search?q=${encodeURIComponent(q)}`); } catch (e) { return toast(e.message); }
  if (seq !== gs.seq) return; // a newer search has started
  gs.items = [];
  gs.sel = -1;
  const parts = [];
  for (const [key, title, show, open] of GS_GROUPS) {
    const g = res.groups[key];
    if (!g) continue;
    parts.push(h("h4", {}, title));
    for (const item of g.items) {
      const [name, sub] = show(item);
      const go = () => { gsClose(); $("#gs").blur(); open(item); };
      const el = h("button", { class: "gs-item", role: "option", onclick: go },
        name || "—", h("span", { class: "sub" }, sub.filter(Boolean).join(" · ")));
      gs.items.push({ el, go });
      parts.push(el);
    }
    if (g.more) parts.push(h("div", { class: "gs-more" }, "More found: type more to narrow it down"));
  }
  if (!parts.length) parts.push(h("div", { class: "gs-empty" }, `Nothing found for “${q}”`));
  box.replaceChildren(...parts);
  box.hidden = false;
  $("#gs").setAttribute("aria-expanded", "true");
}

function gsMove(step) {
  if (!gs.items.length) return;
  gs.sel = (gs.sel + step + gs.items.length) % gs.items.length;
  gs.items.forEach((x, i) => x.el.classList.toggle("sel", i === gs.sel));
  gs.items[gs.sel].el.scrollIntoView({ block: "nearest" });
}

$("#gs").addEventListener("input", () => { clearTimeout(gs.timer); gs.timer = setTimeout(gsRun, 250); });
$("#gs").addEventListener("focus", () => { if ($("#gs").value.trim().length >= 2) gsRun(); });
$("#gs").addEventListener("keydown", (ev) => {
  if (ev.key === "ArrowDown") { ev.preventDefault(); gsMove(1); }
  else if (ev.key === "ArrowUp") { ev.preventDefault(); gsMove(-1); }
  else if (ev.key === "Enter") { ev.preventDefault(); (gs.items[gs.sel] || gs.items[0])?.go(); }
  else if (ev.key === "Escape") { gsClose(); $("#gs").blur(); }
});
document.addEventListener("click", (ev) => { if (!ev.target.closest(".gsearch")) gsClose(); });
document.addEventListener("keydown", (ev) => {
  // "/" jumps to the search box, unless you are typing somewhere already
  if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const t = ev.target;
  if (t.closest("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
  ev.preventDefault();
  $("#gs").focus();
  $("#gs").select();
});

/** Open a device's detail window on the first tab this person may see; else its inventory row. */
function openDevice(d) {
  const tabs = $$("#detail-tabs button").filter((b) => !b.hidden && !b.classList.contains("locked"));
  if (!tabs.length) return d.asset_id ? openItem(d.asset_id) : toast("Nothing more to show for this device");
  openDetail({ device: { address: "", ...d } });
  selectDetailTab(tabs[0].dataset.tab);
}

/** Go to the Circuits page showing this circuit. */
async function openCircuit(c) {
  switchView("circuits");
  await state.viewLoading;
  $("#ct-search").value = c.name;
  renderCircuits();
}

// ---------- config backups ----------

const snmpOnly = (platform) => (state.platforms || []).some((p) => p.key === platform && p.ssh === false);

function effectiveStatus(row) {
  if (!row.backup) return row.device.enabled ? "snmp" : "disabled";
  if (row.backup.busy) return "running";
  if (!row.device.enabled || !row.backup.enabled) return "disabled";
  return row.backup.status;
}

const STATUS_LABEL = { success: "OK", failed: "Failed", running: "Running", never: "Never", disabled: "Disabled",
  snmp: "SNMP only" };

async function loadBackups() {
  try {
    const [rows, summary, cp] = await Promise.all([api("/api/backup/devices"), api("/api/backup/summary"),
      hasModule("backups") ? api("/api/compliance").catch(() => null) : null]);
    state.rows = rows;
    state.cpFailing = new Map();
    for (const x of (cp ? cp.results : [])) {
      if (!x.passed) state.cpFailing.set(x.device_id, (state.cpFailing.get(x.device_id) || 0) + 1);
    }
    renderSummary(summary);
    renderSiteFilter();
    renderDevices();
  } catch (e) {
    toast(e.message);
  }
}

function renderSummary(s) {
  const tiles = [
    ["", "Devices", s.total],
    ["success", "Backed up OK", s.success],
    ["failed", "Failing", s.failed],
    ["never", "Never backed up", s.never],
    ["disabled", "Disabled", s.disabled],
  ];
  $("#summary").replaceChildren(...tiles.map(([key, label, n]) =>
    h("button", { class: `tile ${key}`, onclick: () => { $("#filter-status").value = key; renderDevices(); } },
      h("span", { class: "num" }, n ?? 0), h("span", { class: "lbl" }, label))));
}

function renderSiteFilter() {
  const sel = $("#filter-site");
  const current = sel.value;
  const sites = [...new Set(state.rows.map((r) => r.device.site).filter(Boolean))].sort();
  sel.replaceChildren(h("option", { value: "" }, "All sites"), ...sites.map((s) => h("option", { value: s }, s)));
  sel.value = sites.includes(current) ? current : "";
  $("#site-list").replaceChildren(...sites.map((s) => h("option", { value: s })));
}

function renderDevices() {
  const q = $("#search").value.trim().toLowerCase();
  const status = $("#filter-status").value;
  const site = $("#filter-site").value;
  const rows = state.rows.filter((r) => {
    const d = r.device;
    if (site && d.site !== site) return false;
    if (status && effectiveStatus(r) !== status) return false;
    if (q && ![d.name, d.address, d.site, d.platform_label, d.notes].some((v) => (v || "").toLowerCase().includes(q))) return false;
    return true;
  });
  $("#device-table tbody").replaceChildren(...rows.map(deviceRow));
  $("#empty-devices").hidden = rows.length > 0;
  $("#empty-devices").textContent = state.rows.length ? "No devices match the filter." :
    can("inventory", "addresses") ? "No devices yet - add a credential profile, then add your first device." : "No devices yet.";
}

function deviceRow(r) {
  const d = r.device, b = r.backup;
  const st = effectiveStatus(r);
  let result;
  if (st === "failed") {
    result = [h("span", { class: "badge failed" }, `Failed${b.consecutive_failures > 1 ? ` ×${b.consecutive_failures}` : ""}`),
      h("span", { class: "errtext" }, b.last_error || "")];
  } else {
    result = h("span", { class: `badge ${st}` }, STATUS_LABEL[st] || st);
  }
  if (st === "snmp") result = h("span", { class: "badge snmp", title: "Monitored with SNMP only: no config to back up" }, "SNMP only");
  const actions = [];
  if (b && hasModule("backups")) actions.push(h("button", { class: "small", onclick: () => openDetail(r) }, "History"));
  if (b && can("backups", "run") && hasModule("backups")) {
    actions.push(h("button", { class: "small", disabled: b.busy, onclick: () => runNow(d) }, "Backup now"));
  }
  if (b && can("circuits", "view") && hasModule("circuits")) {
    actions.push(h("button", { class: "small", title: "What is on each port", onclick: () => openPorts(d) }, "Ports"));
  }
  if (can("syslog", "view") && hasModule("syslog")) {
    actions.push(h("button", { class: "small", title: "This device's syslog messages",
      onclick: () => { sl.pick = String(d.id); switchView("syslog"); } }, "Logs"));
  }
  if (can("inventory", "manage")) {
    actions.push(
      h("button", { class: "small", onclick: () => openDeviceDialog(r) }, "Edit"),
      h("button", { class: "small danger", onclick: () => deleteDevice(d) }, "Delete"));
  }
  return h("tr", { class: st === "disabled" ? "disabled" : "" },
    h("td", {}, h("span", { class: `dot ${st}`, title: STATUS_LABEL[st] })),
    h("td", { class: "name" }, d.name, d.notes ? h("small", {}, d.notes.slice(0, 80)) : null),
    h("td", {}, d.address),
    h("td", {}, siteLink(d.site)),
    h("td", {}, d.platform_label),
    h("td", {}, b ? fmtFreq(b.frequency_minutes) : "—"),
    h("td", b ? { title: fmtTime(b.last_success) } : {}, b ? fmtAgo(b.last_success) : "—"),
    h("td", b ? { title: fmtTime(b.last_change) } : {}, b && b.last_change ? fmtAgo(b.last_change) : "—"),
    h("td", { class: "result" }, result,
      state.cpFailing && state.cpFailing.get(d.id) ? h("small", { class: "sub" }, h("span", { class: "link errtext", title: "Compliance rules this config fails",
        onclick: () => { openDetail(r); selectDetailTab("compliance"); } }, `⚠ ${state.cpFailing.get(d.id)} compliance rule(s)`)) : null),
    h("td", { class: "actions" }, actions));
}

["input", "change"].forEach((evt) => {
  $("#search").addEventListener(evt, renderDevices);
  $("#filter-status").addEventListener(evt, renderDevices);
  $("#filter-site").addEventListener(evt, renderDevices);
});

async function runNow(device) {
  try {
    const res = await api(`/api/backup/devices/${device.id}/run`, { method: "POST" });
    toast(`${device.name}: ${res.message}`);
    loadBackups();
    setTimeout(loadBackups, 5000);
  } catch (e) {
    toast(e.message);
  }
}

async function deleteDevice(device) {
  if (!confirm(`Delete ${device.name}?\n\nIts backup history in the GUI is removed. Stored config versions stay in the git archive.`)) return;
  try {
    await api(`/api/devices/${device.id}`, { method: "DELETE" });
    toast(`${device.name} deleted`);
    loadBackups();
  } catch (e) {
    toast(e.message);
  }
}

// ---------- device dialog ----------

async function openDeviceDialog(row = null) {
  const dlg = $("#device-dialog");
  const form = $("#device-form");
  form.reset();
  $(".error", form).hidden = true;
  state.credentials = await api("/api/credentials").catch(() => []);
  form.platform.replaceChildren(...platformOptions());
  form.credential_id.replaceChildren(h("option", { value: "" }, "— none —"),
    ...state.credentials.map((c) => h("option", { value: c.id }, `${c.name} (${c.username})`)));
  $("#device-dialog-title").textContent = row ? `Edit ${row.device.name}` : "Add device";
  if (row) {
    const d = row.device;
    form.name.value = d.name;
    form.address.value = d.address;
    form.platform.value = d.platform;
    form.site.value = d.site;
    form.credential_id.value = d.credential_id ?? "";
    form.notes.value = d.notes;
    form.enabled.checked = d.enabled;
    if (row.backup) {
      form.backup_enabled.checked = row.backup.enabled;
      const freq = String(row.backup.frequency_minutes);
      if (![...form.frequency_minutes.options].some((o) => o.value === freq)) {
        form.frequency_minutes.append(h("option", { value: freq }, fmtFreq(row.backup.frequency_minutes)));
      }
      form.frequency_minutes.value = freq;
    }
  } else if (state.credentials.length === 1) {
    form.credential_id.value = state.credentials[0].id;
  }
  // Where a device account's password is sent is a separate permission.
  const where = can("inventory", "addresses");
  form.address.disabled = form.credential_id.disabled = !where;
  form.address.title = form.credential_id.title = where ? "" :
    "Changing the address or credential profile needs the 'addresses' level for Devices and credentials";
  dlg.dataset.deviceId = row ? row.device.id : "";
  deviceFormKind();
  if (!row || !snmpOnly(row.device.platform)) showSshKey(row);
  dlg.showModal();
}

/** An SNMP-only type has no credential, backups or SSH key: hide those fields. */
function deviceFormKind() {
  const form = $("#device-form"), snmp = snmpOnly(form.platform.value);
  form.querySelectorAll("[data-ssh]").forEach((el) => { el.hidden = snmp; });
  $("#device-snmp-only").hidden = !snmp;
  if (snmp) $("#device-ssh-key").hidden = true;
}
$("#device-form").platform.addEventListener("change", deviceFormKind);

/** The device's recorded SSH host key, and (admins) forgetting it after a replacement. */
async function showSshKey(row) {
  const p = $("#device-ssh-key");
  p.hidden = true;
  if (!row) return;
  const r = await api(`/api/devices/${row.device.id}/ssh-key`).catch(() => null);
  if (!r) return;
  p.replaceChildren(r.key ? `SSH host key: ${r.key.type} ${r.key.fingerprint} ` : "SSH host key: recorded at the first connection",
    r.key && isAdmin() ? h("button", { type: "button", class: "small", onclick: async () => {
      if (!confirm(`Forget the SSH host key of ${row.device.name}? Only if the device was replaced or reinstalled: the next connection trusts the key it is offered.`)) return;
      await api(`/api/devices/${row.device.id}/ssh-key`, { method: "DELETE" });
      toast("SSH host key forgotten");
      showSshKey(row);
    } }, "Forget") : "");
  p.hidden = false;
}

$("#add-device").addEventListener("click", () => openDeviceDialog());

$("#device-form").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const form = ev.target;
  const dlg = $("#device-dialog");
  const id = dlg.dataset.deviceId;
  const body = {
    name: form.name.value, address: form.address.value, platform: form.platform.value,
    site: form.site.value, notes: form.notes.value, enabled: form.enabled.checked,
    credential_id: form.credential_id.value && !snmpOnly(form.platform.value) ? Number(form.credential_id.value) : null,
  };
  try {
    const device = await api(id ? `/api/devices/${id}` : "/api/devices", { method: id ? "PUT" : "POST", body });
    if (!snmpOnly(device.platform)) {
      await api(`/api/backup/devices/${device.id}/settings`, {
        method: "PUT",
        body: { frequency_minutes: Number(form.frequency_minutes.value), enabled: form.backup_enabled.checked },
      });
    }
    dlg.close();
    toast(`${device.name} saved`);
    loadBackups();
  } catch (e) {
    const err = $(".error", form);
    err.textContent = e.message;
    err.hidden = false;
  }
});

// ---------- device detail (history, versions, diffs) ----------

async function openDetail(row) {
  state.detailDevice = row.device;
  $("#detail-title").textContent = row.device.address ? `${row.device.name} — ${row.device.address}` : row.device.name;
  $("#detail-text").hidden = true;
  selectDetailTab("runs");
  $("#detail-dialog").showModal();
}

function selectDetailTab(tab) {
  $$("#detail-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("#detail-runs").hidden = tab !== "runs";
  $("#detail-versions").hidden = tab !== "versions";
  $("#detail-circuits").hidden = tab !== "circuits";
  $("#detail-compliance").hidden = tab !== "compliance";
  $("#detail-ports").hidden = tab !== "ports";
  $("#detail-upgrades").hidden = tab !== "upgrades";
  $("#detail-text").hidden = true;
  ({ runs: loadRuns, versions: loadVersions, circuits: loadDeviceCircuits, upgrades: loadDeviceUpgrades,
    compliance: loadDeviceCompliance, ports: loadDevicePorts })[tab]();
}
$$("#detail-tabs button").forEach((b) => b.addEventListener("click", () => selectDetailTab(b.dataset.tab)));
$("#detail-close").addEventListener("click", () => $("#detail-dialog").close());

async function loadRuns() {
  const pane = $("#detail-runs");
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const runs = await api(`/api/backup/devices/${state.detailDevice.id}/runs`);
    if (!runs.length) return pane.replaceChildren(h("p", { class: "empty" }, "No backup attempts yet."));
    pane.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["Started", "Trigger", "Result", "Detail"].map((t) => h("th", {}, t)))),
      h("tbody", {}, runs.map((r) => h("tr", {},
        h("td", {}, fmtTime(r.started_at)),
        h("td", {}, r.trigger),
        h("td", {}, h("span", { class: `badge ${r.status === "success" && r.changed ? "changed" : r.status}` },
          r.status === "success" ? (r.changed ? "Changed" : "OK") : STATUS_LABEL[r.status] || r.status)),
        h("td", {}, r.error_type ? `[${r.error_type}] ${r.message}` : r.message))))));
  } catch (e) {
    pane.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

async function loadVersions() {
  const pane = $("#detail-versions");
  const id = state.detailDevice.id;
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const versions = await api(`/api/backup/devices/${id}/versions`);
    if (!versions.length) return pane.replaceChildren(h("p", { class: "empty" }, "No stored versions yet."));
    pane.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["Saved", "Version", "Note", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, versions.map((v, i) => h("tr", {},
        h("td", {}, fmtTime(v.date)),
        h("td", {}, h("code", {}, v.commit.slice(0, 8))),
        h("td", {}, v.message),
        h("td", { class: "actions" },
          h("button", { class: "small", onclick: () => showConfig(id, v.commit) }, "View"),
          i < versions.length - 1
            ? h("button", { class: "small", onclick: () => showDiff(id, v.commit) }, "Changes") : null,
          h("button", { class: "small", onclick: () => downloadConfig(id, v.commit) }, "Download")))))));
  } catch (e) {
    pane.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

async function showConfig(id, commit) {
  const pre = $("#detail-text");
  try {
    pre.textContent = await api(`/api/backup/devices/${id}/config?version=${commit}`);
    pre.hidden = false;
  } catch (e) {
    toast(e.message);
  }
}

async function showDiff(id, commit) {
  const pre = $("#detail-text");
  try {
    const diff = await api(`/api/backup/devices/${id}/diff?to=${commit}`);
    pre.replaceChildren(...(diff || "No differences.\n").split("\n").map((line) => {
      const cls = line.startsWith("@@") ? "hunk" : line.startsWith("+") && !line.startsWith("+++") ? "add"
        : line.startsWith("-") && !line.startsWith("---") ? "del" : null;
      return cls ? h("span", { class: cls }, line) : line + "\n";
    }));
    pre.hidden = false;
  } catch (e) {
    toast(e.message);
  }
}

async function downloadConfig(id, commit) {
  try {
    const text = await api(`/api/backup/devices/${id}/config?version=${commit}`);
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = h("a", { href: url, download: `${state.detailDevice.name}_${commit.slice(0, 8)}.cfg` });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast(e.message);
  }
}

// ---------- firmware ----------

const fw = { tab: "versions", rows: [], standards: [], images: [] };

const COMPLIANCE_LABEL = {
  compliant: "On standard", behind: "Behind", ahead: "Ahead", no_standard: "No standard", unknown: "Unknown",
};

function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n >= 2 ** 30) return `${(n / 2 ** 30).toFixed(1)} GB`;
  if (n >= 2 ** 20) return `${Math.round(n / 2 ** 20)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

function loadFirmware() {
  const visible = $$("#fw-tabs button").filter((b) => !b.hidden).map((b) => b.dataset.tab);
  selectFwTab(visible.includes(fw.tab) ? fw.tab : visible[0]);
}

function selectFwTab(tab) {
  fw.tab = tab;
  $$("#fw-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".fw-pane").forEach((p) => (p.hidden = p.id !== `fw-${tab}`));
  ({ versions: loadFwVersions, standards: loadFwStandards, images: loadFwImages, jobs: loadJobs })[tab]();
}
$$("#fw-tabs button").forEach((b) => b.addEventListener("click", () => selectFwTab(b.dataset.tab)));

async function loadFwVersions() {
  try {
    const [rows, summary, images] = await Promise.all([
      api("/api/firmware/devices"), api("/api/firmware/summary"), api("/api/firmware/images")]);
    fw.rows = rows;
    fw.images = images;
    renderFwSummary(summary);
    renderFwFilters();
    renderFwDevices();
  } catch (e) {
    toast(e.message);
  }
}

function renderFwSummary(s) {
  const tiles = [
    ["", "Devices", s.total],
    ["compliant", "On standard", s.compliant],
    ["behind", "Behind standard", s.behind],
    ["ahead", "Ahead of standard", s.ahead],
    ["no_standard", "No standard set", s.no_standard],
    ["unknown", "Version unknown", s.unknown],
  ];
  $("#fw-summary").replaceChildren(...tiles.map(([key, label, n]) =>
    h("button", { class: `tile ${key}`, onclick: () => { $("#fw-filter-compliance").value = key; renderFwDevices(); } },
      h("span", { class: "num" }, n ?? 0), h("span", { class: "lbl" }, label))));
}

// Platform choices grouped by vendor (Cisco, Arista, Juniper, ...)
function platformOptions() {
  const groups = new Map();
  state.platforms.forEach((p) => groups.set(p.vendor, [...(groups.get(p.vendor) || []), p]));
  return [...groups].map(([vendor, list]) => h("optgroup", { label: vendor },
    ...list.map((p) => h("option", { value: p.key }, p.label))));
}

function fillSelect(sel, allLabel, values) {
  const current = sel.value;
  sel.replaceChildren(h("option", { value: "" }, allLabel), ...values.map(([v, l]) => h("option", { value: v }, l)));
  sel.value = values.some(([v]) => v === current) ? current : "";
}

function renderFwFilters() {
  const platforms = new Map(fw.rows.map((r) => [r.device.platform, r.device.platform_label]));
  fillSelect($("#fw-filter-platform"), "All platforms", [...platforms].sort((a, b) => a[1].localeCompare(b[1])));
  const sites = [...new Set(fw.rows.map((r) => r.device.site).filter(Boolean))].sort();
  fillSelect($("#fw-filter-site"), "All sites", sites.map((x) => [x, x]));
}

function renderFwDevices() {
  const q = $("#fw-search").value.trim().toLowerCase();
  const comp = $("#fw-filter-compliance").value;
  const platform = $("#fw-filter-platform").value;
  const site = $("#fw-filter-site").value;
  const rows = fw.rows.filter((r) => {
    const d = r.device, f = r.facts;
    if (comp && r.compliance !== comp) return false;
    if (platform && d.platform !== platform) return false;
    if (site && d.site !== site) return false;
    if (q && ![d.name, d.address, d.site, f.model, f.version, f.serial].some((v) => (v || "").toLowerCase().includes(q))) return false;
    return true;
  });
  $("#fw-table tbody").replaceChildren(...rows.map(fwRow));
  const empty = $("#fw-empty");
  empty.hidden = rows.length > 0;
  empty.textContent = fw.rows.length ? "No devices match the filter." : "No devices yet - add them on the Config backups page.";
}

function fwRow(r) {
  const d = r.device, f = r.facts;
  const image = r.target_image ? fw.images.find((i) => i.filename === r.target_image) : null;
  const lowFlash = image && f.flash_free !== null && f.flash_free < image.size * 1.1;
  let checked;
  if (f.busy || f.status === "running") checked = h("span", { class: "badge running" }, "Checking…");
  else if (f.status === "failed") checked = [h("span", { class: "badge failed" }, "Check failed"),
    h("span", { class: "errtext" }, f.last_error || ""),
    f.last_success ? h("span", { class: "errtext" }, `Last good: ${fmtAgo(f.last_success)}`) : null];
  else checked = h("span", { title: fmtTime(f.last_success) }, fmtAgo(f.last_success));
  const actions = can("firmware", "manage")
    ? [h("button", { class: "small", disabled: f.busy, onclick: () => fwCheckNow(d) }, "Check now"),
      h("button", { class: "small", onclick: () => openUpgradeSettings(d, loadFwVersions) }, "Upgrade settings")] : [];
  const mode = [f.boot_mode, f.ha_role].filter(Boolean).join(" · ") || "—";
  return h("tr", { class: d.enabled ? "" : "disabled" },
    h("td", {}, h("span", { class: `dot ${r.compliance}`, title: COMPLIANCE_LABEL[r.compliance] })),
    h("td", { class: "name" }, d.name, h("small", {}, d.address)),
    h("td", {}, siteLink(d.site)),
    h("td", {}, d.platform_label),
    h("td", {}, f.model || "—", f.serial ? h("small", { class: "sub mono" }, f.serial) : null),
    h("td", {}, f.version ? h("code", {}, f.version) : "—",
      f.previous_version ? h("small", { class: "sub" }, `was ${f.previous_version} until ${fmtTime(f.version_changed_at)}`) : null),
    h("td", {}, h("span", { class: `badge ${r.compliance}` }, COMPLIANCE_LABEL[r.compliance]),
      r.target_version ? h("small", { class: "sub" }, `target ${r.target_version}`) : null),
    h("td", { class: lowFlash ? "lowflash" : "", title: lowFlash ? "Not enough space for the target image" : "" },
      fmtBytes(f.flash_free), f.flash_total ? h("small", { class: "sub" }, `of ${fmtBytes(f.flash_total)}`) : null),
    h("td", {}, mode),
    h("td", { class: "result" }, checked),
    h("td", { class: "actions" }, actions));
}

["input", "change"].forEach((evt) => {
  ["#fw-search", "#fw-filter-compliance", "#fw-filter-platform", "#fw-filter-site"]
    .forEach((sel) => $(sel).addEventListener(evt, renderFwDevices));
});

async function fwCheckNow(device) {
  try {
    const res = await api(`/api/firmware/devices/${device.id}/check`, { method: "POST" });
    toast(`${device.name}: ${res.message}`);
    loadFwVersions();
    setTimeout(loadFwVersions, 5000);
  } catch (e) {
    toast(e.message);
  }
}

$("#fw-check-all").addEventListener("click", async () => {
  if (!confirm("Log in to every enabled device now and read its software version?")) return;
  try {
    toast((await api("/api/firmware/check-all", { method: "POST" })).message);
    loadFwVersions();
    setTimeout(loadFwVersions, 5000);
  } catch (e) {
    toast(e.message);
  }
});

// Standards

async function loadFwStandards() {
  try {
    [fw.standards, fw.rows] = await Promise.all([api("/api/firmware/standards"), api("/api/firmware/devices")]);
  } catch (e) {
    return toast(e.message);
  }
  const counts = {};
  fw.rows.forEach((r) => { if (r.standard_id) counts[r.standard_id] = (counts[r.standard_id] || 0) + 1; });
  $("#fw-standard-table tbody").replaceChildren(...fw.standards.map((s) => h("tr", {},
    h("td", {}, s.platform_label),
    h("td", {}, h("code", {}, s.model_pattern)),
    h("td", {}, h("code", {}, s.target_version)),
    h("td", {}, s.image_filename || "—"),
    h("td", {}, counts[s.id] || 0),
    h("td", {}, s.notes || ""),
    h("td", {}, fmtTime(s.updated_at), h("small", { class: "sub" }, s.updated_by)),
    h("td", { class: "actions" }, can("firmware", "manage") ? [
      h("button", { class: "small", onclick: () => openStandardDialog(s) }, "Edit"),
      h("button", { class: "small danger", onclick: () => deleteStandard(s) }, "Delete")] : []))));
  $("#fw-standards-empty").hidden = fw.standards.length > 0;
}

async function openStandardDialog(std = null) {
  const form = $("#fw-standard-form");
  form.reset();
  $(".error", form).hidden = true;
  fw.images = await api("/api/firmware/images").catch(() => []);
  form.platform.replaceChildren(...platformOptions());
  const fillImages = () => {
    const current = form.image_id.value;
    form.image_id.replaceChildren(h("option", { value: "" }, "— none —"),
      ...fw.images.filter((i) => i.platform === form.platform.value)
        .map((i) => h("option", { value: i.id }, `${i.filename} (${i.version})`)));
    form.image_id.value = current;
  };
  form.platform.onchange = fillImages;
  form.image_id.onchange = () => {
    const img = fw.images.find((i) => String(i.id) === form.image_id.value);
    if (img) form.target_version.value = img.version;
  };
  $("#fw-standard-title").textContent = std ? "Edit standard" : "Add standard";
  if (std) {
    form.platform.value = std.platform;
    form.model_pattern.value = std.model_pattern === "*" ? "" : std.model_pattern;
    form.target_version.value = std.target_version;
    form.notes.value = std.notes;
  }
  fillImages();
  if (std && std.image_id) form.image_id.value = std.image_id;
  $("#fw-standard-dialog").dataset.stdId = std ? std.id : "";
  $("#fw-standard-dialog").showModal();
}
$("#fw-add-standard").addEventListener("click", () => openStandardDialog());

$("#fw-standard-form").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const form = ev.target;
  const id = $("#fw-standard-dialog").dataset.stdId;
  const body = {
    platform: form.platform.value, model_pattern: form.model_pattern.value || "*",
    target_version: form.target_version.value, notes: form.notes.value,
    image_id: form.image_id.value ? Number(form.image_id.value) : null,
  };
  try {
    await api(id ? `/api/firmware/standards/${id}` : "/api/firmware/standards", { method: id ? "PUT" : "POST", body });
    $("#fw-standard-dialog").close();
    loadFwStandards();
  } catch (e) {
    const err = $(".error", form);
    err.textContent = e.message;
    err.hidden = false;
  }
});

async function deleteStandard(std) {
  if (!confirm(`Delete the standard for ${std.platform_label} ${std.model_pattern}?`)) return;
  try {
    await api(`/api/firmware/standards/${std.id}`, { method: "DELETE" });
    loadFwStandards();
  } catch (e) {
    toast(e.message);
  }
}

// Image library

async function loadFwImages() {
  try {
    fw.images = await api("/api/firmware/images");
  } catch (e) {
    return toast(e.message);
  }
  const images = [...fw.images].sort((a, b) => a.vendor.localeCompare(b.vendor) || a.platform.localeCompare(b.platform));
  $("#fw-image-table tbody").replaceChildren(...images.map((i) => h("tr", {},
    h("td", {}, h("b", {}, i.vendor)),
    h("td", { class: "name" }, i.filename, i.recommended ? h("span", { class: "badge success" }, "Recommended") : null,
      i.release_ref ? h("small", {}, i.release_ref) : null, i.notes ? h("small", {}, i.notes.slice(0, 80)) : null,
      i.job_count ? h("small", {}, `Used by ${i.job_count} upgrade job(s)`) : null),
    h("td", {}, i.platform_label),
    h("td", {}, h("code", {}, i.version)),
    h("td", {}, h("code", {}, i.model_pattern)),
    h("td", {}, fmtBytes(i.size)),
    h("td", { title: `SHA-512: ${i.sha512}` }, h("code", {}, i.md5),
      h("small", { class: "sub" }, i.verified ? "✓ matched vendor checksum" : "not verified against vendor checksum")),
    h("td", {}, fmtTime(i.uploaded_at), h("small", { class: "sub" }, i.uploaded_by)),
    h("td", { class: "actions" }, can("firmware", "manage") ? [
      h("button", { class: "small", onclick: () => toggleRecommended(i) }, i.recommended ? "Unmark" : "Recommend"),
      h("button", { class: "small danger", disabled: i.job_count > 0, onclick: () => deleteImage(i) }, "Delete")] : []))));
  $("#fw-images-empty").hidden = fw.images.length > 0;
}

function openUploadDialog() {
  const form = $("#fw-upload-form");
  form.reset();
  $(".error", form).hidden = true;
  $("#fw-upload-progress").hidden = true;
  form.platform.replaceChildren(...platformOptions());
  $("#fw-upload-dialog").showModal();
}
$("#fw-upload").addEventListener("click", openUploadDialog);

// Guess the version from common image names, e.g. cat9k_iosxe.17.12.04.SPA.bin,
// nxos.9.3.10.bin, cisco-asa-fp2k.9.18.4.SPA, x930-5.5.4-1.1.rel
$("#fw-upload-form").file.addEventListener("change", (ev) => {
  const form = ev.target.form;
  const file = ev.target.files[0];
  if (!file || form.version.value) return;
  const m = file.name.match(/[.-](\d+\.\d+[.\d]*[a-z]?(?:-\d+\.\d+)?)(?:\.SPA)?\.(?:bin|rel|SPA|tar)$/i);
  if (m) form.version.value = m[1];
});

$("#fw-upload-form").addEventListener("submit", (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const form = ev.target;
  const err = $(".error", form);
  const bar = $("#fw-upload-progress");
  const file = form.file.files[0];
  const params = new URLSearchParams({
    filename: file.name, platform: form.platform.value, version: form.version.value,
    model_pattern: form.model_pattern.value || "*", checksum: form.checksum.value, notes: form.notes.value,
  });
  const submit = $("button[value=save]", form);
  err.hidden = true;
  bar.hidden = false;
  bar.value = 0;
  submit.disabled = true;
  // XMLHttpRequest rather than fetch, for upload progress on large images.
  const xhr = new XMLHttpRequest();
  xhr.open("PUT", `/api/firmware/images/upload?${params}`);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = (100 * e.loaded) / e.total; };
  xhr.onloadend = () => {
    submit.disabled = false;
    if (xhr.status === 201) {
      $("#fw-upload-dialog").close();
      toast(`${file.name} uploaded`);
      loadFwImages();
      return;
    }
    if (xhr.status === 401) return showLogin();
    let msg = xhr.statusText || "Upload failed";
    try {
      const detail = JSON.parse(xhr.responseText).detail;
      msg = Array.isArray(detail) ? detail.map((e) => `${e.loc.slice(-1)[0]}: ${e.msg}`).join("; ") : detail;
    } catch (_) { /* not JSON */ }
    bar.hidden = true;
    err.textContent = msg;
    err.hidden = false;
  };
  xhr.send(file);
});

async function deleteImage(img) {
  if (!confirm(`Delete ${img.filename} from the server?`)) return;
  try {
    await api(`/api/firmware/images/${img.id}`, { method: "DELETE" });
    loadFwImages();
  } catch (e) {
    toast(e.message);
  }
}

// ---------- the report ----------

async function openReport() {
  const body = $("#rp-body");
  body.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  if (!$("#rp-dialog").open) $("#rp-dialog").showModal();
  let r;
  try { r = await api(`/api/reports?days=${$("#rp-days").value}`); } catch (e) { return body.replaceChildren(h("p", { class: "error" }, e.message)); }
  body.replaceChildren(
    h("p", { class: "muted" }, `${$("#site-name").textContent || ""} · from ${fmtTime(r.since)} to ${fmtTime(r.generated_at)}`),
    h("div", { class: "report-grid" }, ...r.sections.map((sec) => h("section", { class: `report-section card${sec.bad ? " bad" : ""}` },
      h("h3", {}, sec.title, sec.bad ? h("span", { class: "badge failed" }, "needs a look") : ""),
      h("table", {}, h("tbody", {}, sec.rows.map(([label, value, more]) => h("tr", {},
        h("td", {}, label, more ? h("small", { class: "sub" }, more) : null), h("td", { class: "num" }, String(value))))))))));
}
$("#act-report").addEventListener("click", openReport);
$("#rp-days").addEventListener("change", openReport);
$("#rp-close").addEventListener("click", () => $("#rp-dialog").close());
$("#rp-print").addEventListener("click", () => window.print());

// ---------- switch ports ----------

const PORT_STATUS = {
  ok: ["success", "Its circuit is here"], problem: ["failed", "Its circuit isn't here (moved or not seen)"],
  moved_here: ["changed", "A circuit documented elsewhere is here"], unlisted: ["never", "In use, not in the circuit list"],
  uplink: ["uplink", "Uplink to another switch"], empty: ["empty", "Nothing seen"],
};

/** Open a device's port view (from the inventory, a rack, Config backups). */
function openPorts(device) {
  openDetail({ device: { address: "", ...device } });
  selectDetailTab("ports");
}

async function loadDevicePorts() {
  const pane = $("#detail-ports");
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  let d;
  try { d = await api(`/api/circuits/ports/${state.detailDevice.id}`); } catch (e) { return pane.replaceChildren(h("p", { class: "error" }, e.message)); }
  if (!d.ports.length) {
    return pane.replaceChildren(h("p", { class: "empty" }, d.scanned_at ? "The last scan saw nothing on this device's ports, and the circuit list puts nothing on it."
      : "This device hasn't been scanned yet: Circuits › Scan network now reads its MAC table."));
  }
  const info = h("div", { class: "port-info" }, h("p", { class: "muted" }, "Click a port to see what is on it."));
  const show = (p) => {
    $$(".port.sel", pane).forEach((x) => x.classList.remove("sel"));
    info.replaceChildren(
      h("h3", {}, p.port, " ", h("span", { class: `badge ${PORT_STATUS[p.status][0]}` }, PORT_STATUS[p.status][1])),
      p.circuits.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Circuit", "Service", "VLAN", "MAC / IP", "Documented on", "On the network"].map((t) => h("th", {}, t)))),
        h("tbody", {}, p.circuits.map((c) => h("tr", {},
          h("td", { class: "name" }, c.device_name || "—"), h("td", {}, c.service || "—"), h("td", {}, c.vlan || "—"),
          h("td", {}, h("code", {}, c.mac || "—"), c.ip ? h("small", { class: "sub" }, c.ip) : null),
          h("td", {}, c.documented || "—"),
          h("td", {}, h("span", { class: `badge ${CT_LIVE_CLS[c.live_status] || "never"}` }, c.live_status_label || "—"), c.found ? h("small", { class: "sub" }, c.found) : null)))))
        : h("p", { class: "muted" }, "No circuit in the list for this port."),
      p.macs.length ? h("div", {}, h("h4", {}, `MAC addresses seen (${p.macs.length})`),
        h("table", {}, h("tbody", {}, p.macs.slice(0, 50).map((m) => h("tr", {}, h("td", {}, h("code", {}, m.mac)), h("td", {}, `VLAN ${m.vlan || "—"}`), h("td", {}, m.ip ? h("code", {}, m.ip) : ""),
          h("td", {}, p.status === "unlisted" && can("circuits", "manage") ? h("button", { type: "button", class: "small", onclick: () => adoptFound([m.mac]) }, "Add to the circuit list") : "")))))) : "");
  };
  // Group ports by everything but their last number (gi1/0/, te1/1/...), odd numbers on top like a switch.
  const groups = new Map();
  for (const p of d.ports) {
    const m = p.port_norm.match(/^(.*?)(\d+)$/);
    const key = m ? m[1] : p.port_norm;
    groups.set(key, [...(groups.get(key) || []), { ...p, num: m ? Number(m[2]) : 0 }]);
  }
  const plates = [...groups.entries()].map(([key, list]) => {
    const plate = h("div", { class: "faceplate" });
    list.sort((a, b) => a.num - b.num);
    const max = Math.max(...list.map((p) => p.num), 1);
    const byNum = new Map(list.map((p) => [p.num, p]));
    for (let n = 1; n <= max; n++) {
      const p = byNum.get(n);
      const col = Math.ceil(n / 2), row = n % 2 ? 1 : 2;
      const el = h("button", { type: "button", class: `port ${p ? PORT_STATUS[p.status][0] : "unused"}`, disabled: !p,
        title: p ? `${p.port}: ${PORT_STATUS[p.status][1]}${p.circuits[0] ? ` · ${p.circuits[0].device_name}` : ""}${p.macs.length ? ` · ${p.macs.length} MAC` : ""}` : `${key}${n}: nothing seen`,
        onclick: p ? (ev) => { show(p); ev.currentTarget.classList.add("sel"); } : null }, n);
      el.style.gridColumn = String(col);
      el.style.gridRow = String(row);
      plate.append(el);
    }
    return h("div", { class: "plate-group" }, h("div", { class: "muted" }, key || "ports"), plate);
  });
  const counts = Object.keys(PORT_STATUS).map((k) => [k, d.ports.filter((p) => p.status === k).length]).filter(([, n]) => n);
  pane.replaceChildren(
    h("p", { class: "muted" }, d.scanned_at ? `From the scan of ${fmtTime(d.scanned_at)} and the circuit list. ` : "Not scanned yet: from the circuit list only. ",
      d.scan_error ? h("span", { class: "errtext" }, `Last scan error: ${d.scan_error}`) : ""),
    h("div", { class: "port-key" }, ...counts.map(([k, n]) => h("span", {}, h("span", { class: `port ${PORT_STATUS[k][0]} key` }), ` ${PORT_STATUS[k][1]} (${n})`))),
    ...plates, info);
  const firstBad = d.ports.find((p) => p.status === "problem") || d.ports.find((p) => p.circuits.length);
  if (firstBad) show(firstBad);
}

// ---------- config compliance ----------

const CP_KIND = { must: "must have", must_not: "must not have" };

async function loadDeviceCompliance() {
  const pane = $("#detail-compliance");
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const rows = await api(`/api/compliance/device/${state.detailDevice.id}`);
    if (!rows.length) return pane.replaceChildren(h("p", { class: "empty" }, "No compliance rule applies to this device (or it hasn't been backed up yet)."));
    pane.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["Rule", "Result", "Since", "Config lines"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map((x) => h("tr", {},
        h("td", {}, x.rule, x.severity === "critical" ? h("small", { class: "sub errtext" }, "critical") : null),
        h("td", {}, h("span", { class: `badge ${x.passed ? "success" : "failed"}` }, x.passed ? "Pass" : "Fail")),
        h("td", {}, x.failing_since ? fmtTime(x.failing_since) : "—"),
        h("td", {}, x.detail === null ? h("span", { class: "muted" }, "needs Config backups: read configs") :
          x.detail ? h("pre", { class: "config small" }, (x.passed ? "" : x.kind === "must" ? "Missing:\n" : "Found:\n") + x.detail) : "—"))))));
  } catch (e) { pane.replaceChildren(h("p", { class: "error" }, e.message)); }
}

function cpDialog(...content) {
  $("#cp-dialog-body").replaceChildren(...content);
  if (!$("#cp-dialog").open) $("#cp-dialog").showModal();
}
$("#cp-dialog-close").addEventListener("click", () => { $("#cp-dialog").close(); loadBackups(); });

/** Every rule, how many devices pass and fail it, and the failures. */
async function openCompliance() {
  let d;
  try { d = await api("/api/compliance"); } catch (e) { return toast(e.message); }
  const failing = d.results.filter((x) => !x.passed);
  const devices = new Set(d.results.map((x) => x.device_id));
  const badDevices = new Set(failing.map((x) => x.device_id));
  const ruleOf = new Map(d.rules.map((r) => [r.id, r]));
  const call = async (fn, msg) => { try { const r = await fn(); if (msg) toast(msg(r)); openCompliance(); } catch (e) { toast(e.message); } };
  const tiles = h("div", { class: "tiles" },
    ...[["", "Rules", d.rules.length], ["success", "Devices compliant", devices.size - badDevices.size],
      ["failed", "Devices failing", badDevices.size], ["failed", "Critical failures", failing.filter((x) => (ruleOf.get(x.rule_id) || {}).severity === "critical").length]]
      .map(([cls, lbl, n]) => h("div", { class: `tile ${cls}` }, h("span", { class: "num" }, n), h("span", { class: "lbl" }, lbl))));
  const scope = (r) => [r.platforms.length ? r.platforms.map((p) => d.platforms[p] || p).join(", ") : "every platform",
    r.sites.length ? `sites ${r.sites.join(", ")}` : ""].filter(Boolean).join(" · ");
  const ruleRows = d.rules.map((r) => {
    const res = d.results.filter((x) => x.rule_id === r.id);
    const bad = res.filter((x) => !x.passed).length;
    return h("tr", { class: r.enabled ? "" : "disabled" },
      h("td", { class: "name" }, r.name, r.description ? h("small", {}, r.description) : null),
      h("td", {}, CP_KIND[r.kind], h("pre", { class: "config small" }, r.lines), r.regex ? h("small", { class: "sub" }, "patterns") : null),
      h("td", {}, scope(r)),
      h("td", {}, h("span", { class: `badge ${r.severity === "critical" ? "failed" : "changed"}` }, r.severity)),
      h("td", {}, r.enabled ? `${res.length - bad} pass, ${bad} fail` : "off"),
      h("td", { class: "actions" }, d.can_manage ? [
        h("button", { class: "small", onclick: () => cpRuleForm(d, r) }, "Edit"),
        h("button", { class: "small danger", onclick: () => { if (confirm(`Delete the rule ${r.name}?`)) call(() => api(`/api/compliance/rules/${r.id}`, { method: "DELETE" })); } }, "Delete")] : null));
  });
  const failRows = failing.sort((a, b) => a.device.localeCompare(b.device)).map((x) => {
    const r = ruleOf.get(x.rule_id) || { name: "?" };
    return h("tr", {},
      h("td", { class: "name" }, x.device, h("small", {}, x.site || "")),
      h("td", {}, r.name, r.severity === "critical" ? h("small", { class: "sub errtext" }, "critical") : null),
      h("td", {}, x.failing_since ? fmtTime(x.failing_since) : "—"),
      h("td", {}, x.detail === null ? h("span", { class: "muted" }, "—") : h("pre", { class: "config small" }, x.detail)));
  });
  cpDialog(tiles,
    h("p", { class: "muted" }, "Every device's config is checked after each backup. " +
      (d.can_read_lines ? "" : "The config lines of a result need Config backups: read configs.")),
    h("div", { class: "toolbar" },
      can("backups", "run") ? h("button", { type: "button", onclick: () => call(() => api("/api/compliance/check", { method: "POST" }), (r) => `Checked ${r.checked} device(s)`) }, "Check now") : null,
      h("a", { class: "button", href: "/api/compliance/export.csv", download: "" }, "Export CSV"),
      h("span", { class: "spacer" }),
      d.can_manage ? h("button", { type: "button", onclick: () => call(() => api("/api/compliance/examples", { method: "POST" }), (r) => `Added ${r.added.length} example rule(s)`) }, "Add example rules (Cisco IOS)") : null,
      d.can_manage ? h("button", { type: "button", class: "primary", onclick: () => cpRuleForm(d) }, "+ Add rule") : null),
    h("h3", {}, `Failing (${failing.length})`),
    failing.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Device", "Rule", "Failing since", "Config lines"].map((t) => h("th", {}, t)))), h("tbody", {}, failRows)))
      : h("p", { class: "muted" }, d.rules.length ? "Nothing fails." : "No rules yet."),
    h("h3", {}, `Rules (${d.rules.length})`),
    d.rules.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Rule", "Config", "Applies to", "Severity", "Devices", ""].map((t) => h("th", {}, t)))), h("tbody", {}, ruleRows)))
      : h("p", { class: "muted" }, "Add a rule, or start from the examples."));
}

function cpRuleForm(d, r = null) {
  const err = errorLine();
  const v = r || { name: "", description: "", kind: "must", lines: "", regex: false, platforms: [], sites: [], severity: "warning", enabled: true };
  const f = {
    name: h("input", { value: v.name, maxlength: 100, placeholder: "e.g. NTP server set" }),
    description: h("input", { value: v.description, maxlength: 2000 }),
    kind: h("select", {}, ...Object.entries(CP_KIND).map(([k, l]) => h("option", { value: k, selected: v.kind === k }, `The config ${l}`))),
    lines: h("textarea", { rows: 4, placeholder: "One config line per line, e.g.\nip ssh version 2\nservice password-encryption" }, v.lines),
    regex: h("input", { type: "checkbox", checked: v.regex }),
    sites: h("input", { value: v.sites.join(", "), placeholder: "Empty: every site" }),
    severity: h("select", {}, ...["warning", "critical"].map((x) => h("option", { value: x, selected: v.severity === x }, x))),
    enabled: h("input", { type: "checkbox", checked: v.enabled }),
  };
  const plats = h("div", { class: "chips" }, ...Object.entries(d.platforms).map(([k, l]) =>
    h("label", { class: "check" }, h("input", { type: "checkbox", "data-platform": k, checked: v.platforms.includes(k) }), ` ${l}`)));
  cpDialog(
    h("h3", {}, r ? `Rule: ${r.name}` : "New rule"),
    h("div", { class: "grid2" }, h("label", {}, "Name", f.name), h("label", {}, "Severity", f.severity)),
    h("label", {}, "What it checks", f.description),
    h("label", {}, "Kind", f.kind),
    h("label", {}, "Config lines", f.lines),
    h("label", { class: "check" }, f.regex, " The lines are patterns (regular expressions), searched in each config line"),
    h("p", { class: "muted" }, "Must have: every line must be in the config. Must not have: any of them fails it. Without patterns, a line matches when it is the same, ignoring spaces at either end."),
    h("label", {}, "Platforms (none ticked: every platform)"), plats,
    h("label", {}, "Sites (names, separated by commas)", f.sites),
    h("label", { class: "check" }, f.enabled, " On"),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onclick: () => openCompliance() }, "Cancel"),
      h("button", { type: "button", class: "primary", onclick: async () => {
        err.hidden = true;
        const body = { name: f.name.value, description: f.description.value, kind: f.kind.value, lines: f.lines.value,
          regex: f.regex.checked, severity: f.severity.value, enabled: f.enabled.checked,
          platforms: $$("input[data-platform]", plats).filter((c) => c.checked).map((c) => c.dataset.platform),
          sites: f.sites.value.split(",").map((x) => x.trim()).filter(Boolean) };
        try {
          await api(r ? `/api/compliance/rules/${r.id}` : "/api/compliance/rules", { method: r ? "PUT" : "POST", body });
          toast("Saved; every device checked again");
          openCompliance();
        } catch (e) { showError(err, e); }
      } }, "Save")));
}

$("#bk-compliance").addEventListener("click", openCompliance);

// ---------- shared: links to sites ----------

/** Sites by lower-case name and code, so any page can link a Site value to its site. */
async function loadSiteIndex() {
  const list = await api("/api/sites/index").catch(() => []);
  state.siteIndex = new Map();
  list.forEach((x) => { if (x.code) state.siteIndex.set(x.code.trim().toLowerCase(), x); });
  list.forEach((x) => state.siteIndex.set(x.name.trim().toLowerCase(), x)); // a name wins over a code
}

const siteOf = (text) => (text && state.siteIndex ? state.siteIndex.get(String(text).trim().toLowerCase()) : null);

/** A Site value as a link to its site (or plain text when it isn't on the site list). */
function siteLink(text, id = null) {
  const s = id ? { id, name: text } : siteOf(text);
  if (!text) return "—";
  if (!s) return h("span", { title: "Not on the site list" }, text);
  return h("span", { class: "link", title: "Open the site", onclick: (ev) => { ev.stopPropagation(); openSite(s.id); } }, text);
}

/** Go to the Sites page and open one site's page. */
async function openSite(id) {
  if (state.view !== "sites") switchView("sites");
  await site.loading;
  openSitePage(id);
}

/** Open the site page at an item's rack (or where the item is). */
async function showInRack(assetId) {
  try {
    const at = await api(`/api/racks/locate/${assetId}`);
    if (!at.site_id) return toast("Its Site isn't on the site list, so there's no rack view for it yet");
    if (state.view !== "sites") switchView("sites");
    await site.loading;
    openSitePage(at.site_id, at.location_id, at.rack_id);
  } catch (e) { toast(e.message); }
}

/** Go to the Inventory page and open one item. */
async function openItem(id) {
  if ($("#site-dialog").open) $("#site-dialog").close();
  switchView("inventory");
  await state.viewLoading;
  const r = inv.rows.find((x) => x.id === id);
  if (r) invEdit(r);
}

/** Go to the Circuits page, showing one site's circuits. */
function openSiteCircuits(id) {
  ct.siteFilter = String(id);
  if ($("#site-dialog").open) $("#site-dialog").close();
  switchView("circuits");
}

// ---------- maintenance calendar ----------

const cal = { month: null, mode: "month", site: "", items: [], kinds: {}, devices: null, siteNames: [] };
const CAL_LEGEND = [["upgrade", "Upgrade (live)"], ["dry_run", "Upgrade (dry run)"], ["change", "Change"],
  ["maintenance", "Maintenance"], ["outage", "Outage"], ["freeze", "Change freeze"], ["meraki", "Meraki upgrade"]];
const utcDate = (v) => new Date(v.endsWith("Z") || v.includes("+") ? v : v + "Z");
const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const isoUtc = (d) => d.toISOString().slice(0, 19);
const hhmm = (d) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** The period shown: six weeks around the month (Mondays first), or the next 60 days. */
function calPeriod() {
  if (cal.mode === "list") {
    const from = dayStart(cal.month.getMonth() === new Date().getMonth() && cal.month.getFullYear() === new Date().getFullYear() ? new Date() : cal.month);
    return [from, addDays(from, 60)];
  }
  const first = new Date(cal.month.getFullYear(), cal.month.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  return [start, addDays(start, 42)];
}

async function loadCalendar() {
  if (!cal.month) cal.month = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  cal.siteNames = [...new Map([...(state.siteIndex || new Map()).values()].map((x) => [x.id, x.name])).values()].sort();
  const sel = $("#cal-site");
  if (sel.options.length !== cal.siteNames.length + 1) {
    sel.replaceChildren(h("option", { value: "" }, "Every site"), ...cal.siteNames.map((n) => h("option", { value: n }, n)));
    sel.value = cal.site;
  }
  $("#cal-legend").replaceChildren(...CAL_LEGEND.map(([k, label]) => h("span", { class: `cal-item k-${k}` }, label)),
    h("span", { class: "cal-item clash" }, "⚠ clashes with something"));
  const [from, to] = calPeriod();
  const q = new URLSearchParams({ start: isoUtc(from), end: isoUtc(to), site: cal.site });
  $("#cal-ics").href = `/api/calendar/export.ics?${q}`;
  $("#cal-title").textContent = cal.mode === "month"
    ? cal.month.toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : `${from.toLocaleDateString()} – ${addDays(to, -1).toLocaleDateString()}`;
  try {
    const r = await api(`/api/calendar?${q}`);
    cal.items = r.items.map((x) => ({ ...x, s: utcDate(x.start), e: utcDate(x.end) }));
    cal.kinds = r.kinds;
  } catch (e) { return toast(e.message); }
  const clashes = cal.items.filter((x) => x.clashes.length);
  $("#cal-clash-note").hidden = !clashes.length;
  $("#cal-clash-note").textContent = clashes.length
    ? `⚠ ${clashes.length} item(s) clash: the same device or site at the same time, or work during a change freeze. Click one to see what with.` : "";
  (cal.mode === "month" ? calMonth : calList)();
}

function calChip(x, day = null) {
  const cont = day && x.s < day ? "… " : "";
  const time = day && x.s >= day ? `${hhmm(x.s)} ` : "";
  return h("button", { class: `cal-item k-${x.kind}${x.clashes.length ? " clash" : ""}`,
    title: `${x.kind_label}: ${x.title}\n${fmtTime(x.start)} – ${fmtTime(x.end)}${x.sites.length ? `\n${x.sites.join(", ")}` : ""}${x.clashes.length ? "\n⚠ clashes with something" : ""}`,
    onclick: () => calOpen(x) }, `${x.clashes.length ? "⚠ " : ""}${cont}${time}${x.title}`);
}

function calMonth() {
  const [from] = calPeriod();
  const today = dayStart(new Date()).getTime();
  const cells = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => h("div", { class: "dow" }, d));
  for (let i = 0; i < 42; i++) {
    const day = addDays(from, i), next = addDays(day, 1);
    const here = cal.items.filter((x) => x.s < next && x.e > day);
    const shown = here.slice(0, 4);
    cells.push(h("div", { class: `cal-day${day.getMonth() !== cal.month.getMonth() ? " other" : ""}${day.getTime() === today ? " today" : ""}` },
      h("span", { class: "num" }, day.getDate()),
      ...shown.map((x) => calChip(x, day)),
      here.length > shown.length ? h("span", { class: "cal-more", onclick: () => { cal.mode = "list"; $("#cal-mode").value = "list"; cal.month = day; loadCalendar(); } },
        `+${here.length - shown.length} more`) : null));
  }
  $("#cal-body").replaceChildren(h("div", { class: "cal-grid" }, cells));
}

function calList() {
  if (!cal.items.length) return $("#cal-body").replaceChildren(h("p", { class: "empty" }, "Nothing planned in this period."));
  const byKey = new Map(cal.items.map((x) => [x.key, x]));
  $("#cal-body").replaceChildren(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ...["When", "What", "", "Sites", "Devices", "Change", "Clashes with"].map((t) => h("th", {}, t)))),
    h("tbody", {}, cal.items.map((x) => h("tr", {},
      h("td", {}, `${fmtTime(x.start)} – ${x.s.toDateString() === x.e.toDateString() ? hhmm(x.e) : fmtTime(x.end)}`),
      h("td", {}, h("span", { class: `cal-item k-${x.kind}` }, x.kind_label)),
      h("td", {}, h("span", { class: "link", onclick: () => calOpen(x) }, x.title)),
      h("td", {}, ...(x.sites.length ? x.sites.flatMap((n, i) => [i ? ", " : "", siteLink(n)]) : ["Every site"])),
      h("td", {}, x.devices.map((d) => d.name).join(", ") || "—"),
      h("td", {}, x.change_ref || "—"),
      h("td", {}, x.clashes.length ? h("span", { class: "badge failed" }, x.clashes.map((k) => byKey.get(k)?.title || "another item").join("; ")) : "—")))))));
}

function calOpen(x) {
  if (x.source === "upgrade") return openJob(x.id);
  const byKey = new Map(cal.items.map((i) => [i.key, i]));
  const row = (label, value) => value ? h("p", {}, h("strong", {}, `${label}: `), value) : null;
  $("#cal-dialog-title").textContent = `${x.kind_label}: ${x.title}`;
  $("#cal-dialog-body").replaceChildren(...[
    row("When", `${fmtTime(x.start)} – ${fmtTime(x.end)}`),
    row("Sites", x.sites.join(", ") || "Every site"),
    row("Devices", x.devices.map((d) => d.name).join(", ")),
    row("Change", x.change_ref),
    x.notes ? h("p", { class: "pre-wrap" }, x.notes) : null,
    x.clashes.length ? h("p", { class: "notice" }, "⚠ Clashes with: ", ...x.clashes.map((k) => byKey.get(k)).filter(Boolean)
      .flatMap((o, i) => [i ? "; " : "", h("span", { class: "link", onclick: () => calOpen(o) }, `${o.kind_label}: ${o.title} (${fmtTime(o.start)})`)])) : null,
    h("p", { class: "muted" }, `Added by ${x.created_by}${x.updated_by && x.updated_by !== x.created_by ? `, last changed by ${x.updated_by}` : ""}`),
    x.source === "event" && can("inventory", "manage") ? h("div", { class: "dialog-actions" },
      h("button", { class: "danger", onclick: async () => {
        if (!confirm(`Delete "${x.title}" from the calendar?`)) return;
        try { await api(`/api/calendar/events/${x.id}`, { method: "DELETE" }); $("#cal-dialog").close(); loadCalendar(); } catch (e) { toast(e.message); }
      } }, "Delete"),
      h("button", { title: "A new item like this one", onclick: () => calEdit(x) }, "Copy"),
      h("button", { class: "primary", onclick: () => calEdit(x, true) }, "Edit")) : null].filter(Boolean));
  if (!$("#cal-dialog").open) $("#cal-dialog").showModal();
}

async function calEdit(x = null, editing = false) {
  if (!cal.devices) cal.devices = await api("/api/devices").catch(() => []);
  const now = new Date(); now.setMinutes(0, 0, 0);
  const start = x ? x.s : addDays(dayStart(now), 1), end = x ? x.e : new Date(start.getTime() + 3600000);
  if (!x) start.setHours(20), end.setTime(start.getTime() + 2 * 3600000);
  const f = {
    title: h("input", { value: x ? x.title : "", maxlength: 200, required: true }),
    kind: h("select", {}, ...Object.entries(cal.kinds).map(([k, label]) => h("option", { value: k, selected: x ? x.kind === k : k === "change" }, label))),
    start: h("input", { type: "datetime-local", value: toLocalInput(start), required: true }),
    end: h("input", { type: "datetime-local", value: toLocalInput(end), required: true }),
    change_ref: h("input", { value: x ? x.change_ref : "", maxlength: 100, placeholder: "e.g. CHG0012345" }),
    notes: h("textarea", { rows: 3, maxlength: 5000 }, x ? x.notes : ""),
  };
  const siteBoxes = cal.siteNames.map((n) => h("label", { class: "check" },
    h("input", { type: "checkbox", value: n, checked: x ? x.sites.includes(n) : n === cal.site }), n));
  const chosen = new Set(x ? x.devices.map((d) => d.id) : []);
  const devBoxes = [...cal.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    .map((d) => h("label", { class: "check", title: d.site || "" }, h("input", { type: "checkbox", value: d.id, checked: chosen.has(d.id) }), d.name));
  const save = async (ev) => {
    ev.preventDefault();
    const body = { title: f.title.value, kind: f.kind.value, start: isoUtc(new Date(f.start.value)), end: isoUtc(new Date(f.end.value)),
      sites: siteBoxes.map((l) => l.firstChild).filter((c) => c.checked).map((c) => c.value),
      devices: devBoxes.map((l) => l.firstChild).filter((c) => c.checked).map((c) => Number(c.value)),
      change_ref: f.change_ref.value, notes: f.notes.value };
    try {
      await api(editing ? `/api/calendar/events/${x.id}` : "/api/calendar/events", { method: editing ? "PUT" : "POST", body });
      $("#cal-dialog").close();
      cal.month = new Date(new Date(f.start.value).getFullYear(), new Date(f.start.value).getMonth(), 1);
      if (cal.mode === "list") cal.month = new Date(f.start.value);
      loadCalendar();
    } catch (e) { toast(e.message); }
  };
  $("#cal-dialog-title").textContent = editing ? "Change calendar item" : "Add to the calendar";
  $("#cal-dialog-body").replaceChildren(h("form", { class: "form", onsubmit: save },
    h("label", {}, "What", f.title),
    h("div", { class: "grid2" }, h("label", {}, "Kind", f.kind), h("label", {}, "Change reference", f.change_ref)),
    h("div", { class: "grid2" }, h("label", {}, "Starts", f.start), h("label", {}, "Ends", f.end)),
    h("div", {}, h("span", {}, "Sites "), h("span", { class: "muted" }, "(none ticked: every site; a change freeze then covers everything)"),
      h("div", { class: "cal-check-list" }, siteBoxes.length ? siteBoxes : h("span", { class: "muted" }, "No sites on the site list"))),
    h("div", {}, h("span", {}, "Devices "), h("span", { class: "muted" }, "(optional)"), h("div", { class: "cal-check-list" }, devBoxes)),
    h("label", {}, "Notes", f.notes),
    h("div", { class: "dialog-actions" }, h("button", { type: "submit", class: "primary" }, editing ? "Save" : "Add"))));
  if (!$("#cal-dialog").open) $("#cal-dialog").showModal();
  f.title.focus();
}

$("#cal-prev").addEventListener("click", () => {
  cal.month = cal.mode === "month" ? new Date(cal.month.getFullYear(), cal.month.getMonth() - 1, 1) : addDays(calPeriod()[0], -60);
  loadCalendar();
});
$("#cal-next").addEventListener("click", () => {
  cal.month = cal.mode === "month" ? new Date(cal.month.getFullYear(), cal.month.getMonth() + 1, 1) : calPeriod()[1];
  loadCalendar();
});
$("#cal-today").addEventListener("click", () => { cal.month = new Date(new Date().getFullYear(), new Date().getMonth(), 1); loadCalendar(); });
$("#cal-mode").addEventListener("change", () => {
  cal.mode = $("#cal-mode").value;
  if (cal.mode === "month") cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth(), 1);
  loadCalendar();
});
$("#cal-site").addEventListener("change", () => { cal.site = $("#cal-site").value; loadCalendar(); });
$("#cal-add").addEventListener("click", () => calEdit());
$("#cal-dialog-close").addEventListener("click", () => $("#cal-dialog").close());
// ---------- topology map ----------

const topo = { siteId: 0, data: null, pos: new Map(), svg: null, sel: null, mon: new Map(), load: new Map() };
const SVGNS = "http://www.w3.org/2000/svg";
const TOPO_W = 150, TOPO_H = 46, TOPO_DX = 190, TOPO_DY = 130;

function svgEl(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) el.append(k instanceof Node ? k : document.createTextNode(k));
  return el;
}

/** Open the network map, for one site or (0) every site. */
async function openTopology(siteId = 0) {
  topo.siteId = Number(siteId) || 0;
  const sites = [...new Map([...(state.siteIndex || new Map()).values()].map((x) => [x.id, x])).values()]
    .sort((a, b) => a.name.localeCompare(b.name));
  $("#topo-site").replaceChildren(h("option", { value: "0" }, "Every site"),
    ...sites.map((x) => h("option", { value: String(x.id) }, x.name)));
  $("#topo-site").value = String(topo.siteId);
  $("#topo-dialog").showModal();
  await loadTopology();
}

async function loadTopology() {
  const q = new URLSearchParams({ site_id: topo.siteId, endpoints: $("#topo-endpoints").checked });
  try {
    [topo.data, topo.mon] = await Promise.all([api(`/api/topology?${q}`), monStatesForMap()]);
    topo.load = await monLinkLoad(topo.data);
  } catch (e) { return toast(e.message); }
  topo.pos = new Map(Object.entries(topo.data.positions).map(([k, p]) => [k, { ...p }]));
  if (!topo.portsChosen) $("#topo-ports").checked = topo.data.edges.length <= 25; // busy maps: no port names
  topoArrange(false);
  const d = topo.data;
  const parts = [d.last_scan ? `From the network scan of ${fmtTime(d.last_scan)}.` : "No network scan yet: run one on the Circuits page."];
  if (d.not_read.length) parts.push(`Not read yet (orange outline): ${d.not_read.join(", ")}.`);
  if (topo.mon.size) {
    const down = d.nodes.filter((n) => topo.mon.get(n.id)?.status === "down").map((n) => n.name);
    parts.push(down.length ? `DOWN now (red): ${down.join(", ")}.` : "Every monitored device on the map is answering.");
  }
  if (topo.load.size) parts.push("Lines show the busier end's load: orange from 50%, red from 80%.");
  const ends = d.nodes.reduce((n, x) => n + (x.endpoints || 0), 0);
  if (ends && !$("#topo-endpoints").checked) parts.push(`${ends} phone(s) and access point(s) not shown.`);
  if (!d.nodes.length) parts.push("No devices at this site.");
  $("#topo-note").textContent = parts.join(" ");
  $("#topo-info").textContent = "Click a line to see its ports, a box to open the device. Drag the boxes to tidy the map.";
  topoDraw();
}

/** Place boxes in rows: what the site connects out to on top (other sites, routers not in
 * the inventory), then each hop further down. On the every-site map each site gets its own
 * block. Boxes someone placed keep their place unless all = true. */
function topoArrange(all) {
  const { nodes, edges } = topo.data;
  const adj = new Map(nodes.map((n) => [n.key, new Set()]));
  edges.forEach((e) => { adj.get(e.a)?.add(e.b); adj.get(e.b)?.add(e.a); });
  const groups = new Map();
  if (topo.siteId) {
    groups.set("", nodes);
  } else {
    const siteOfNode = new Map(nodes.filter((n) => n.kind === "device").map((n) => [n.key, n.site || "No site"]));
    for (const n of nodes) {
      const g = siteOfNode.get(n.key) || siteOfNode.get([...adj.get(n.key)].find((x) => siteOfNode.has(x))) || "No site";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(n);
    }
  }
  let x0 = 40;
  for (const name of [...groups.keys()].sort((a, b) => a.localeCompare(b))) {
    x0 += topoArrangeGroup(groups.get(name), adj, x0, all) + TOPO_DX - TOPO_W + 40;
  }
}

function topoArrangeGroup(nodes, adj, x0, all) {
  const inGroup = new Set(nodes.map((n) => n.key));
  const kind = new Map(nodes.map((n) => [n.key, n.kind]));
  const near = (k) => [...adj.get(k)].filter((x) => inGroup.has(x));
  let roots = nodes.filter((n) => n.kind === "other_site" || n.kind === "unmanaged").map((n) => n.key);
  if (!roots.length) {
    const deg = (k) => near(k).filter((x) => kind.get(x) !== "endpoint").length;
    const max = Math.max(0, ...nodes.filter((n) => n.kind === "device").map((n) => deg(n.key)));
    roots = nodes.filter((n) => n.kind === "device" && deg(n.key) === max && max > 0).map((n) => n.key);
  }
  const level = new Map(roots.map((k) => [k, 0]));
  const queue = [...roots];
  while (queue.length) {
    const k = queue.shift();
    for (const x of near(k).sort()) {
      if (!level.has(x)) { level.set(x, level.get(k) + 1); queue.push(x); }
    }
  }
  const maxLevel = Math.max(0, ...level.values());
  nodes.forEach((n) => { if (!level.has(n.key)) level.set(n.key, maxLevel + 1); }); // not connected
  const rows = new Map();
  [...nodes].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    .forEach((n) => { const l = level.get(n.key); if (!rows.has(l)) rows.set(l, []); rows.get(l).push(n.key); });
  const order = new Map();
  const widest = Math.max(1, ...[...rows.values()].map((row) => row.length));
  [...rows.keys()].sort((a, b) => a - b).forEach((l) => {
    const row = rows.get(l);
    // under the boxes they hang from, to keep lines from crossing
    const above = (k) => { const xs = near(k).filter((x) => level.get(x) < l && order.has(x)).map((x) => order.get(x));
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : Infinity; };
    row.sort((a, b) => above(a) - above(b));
    const offset = (widest - row.length) / 2;
    row.forEach((k, i) => {
      order.set(k, offset + i);
      if (all || !topo.pos.has(k)) topo.pos.set(k, { x: Math.round(x0 + (offset + i) * TOPO_DX), y: Math.round(50 + l * TOPO_DY) });
    });
  });
  return (widest - 1) * TOPO_DX + TOPO_W;
}

function topoDraw() {
  const { nodes, edges } = topo.data;
  const byKey = new Map(nodes.map((n) => [n.key, n]));
  const pts = [...topo.pos.values()];
  const width = Math.max(600, ...pts.map((p) => p.x + TOPO_W + 40));
  const height = Math.max(300, ...pts.map((p) => p.y + TOPO_H + 40));
  const centre = (k) => { const p = topo.pos.get(k); return [p.x + TOPO_W / 2, p.y + TOPO_H / 2]; };
  const portLoad = (node, port) => { const n = byKey.get(node); return n && n.id !== undefined ? topo.load.get(`${n.id}|${port}`) : null; };
  const edgeEls = edges.map((e) => {
    const ends = e.links.flatMap((l) => [portLoad(e.a, l.a_port), portLoad(e.b, l.b_port)]).filter(Boolean);
    const util = ends.length && ends.some((p) => p.util !== null) ? Math.max(...ends.map((p) => p.util ?? 0)) : null;
    const loadCls = util === null ? "" : util >= 0.8 ? " load-hi" : util >= 0.5 ? " load-mid" : " load-ok";
    const g = svgEl("g", { class: `topo-edge${e.links.length > 1 ? " multi" : ""}${loadCls}` });
    const vis = svgEl("line", { class: "vis" }), hit = svgEl("line", { class: "hit" });
    const label = svgEl("text", { "text-anchor": "middle" });
    const portA = svgEl("text", { "text-anchor": "middle", class: "port" }), portB = svgEl("text", { "text-anchor": "middle", class: "port" });
    const place = () => {
      const [x1, y1] = centre(e.a), [x2, y2] = centre(e.b);
      for (const l of [vis, hit]) { l.setAttribute("x1", x1); l.setAttribute("y1", y1); l.setAttribute("x2", x2); l.setAttribute("y2", y2); }
      label.setAttribute("x", (x1 + x2) / 2); label.setAttribute("y", (y1 + y2) / 2 - 4);
      label.textContent = [e.links.length > 1 ? `×${e.links.length}` : "", util !== null ? `${Math.round(util * 100)}%` : ""].filter(Boolean).join(" ");
      const at = (t) => [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t];
      const one = e.links.length === 1;
      const [ax, ay] = at(0.3), [bx, by] = at(0.7);
      portA.setAttribute("x", ax); portA.setAttribute("y", ay); portA.textContent = one ? shortPort(e.links[0].a_port) : "";
      portB.setAttribute("x", bx); portB.setAttribute("y", by); portB.textContent = one ? shortPort(e.links[0].b_port) : "";
    };
    place();
    const select = () => {
      $$("#topo-wrap .topo-edge.sel").forEach((x) => x.classList.remove("sel"));
      g.classList.add("sel");
      const a = byKey.get(e.a).name, b = byKey.get(e.b).name;
      const loadOf = (node, port) => { const p = portLoad(node, port); return p && p.util !== null ? ` (${Math.round(p.util * 100)}%: in ${fmtBps(p.in_bps)}, out ${fmtBps(p.out_bps)}${p.errors ? `, ${p.errors} errors/min` : ""})` : ""; };
      $("#topo-info").textContent = `${a} ↔ ${b}: ` + e.links.map((l) => `${a} ${l.a_port || "?"}${loadOf(e.a, l.a_port)} — ${b} ${l.b_port || "?"}${loadOf(e.b, l.b_port)}`).join(" · ");
    };
    hit.addEventListener("click", select);
    g.append(vis, hit, label, portA, portB);
    return { e, g, place };
  });
  const nodeEls = nodes.map((n) => {
    const p = topo.pos.get(n.key);
    const sub = n.kind === "other_site" ? (n.site || "another site")
      : n.kind === "unmanaged" ? "not in the inventory"
      : n.kind === "endpoint" ? "phone or access point"
      : [platformLabel(n.platform), n.endpoints ? `+${n.endpoints} phones/APs` : ""].filter(Boolean).join(" · ");
    const m = n.id !== undefined && n.kind !== "unmanaged" && n.kind !== "endpoint" ? topo.mon.get(n.id) : null;
    const g = svgEl("g", { class: `topo-node ${n.kind}${n.kind === "device" && !n.read ? " not-read" : ""}${m ? ` mon-${m.status}` : ""}`, transform: `translate(${p.x},${p.y})` },
      svgEl("title", {}, [n.name, n.address, n.platform, m && `Monitoring: ${m.status_label}${m.reason ? ` (${m.reason})` : ""}`, n.read_error && `Scan: ${n.read_error}`].filter(Boolean).join("\n")),
      svgEl("rect", { width: TOPO_W, height: TOPO_H, rx: 6 }),
      svgEl("text", { x: 10, y: 19 }, n.name.length > 20 ? n.name.slice(0, 19) + "…" : n.name),
      svgEl("text", { x: 10, y: 36, class: "sub" }, sub.length > 26 ? sub.slice(0, 25) + "…" : sub));
    topoDrag(g, n, () => edgeEls.filter((x) => x.e.a === n.key || x.e.b === n.key).forEach((x) => x.place()));
    return g;
  });
  const titles = [];
  if (!topo.siteId) { // the every-site map: each site's name over its boxes
    const bySite = new Map();
    nodes.filter((n) => n.kind === "device").forEach((n) => {
      const p = topo.pos.get(n.key), k = n.site || "No site", b = bySite.get(k);
      bySite.set(k, b ? { x: Math.min(b.x, p.x), y: Math.min(b.y, p.y) } : { x: p.x, y: p.y });
    });
    bySite.forEach((p, name) => titles.push(svgEl("text", { x: p.x, y: 26, class: "topo-site" }, name)));
  }
  topo.svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Network map",
    class: $("#topo-ports").checked ? "" : "no-ports" }, titles, edgeEls.map((x) => x.g), nodeEls);
  $("#topo-wrap").replaceChildren(topo.svg);
}

/** 'GigabitEthernet1/0/48' -> 'Gi1/0/48', 'Ethernet1/49' -> 'Eth1/49': short labels on the lines. */
function shortPort(p) {
  return (p || "").replace(/^GigabitEthernet/i, "Gi").replace(/^TenGigabitEthernet/i, "Te")
    .replace(/^TwentyFiveGigE/i, "Twe").replace(/^HundredGigE/i, "Hu").replace(/^FortyGigabitEthernet/i, "Fo")
    .replace(/^Ethernet/i, "Eth");
}

function platformLabel(p) {
  return (state.platforms || []).find((x) => x.key === p || x.id === p)?.label || p || "";
}

function topoDrag(g, n, moved) {
  let start = null, clicked = true;
  g.addEventListener("pointerdown", (ev) => {
    const p = topo.pos.get(n.key);
    start = { x: ev.clientX, y: ev.clientY, px: p.x, py: p.y };
    clicked = true;
    g.setPointerCapture(ev.pointerId);
    g.classList.add("dragging");
  });
  g.addEventListener("pointermove", (ev) => {
    if (!start) return;
    const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) clicked = false;
    const p = { x: Math.max(0, Math.round(start.px + dx)), y: Math.max(0, Math.round(start.py + dy)) };
    topo.pos.set(n.key, p);
    g.setAttribute("transform", `translate(${p.x},${p.y})`);
    moved();
  });
  g.addEventListener("pointerup", () => {
    if (!start) return;
    start = null;
    g.classList.remove("dragging");
    if (clicked) topoOpen(n);
    else topoDraw(); // grow the drawing if a box went past its edge
  });
}

function topoOpen(n) {
  if (n.kind === "device" || n.kind === "other_site") {
    if (n.kind === "other_site" && n.site_id && confirm(`Show the map of ${n.site}?`)) {
      topo.siteId = n.site_id;
      $("#topo-site").value = String(n.site_id);
      return loadTopology();
    }
    const tabs = $$("#detail-tabs button").filter((b) => !b.hidden && !b.classList.contains("locked"));
    if (!tabs.length) return;
    openDetail({ device: { id: n.id, name: n.name, address: n.address || "" } });
    selectDetailTab(tabs.find((b) => b.dataset.tab === "ports") ? "ports" : tabs[0].dataset.tab);
  } else {
    $("#topo-info").textContent = `${n.name}: ${[n.platform, n.address].filter(Boolean).join(" · ") || "no details"} (not in the inventory).`;
  }
}

function topoSvgFile() {
  const clone = topo.svg.cloneNode(true);
  const live = topo.svg.querySelectorAll("*"), copy = clone.querySelectorAll("*");
  live.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const keep = ["fill", "stroke", "stroke-width", "stroke-dasharray", "font-size", "font-family", "paint-order"];
    copy[i].setAttribute("style", keep.map((k) => `${k}:${cs.getPropertyValue(k)}`).join(";"));
  });
  clone.setAttribute("xmlns", SVGNS);
  clone.insertBefore(svgEl("rect", { width: "100%", height: "100%", fill: getComputedStyle($("#topo-wrap")).backgroundColor }), clone.firstChild);
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" });
  const a = h("a", { href: URL.createObjectURL(blob), download: `network-map-${$("#topo-site").selectedOptions[0].text.replace(/\W+/g, "-")}.svg` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

$("#topo-close").addEventListener("click", () => $("#topo-dialog").close());
$("#topo-site").addEventListener("change", () => { topo.siteId = Number($("#topo-site").value); loadTopology(); });
$("#topo-endpoints").addEventListener("change", loadTopology);
$("#topo-ports").addEventListener("change", () => { topo.portsChosen = true; topo.svg?.classList.toggle("no-ports", !$("#topo-ports").checked); });
$("#topo-auto").addEventListener("click", () => { topoArrange(true); topoDraw(); });
$("#topo-svg").addEventListener("click", topoSvgFile);
$("#topo-save").addEventListener("click", async () => {
  try {
    await api("/api/topology/positions", { method: "PUT", body: { site_id: topo.siteId, positions: Object.fromEntries(topo.pos) } });
    toast("Layout saved for everyone");
  } catch (e) { toast(e.message); }
});
$("#site-map").addEventListener("click", () => openTopology(0));
$("#sp-map").addEventListener("click", () => openTopology(sp.siteId));

// ---------- shared: column chooser and blank templates ----------

function saveLocal(key, value) {
  try {
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* private window */ }
}

/** Tick and order columns. `all`: [{key, label, group, help}]; `shown`: keys shown now. */
function chooseColumns(dialog, close, all, shown, save, reset, note = "") {
  shown = [...shown];
  const order = [...shown, ...all.map((f) => f.key).filter((k) => !shown.includes(k))];
  const byKey = new Map(all.map((f) => [f.key, f]));
  const list = h("ul", { class: "col-list" });
  const draw = () => list.replaceChildren(...order.map((k, i) => h("li", {},
    h("input", { type: "checkbox", checked: shown.includes(k), "aria-label": byKey.get(k).label, onchange: (ev) => {
      if (ev.target.checked) shown.push(k); else shown.splice(shown.indexOf(k), 1);
    } }),
    h("span", {}, byKey.get(k).label, h("small", { class: "muted" }, ` ${byKey.get(k).group}${byKey.get(k).help ? `: ${byKey.get(k).help}` : ""}`)),
    h("span", { class: "spacer" }),
    h("button", { type: "button", class: "small ghost", title: "Move up", disabled: i === 0, onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; draw(); } }, "↑"),
    h("button", { type: "button", class: "small ghost", title: "Move down", disabled: i === order.length - 1, onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; draw(); } }, "↓"))));
  draw();
  dialog("Columns",
    h("p", { class: "muted" }, "Tick the columns you want to see and put them in order. This is remembered for you in this browser; others keep their own. " + note),
    list,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onclick: () => { reset(); close(); } }, "Reset to the defaults"),
      h("button", { type: "button", class: "primary", onclick: () => { save(order.filter((k) => shown.includes(k))); close(); } }, "Apply")));
}

/** Download a blank sheet with the column names: the columns you see, or all of them. */
function templateDialog(dialog, base, seen, note) {
  const which = h("select", {}, h("option", { value: "seen" }, "The columns I see"), h("option", { value: "all" }, "Every column"));
  const csv = h("a", { class: "button", download: "" }, "CSV");
  const xlsx = h("a", { class: "button", download: "" }, "Excel");
  const update = () => {
    const q = which.value === "seen" && seen.length ? `?columns=${encodeURIComponent(seen.join(","))}` : "";
    csv.href = `${base}/template.csv${q}`;
    xlsx.href = `${base}/template.xlsx${q}`;
  };
  which.addEventListener("change", update);
  update();
  dialog("Blank template",
    h("p", { class: "muted" }, "A sheet with only the column names, in a format the import reads. " + note),
    h("p", { class: "muted" }, "The Excel version also has a second sheet on how to fill it in, and pick-lists on columns that take set values."),
    h("label", {}, "Columns", which),
    h("div", { class: "dialog-actions" }, csv, xlsx));
}

// ---------- circuits ----------

const ct = { rows: [], imp: null, pending: null, meta: null, tab: "list", found: [], file: null };
const ctColsKey = () => `circuit-columns:${state.user ? state.user.username : ""}`;
const sub = (text) => (text ? h("small", { class: "sub" }, text) : null);
const ctCode = (v) => h("code", {}, v || "—");

/* The columns you can show. "Combined" ones put two or three values in one cell (the
   default view); every value also has its own column, and admins add custom ones. */
const CT_COMBINED = [
  { key: "@service", label: "Service", help: "Service, IP partition", fields: ["service", "ip_partition"],
    cell: (r) => [r.service || "—", sub(r.ip_partition)] },
  { key: "@device", label: "Device", help: "Device name, engineering prefix, warnings", fields: ["device_name", "eng_prefix"], cls: "name",
    cell: (r) => [r.device_name || "—", r.eng_prefix ? h("small", {}, r.eng_prefix) : null,
      r.warnings ? h("span", { class: "errtext" }, `⚠ ${r.warnings}`) : null] },
  { key: "@type", label: "Type / make", help: "Device type, manufacturer", fields: ["device_type", "manufacturer"],
    cell: (r) => [r.device_type || "—", sub(r.manufacturer)] },
  { key: "@site", label: "Site", help: "The list's Site, else the site of the switch it is on; links to the site", fields: ["site"],
    cell: (r) => [r.site_id ? siteLink(r.site_name, r.site_id) : r.site_text || "—",
      r.site_text && !r.site_id ? sub("not on the site list") : sub({ switch: "from its switch", network: "from where it was found" }[r.site_from])] },
  { key: "@location", label: "Location", help: "Room / area, floor", fields: ["room", "floor"],
    cell: (r) => [r.room || "—", sub(r.floor)] },
  { key: "@ip", label: "IP", help: "IP address, gateway and mask", fields: ["ip", "gateway", "mask"],
    cell: (r) => [ctCode(r.ip), r.gateway ? sub(`gw ${r.gateway} / ${r.mask}`) : null] },
  { key: "@vlan", label: "VLAN", help: "VLAN, connection type", fields: ["vlan", "conn_type"],
    cell: (r) => [r.vlan || "—", sub(r.conn_type)] },
  { key: "@switch", label: "Switch / port (list)", help: "DEVICE and PORT from the list, and the inventory device it links to", fields: ["switch", "port"],
    cell: (r) => [r.switch || r.port ? h("code", {}, `${r.switch || "?"} ${r.port || ""}`) : "—",
      sub(r.match === "matched" ? `→ ${r.switch_device_name}` : CT_MATCH[r.match])] },
  { key: "@live", label: "On the network", help: "Where the last scan found it", fields: [], live: true },
  { key: "@drawing", label: "Drawing", help: "Drawing number, device drawing reference", fields: ["drawing_number", "drawing_ref"],
    cell: (r) => [r.drawing_number || "—", sub(r.drawing_ref)] },
];
const CT_DEFAULT = ["@service", "@device", "@type", "mac", "@site", "@location", "@ip", "@vlan", "@switch", "@live", "@drawing"];

function ctAllColumns() {
  const fields = ct.meta ? ct.meta.fields : [];
  return [
    ...CT_COMBINED.map((c) => ({ ...c, group: "Combined" })),
    ...fields.map((f) => ({ key: f.key, label: f.label, group: f.custom ? "Custom" : "One value", fields: [f.key],
      cell: (r) => (["mac", "ip", "gateway", "mask", "port", "switch"].includes(f.key) ? ctCode(r[f.key]) : r[f.key] || "—") })),
    { key: "warnings", label: "Warnings", group: "One value", fields: [], cell: (r) => (r.warnings ? h("span", { class: "errtext" }, r.warnings) : "—") },
  ];
}

/** The columns this person chose (and their order); the defaults until they choose. */
function ctColumns() {
  const all = new Map(ctAllColumns().map((c) => [c.key, c]));
  let keys = null;
  try { keys = JSON.parse(localStorage.getItem(ctColsKey()) || "null"); } catch { keys = null; }
  if (!Array.isArray(keys)) keys = CT_DEFAULT;
  return keys.filter((k) => all.has(k)).map((k) => all.get(k));
}

function ctDialog(title, ...content) {
  $("#ct-dialog-title").textContent = title;
  $("#ct-dialog-body").replaceChildren(...content);
  if (!$("#ct-dialog").open) $("#ct-dialog").showModal();
}
$("#ct-dialog-close").addEventListener("click", () => $("#ct-dialog").close());

const CT_MATCH = { matched: "Linked", unmatched: "Switch not in inventory", ambiguous: "Several devices match", none: "No switch" };
const CT_LIVE_CLS = { matches: "success", moved: "failed", found: "changed", not_seen: "never", several: "changed", no_address: "never" };

async function loadCircuits() {
  loadFound();
  loadCarriers();
  try {
    const [data, meta] = await Promise.all([api("/api/circuits"), api("/api/circuits/meta")]);
    ct.meta = meta;
    ct.rows = data.circuits;
    ct.imp = data.import;
    ct.scan = data.scan;
  } catch (e) {
    return toast(e.message);
  }
  const rows = ct.rows;
  const linked = rows.filter((r) => r.match === "matched").length;
  const live = (st) => rows.filter((r) => r.live_status === st).length;
  const tiles = [
    ["", "Circuits", rows.length, ""],
    ["success", "Linked to a switch", linked, "matched"],
    ["failed", "Not linked", rows.length - linked, "unlinked"],
    ["never", "With warnings", rows.filter((r) => r.warnings).length, "warnings"],
    ["success", "Network: matches", live("matches"), "live:matches"],
    ["failed", "Network: moved", live("moved"), "live:moved"],
    ["", "Network: found", live("found"), "live:found"],
    ["never", "Network: not seen", live("not_seen"), "live:not_seen"],
  ];
  $("#ct-summary").replaceChildren(...tiles.map(([cls, label, n, filter]) =>
    h("button", { class: `tile ${cls}`, onclick: () => { $("#ct-filter-match").value = filter; renderCircuits(); } },
      h("span", { class: "num" }, n), h("span", { class: "lbl" }, label))));
  $("#ct-source").textContent = ct.imp
    ? `Live list: ${ct.imp.filename} (sheet "${ct.imp.sheet}"), ${ct.imp.row_count} rows, made live ${fmtTime(ct.imp.committed_at)} by ${ct.imp.committed_by}.`
    : "No circuit list has been uploaded yet.";
  const full = ct.scan && ct.scan.last_full;
  $("#ct-scan-info").textContent = full
    ? `Network last read ${fmtTime(full.finished_at)} (${full.trigger.startsWith("schedule") ? "scheduled scan" : full.trigger.replace("manual:", "by ")}): ` +
      `${full.devices_ok} device(s) read` + (full.devices_failed ? `, ${full.devices_failed} failed` : "") + "."
    : "The network hasn't been scanned yet: the scheduled scan (Settings) or Scan network now fills in where each circuit is.";
  $("#ct-scan-info").title = full && full.errors ? full.errors : "";
  const uniq = (key) => [...new Set(rows.map((r) => r[key]).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  fillSelect($("#ct-filter-service"), "All services", uniq("service").map((x) => [x, x]));
  fillSelect($("#ct-filter-switch"), "All switches", uniq("switch").map((x) => [x, x]));
  const sites = [...new Map(rows.filter((r) => r.site_id).map((r) => [r.site_id, r.site_name])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1]));
  fillSelect($("#ct-filter-site"), "All sites", [...sites.map(([id, name]) => [String(id), name]), ["none", "Not at a listed site"]]);
  if (ct.siteFilter) { $("#ct-filter-site").value = ct.siteFilter; ct.siteFilter = null; }
  fillSelect($("#ct-filter-vlan"), "All VLANs", uniq("vlan").map((x) => [x, `VLAN ${x}`]));
  renderCircuits();
}

function renderCircuits() {
  const q = $("#ct-search").value.trim().toLowerCase();
  const service = $("#ct-filter-service").value, sw = $("#ct-filter-switch").value;
  const vlan = $("#ct-filter-vlan").value, match = $("#ct-filter-match").value;
  const siteSel = $("#ct-filter-site").value;
  const rows = ct.rows.filter((r) => {
    if (siteSel === "none" ? r.site_id : siteSel && String(r.site_id) !== siteSel) return false;
    if (service && r.service !== service) return false;
    if (sw && r.switch !== sw) return false;
    if (vlan && r.vlan !== vlan) return false;
    if (match === "matched" && r.match !== "matched") return false;
    if (match === "unlinked" && r.match === "matched") return false;
    if (match === "warnings" && !r.warnings) return false;
    if (match.startsWith("live:") && r.live_status !== match.slice(5)) return false;
    if (q && ![r.device_name, r.eng_prefix, r.ip, r.mac, r.port, r.switch, r.drawing_number, r.drawing_ref,
      r.room, r.device_type, r.live_switch, r.live_port, r.live_mac, r.site_text, r.site_name,
      ...Object.keys(r).filter((k) => k.startsWith("x_")).map((k) => r[k])].some((v) => (v || "").toLowerCase().includes(q))) return false;
    return true;
  });
  const shown = rows.slice(0, 2000);
  const cols = ctColumns();
  $("#ct-table thead").replaceChildren(h("tr", {}, h("th", {}), ...cols.map((c) => h("th", { title: c.help || "" }, c.label))));
  $("#ct-table tbody").replaceChildren(...shown.map((r) => circuitRow(r, cols)));
  const empty = $("#ct-empty");
  empty.hidden = rows.length > 0 && rows.length <= 2000;
  empty.textContent = !ct.rows.length ? (can("circuits", "manage") ? "No circuit list yet - click Upload spreadsheet." : "No circuit list uploaded yet.")
    : !rows.length ? "No circuits match the filter." : `Showing the first 2000 of ${rows.length} - narrow the filter to see the rest.`;
}

function circuitRow(r, cols) {
  const linkCls = r.match === "matched" ? "success" : r.match === "none" ? "never" : "failed";
  return h("tr", {},
    h("td", {}, h("span", { class: `dot ${linkCls}`, title: CT_MATCH[r.match] })),
    ...cols.map((c) => (c.live ? liveCell(r) : h("td", { class: c.cls || "" }, c.cell(r)))));
}

/** Choose and order the circuit columns (remembered for you, in this browser). */
function ctColumnsDialog() {
  chooseColumns(ctDialog, () => $("#ct-dialog").close(), ctAllColumns(), ctColumns().map((c) => c.key),
    (keys) => { saveLocal(ctColsKey(), keys); renderCircuits(); },
    () => { saveLocal(ctColsKey(), null); renderCircuits(); },
    "Combined columns show two or three values in one cell; every value also has a column of its own.");
}

/** Admins: the site's own columns on the circuit list. */
function ctFieldsDialog() {
  const custom = ct.meta.fields.filter((f) => f.custom);
  const err = errorLine();
  const label = h("input", { placeholder: "e.g. Patch panel", maxlength: 100 });
  const call = async (fn) => { err.hidden = true; try { await fn(); await loadCircuits(); ctFieldsDialog(); } catch (e) { showError(err, e); } };
  ctDialog("Custom columns",
    h("p", { class: "muted" }, "Columns you add here are there for everyone: in Columns, the blank template and the exports. " +
      "An upload reads a column with the same name; the values come from the spreadsheet."),
    custom.length ? h("ul", { class: "col-list" }, ...custom.map((f) => h("li", {},
      h("span", {}, f.label), h("span", { class: "spacer" }),
      h("button", { type: "button", class: "small", onclick: () => {
        const name = prompt("New name for the column (uploads then read the new name)", f.label);
        if (name) call(() => api(`/api/circuits/fields/${f.key}`, { method: "PUT", body: { label: name } }));
      } }, "Rename"),
      h("button", { type: "button", class: "small danger", onclick: () => {
        if (confirm(`Delete the column ${f.label} and its values in every version of the list?`)) call(() => api(`/api/circuits/fields/${f.key}`, { method: "DELETE" }));
      } }, "Delete")))) : h("p", { class: "muted" }, "No custom columns yet."),
    h("h3", {}, "Add a column"),
    h("label", {}, "Name", label), err,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "primary", onclick: () =>
      call(() => api("/api/circuits/fields", { method: "POST", body: { label: label.value } })) }, "Add column")));
}

$("#ct-columns").addEventListener("click", ctColumnsDialog);
$("#ct-fields").addEventListener("click", ctFieldsDialog);
$("#ct-template").addEventListener("click", () => templateDialog(ctDialog, "/api/circuits",
  [...new Set(ctColumns().flatMap((c) => c.fields))],
  "Fill it in (one row per circuit) and upload it with Upload spreadsheet. Each row needs a MAC or an IP address, so those two columns are always in it. " +
  "The upload replaces the whole list: you see what changes before it is made live."));

function liveCell(r) {
  if (!r.live_status) return h("td", {}, h("span", { class: "muted" }, r.live_status_label || "—"));
  const where = r.live_switch ? `${r.live_switch} ${r.live_port}` : r.live_port;
  const seen = r.live_status === "not_seen" && r.last_seen_at
    ? `last seen ${fmtTime(r.last_seen_at)} on ${r.last_seen_where}` : "";
  return h("td", {},
    h("span", { class: `badge ${CT_LIVE_CLS[r.live_status] || "never"}` }, r.live_status_label),
    where ? h("small", { class: "sub" }, h("code", {}, where)) : null,
    r.live_mac_source === "arp" ? h("small", { class: "sub", title: "The list has no MAC; it was found from the IP in an ARP table" }, `MAC ${r.live_mac} from ARP`) : null,
    seen ? h("small", { class: "sub" }, seen) : null);
}

$("#ct-scan").addEventListener("click", async () => {
  if (!confirm("Read the MAC and ARP tables of every device now? It uses the backup accounts and only runs 'show' commands.")) return;
  try {
    await api("/api/circuits/scan", { method: "POST", body: {} });
    toast("Scan started - refresh in a minute or two");
  } catch (e) {
    toast(e.message);
  }
});

["input", "change"].forEach((evt) => {
  ["#ct-search", "#ct-filter-service", "#ct-filter-switch", "#ct-filter-site", "#ct-filter-vlan", "#ct-filter-match"]
    .forEach((sel) => $(sel).addEventListener(evt, renderCircuits));
});

// Upload + preview

$("#ct-upload").addEventListener("click", () => {
  const form = $("#ct-upload-form");
  form.reset();
  $(".error", form).hidden = true;
  form.hidden = false;
  $("#ct-preview").hidden = true;
  $("#ct-upload-dialog").showModal();
  loadLayouts();
});

/** Spreadsheet layouts people matched before: files laid out the same are read with them. */
async function loadLayouts() {
  const box = $("#ct-layouts");
  let maps = [];
  try { maps = await api("/api/circuits/column-maps"); } catch (e) { maps = []; }
  if (!maps.length) return box.replaceChildren();
  box.replaceChildren(h("details", {},
    h("summary", {}, `Saved layouts (${maps.length})`),
    h("p", { class: "muted" }, "A file whose column names match one of these is read with it, without asking. Delete one to choose its columns again."),
    h("table", {}, h("tbody", {}, maps.map((m) => h("tr", {},
      h("td", { class: "name" }, m.name, h("small", { class: "sub" }, `${m.created_by}, ${fmtTime(m.created_at)}`)),
      h("td", {}, m.columns.map((c) => `${c.header} → ${c.label}`).join(", ")),
      h("td", {}, can("circuits", "manage") ? h("button", { type: "button", class: "small", onclick: async () => {
        try { await api(`/api/circuits/column-maps/${m.id}`, { method: "DELETE" }); loadLayouts(); } catch (e) { toast(e.message); }
      } }, "Delete") : "")))))));
}
$("#ct-upload-close").addEventListener("click", () => $("#ct-upload-dialog").close());

async function sendCircuitFile(file, mapping = null, save = false) {
  let url = `/api/circuits/imports/upload?filename=${encodeURIComponent(file.name)}`;
  if (mapping) url += `&map=${encodeURIComponent(JSON.stringify(mapping))}${save ? "&save=true" : ""}`;
  const res = await fetch(url, {
    method: "PUT", credentials: "same-origin", body: file, headers: { "Content-Type": "application/octet-stream" },
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { showLogin(); throw new Error("Signed out"); }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

$("#ct-upload-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, err = $(".error", form), file = form.file.files[0];
  const btn = $("button", form);
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const data = await sendCircuitFile(file);
    form.hidden = true;
    if (data.needs_mapping) return renderMapping(file, data);
    ct.pending = data;
    renderPreview(data);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Check file";
  }
});

/** The file's column names aren't known: the person picks the header row and says what
 * each column is. Only a MAC or an IP column is needed; the layout can be remembered. */
function renderMapping(file, data) {
  const pane = $("#ct-preview");
  const fields = data.fields;
  const NEW = "__new__";
  let sheetIdx = Math.max(0, data.sheets.findIndex((sh) => Object.keys(sh.guess.columns).length));
  let headerRow = data.sheets[sheetIdx].guess.header_row;
  let choice = {};
  const err = h("p", { class: "error", hidden: true });
  const remember = h("input", { type: "checkbox", checked: true });
  const grid = h("div", { class: "table-wrap map-grid" });

  const resetChoice = () => {
    const g = data.sheets[sheetIdx].guess;
    choice = g.header_row === headerRow ? Object.fromEntries(Object.entries(g.columns).map(([c, f]) => [c, f])) : {};
  };
  const options = (col) => {
    const sel = h("select", { "aria-label": `Column ${Number(col) + 1}`, onchange: () => { choice[col] = sel.value; } },
      h("option", { value: "ignore" }, "Ignore this column"),
      h("optgroup", { label: "List columns" }, fields.filter((f) => !f.custom).map((f) => h("option", { value: f.key }, f.label))),
      fields.some((f) => f.custom) ? h("optgroup", { label: "Your columns" }, fields.filter((f) => f.custom).map((f) => h("option", { value: f.key }, f.label))) : null,
      isAdmin() ? h("option", { value: NEW }, "New column (named as in the file)") : null);
    sel.value = choice[col] || "ignore";
    return sel;
  };
  const draw = () => {
    const rows = data.sheets[sheetIdx].rows;
    const header = rows[headerRow] || [];
    const sample = rows.slice(headerRow + 1, headerRow + 6);
    const cols = header.map((_, i) => String(i)).filter((i) => header[i] || sample.some((r) => r[i]));
    grid.replaceChildren(h("table", {},
      h("thead", {},
        h("tr", {}, cols.map((c) => h("th", {}, options(c)))),
        h("tr", { class: "map-head" }, cols.map((c) => h("th", {}, header[c] || `(column ${Number(c) + 1})`)))),
      h("tbody", {}, sample.length ? sample.map((r) => h("tr", {}, cols.map((c) => h("td", {}, r[c] || "")))) :
        h("tr", {}, h("td", { colspan: cols.length || 1, class: "muted" }, "No rows under this one.")))));
  };
  const rowPick = h("select", { "aria-label": "Row with the column names", onchange: () => { headerRow = Number(rowPick.value); resetChoice(); draw(); } });
  const fillRows = () => {
    rowPick.replaceChildren(...data.sheets[sheetIdx].rows.map((r, i) =>
      h("option", { value: i }, `Row ${i + 1}: ${r.filter(Boolean).slice(0, 4).join(", ").slice(0, 70) || "(empty)"}`)));
    rowPick.value = String(headerRow);
  };
  const sheetPick = data.sheets.length > 1 ? h("select", { "aria-label": "Sheet", onchange: () => {
    sheetIdx = Number(sheetPick.value); headerRow = data.sheets[sheetIdx].guess.header_row; resetChoice(); fillRows(); draw();
  } }, data.sheets.map((sh, i) => h("option", { value: i }, sh.name))) : null;
  if (sheetPick) sheetPick.value = String(sheetIdx);

  const go = async (btn) => {
    err.hidden = true;
    const used = Object.entries(choice).filter(([, f]) => f && f !== "ignore");
    if (!used.some(([, f]) => f === "mac" || f === "ip")) {
      err.textContent = "Choose the column with the MAC address or the IP address: it's how each device is found on the network.";
      err.hidden = false;
      return;
    }
    btn.disabled = true;
    try {
      const header = data.sheets[sheetIdx].rows[headerRow] || [];
      const columns = {};
      for (const [col, f] of used) {
        if (f === NEW) {
          const label = (header[col] || `Column ${Number(col) + 1}`).slice(0, 100);
          const made = await api("/api/circuits/fields", { method: "POST", body: { label } });
          columns[col] = made.key;
        } else {
          columns[col] = f;
        }
      }
      const imp = await sendCircuitFile(file, { sheet: data.sheets[sheetIdx].name === "CSV" ? "" : data.sheets[sheetIdx].name,
        header_row: headerRow, columns }, remember.checked);
      ct.pending = imp;
      renderPreview(imp);
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
    } finally {
      btn.disabled = false;
    }
  };

  resetChoice();
  fillRows();
  draw();
  const goBtn = h("button", { class: "primary", onclick: () => go(goBtn) }, "Continue");
  pane.replaceChildren(
    h("h3", {}, "Which column is which?"),
    h("p", { class: "muted" }, `The column names in ${file.name} aren't ones the list knows. Pick the row that holds the column names, then choose what each column is. `,
      "Only the ", h("b", {}, "MAC address"), " or the ", h("b", {}, "IP address"), " is needed; everything else is optional, and columns you leave as Ignore aren't read."),
    h("div", { class: "toolbar" }, sheetPick ? h("label", {}, "Sheet ", sheetPick) : null, h("label", {}, "Column names are in ", rowPick)),
    grid,
    h("label", { class: "check" }, remember, " Remember this layout: the next file with the same column names is read without asking"),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { class: "ghost", onclick: () => $("#ct-upload-dialog").close() }, "Cancel"), goBtn));
  pane.hidden = false;
}

function renderPreview(imp) {
  const s = imp.summary, d = s.diff;
  const list = (items, more) => items.length
    ? h("ul", { class: "plain" }, items.map((x) => h("li", {}, x)), more > items.length ? h("li", { class: "muted" }, `… and ${more - items.length} more`) : null)
    : h("p", { class: "muted" }, "None.");
  const pane = $("#ct-preview");
  pane.replaceChildren(
    h("div", { class: "tiles" },
      [["", "Rows read", imp.row_count], ["success", "New", d.added], ["never", "Changed", d.changed],
        ["failed", "Removed", d.removed], ["", "Unchanged", d.unchanged], ["failed", "Rows not linked", s.rows_unmatched],
        ["never", "Rows with warnings", imp.warning_count]]
        .map(([cls, label, n]) => h("div", { class: `tile ${cls}` }, h("span", { class: "num" }, n), h("span", { class: "lbl" }, label)))),
    h("p", { class: "muted" }, `${imp.filename}, sheet "${imp.sheet}", header on row ${s.header_row}. ` +
      (s.replaces_import ? "Compared with the current live list." : "There is no live list yet; every row is new.") +
      (s.missing_columns.length ? ` Columns not found (left empty): ${s.missing_columns.join(", ")}.` : "")),
    h("h3", {}, "Switches not found in the inventory"),
    h("p", { class: "muted" }, "Rows on these switches can't be linked to upgrade jobs until a device with that name (or ending in -name) exists."),
    list([...s.unmatched_switches, ...s.ambiguous_switches.map((x) => `${x} (matches more than one device)`)],
      s.unmatched_switches.length + s.ambiguous_switches.length),
    h("h3", {}, "Changes"),
    d.changed_sample.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Row", "Field", "Before", "After"].map((t) => h("th", {}, t)))),
      h("tbody", {}, d.changed_sample.flatMap((c) => c.fields.map((f, i) => h("tr", {},
        h("td", {}, i === 0 ? c.row : ""), h("td", {}, (s.labels || {})[f] || f), h("td", {}, h("code", {}, c.before[f] || "—")),
        h("td", {}, h("code", {}, c.after[f] || "—"))))))) : h("p", { class: "muted" }, "No changed rows."),
    h("p", {}, h("b", {}, "New: "), d.added_sample.slice(0, 20).join(", ") || "none", d.added > 20 ? ` … (+${d.added - 20})` : ""),
    h("p", {}, h("b", {}, "Removed: "), d.removed_sample.slice(0, 20).join(", ") || "none", d.removed > 20 ? ` … (+${d.removed - 20})` : ""),
    h("h3", {}, "Rows with warnings"),
    list(s.warnings_sample.map((w) => `Row ${w.row}: ${w.warnings}`), imp.warning_count),
    h("div", { class: "dialog-actions" },
      h("button", { class: "ghost", onclick: discardPending }, "Discard"),
      h("button", { class: "primary", onclick: commitPending }, "Make this the live list")));
  pane.hidden = false;
}

async function commitPending() {
  try {
    await api(`/api/circuits/imports/${ct.pending.id}/commit`, { method: "POST" });
    $("#ct-upload-dialog").close();
    toast("Circuit list updated");
    loadCircuits();
  } catch (e) {
    toast(e.message);
  }
}

async function discardPending() {
  try {
    await api(`/api/circuits/imports/${ct.pending.id}`, { method: "DELETE" });
  } catch (e) { /* already gone */ }
  $("#ct-upload-dialog").close();
}

// Found on the network: on switch ports, not on the list

function selectCtTab(tab) {
  ct.tab = tab;
  $$("#ct-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".ct-pane").forEach((p) => (p.hidden = p.id !== `ct-pane-${tab}`));
  if (tab === "found") loadFound();
  if (tab === "carriers") loadCarriers();
}
$$("#ct-tabs button").forEach((b) => b.addEventListener("click", () => selectCtTab(b.dataset.tab)));

async function loadFound() {
  try {
    const d = await api("/api/circuits/discovered");
    ct.found = d.devices;
    ct.foundScanned = !!(d.scan && d.scan.last_full);
  } catch (e) {
    return;
  }
  $("#ct-found-count").textContent = ct.found.length ? String(ct.found.length) : "";
  const uniq = (key) => [...new Set(ct.found.map((r) => r[key]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
  for (const [id, label, key] of [["#ctf-site", "All sites", "site"], ["#ctf-switch", "All switches", "switch"], ["#ctf-vlan", "All VLANs", "vlan"]]) {
    const keep = $(id).value;
    fillSelect($(id), label, uniq(key).map((x) => [x, x]));
    $(id).value = keep;
  }
  renderFound();
}

function shownFound() {
  const q = $("#ctf-search").value.trim().toLowerCase();
  const site = $("#ctf-site").value, sw = $("#ctf-switch").value, vlan = $("#ctf-vlan").value;
  return ct.found.filter((r) => (!site || r.site === site) && (!sw || r.switch === sw) && (!vlan || String(r.vlan) === vlan) &&
    (!q || [r.mac, r.ip, r.switch, r.port, r.lldp_name, r.lldp_platform, r.site].some((x) => (x || "").toLowerCase().includes(q))));
}

function renderFound() {
  const rows = shownFound();
  const picked = () => $$("#ctf-table tbody input:checked").map((x) => x.value);
  const sync = () => { $("#ctf-add").disabled = !picked().length; };
  $("#ctf-all").checked = false;
  $("#ctf-table tbody").replaceChildren(...rows.slice(0, 2000).map((r) => h("tr", {},
    h("td", {}, h("input", { type: "checkbox", value: r.mac, "aria-label": `Select ${r.mac}`, onchange: sync })),
    h("td", {}, h("code", {}, r.mac)), h("td", {}, r.ip ? h("code", {}, r.ip) : "—"), h("td", {}, r.vlan || "—"),
    h("td", { class: "name" }, r.switch, r.also_on.length ? h("small", { class: "sub", title: r.also_on.join(", ") }, `also on ${r.also_on.length} other port(s)`) : null),
    h("td", {}, r.port), h("td", {}, r.site ? siteLink(r.site) : "—"),
    h("td", {}, r.lldp_name || "—", r.lldp_platform ? h("small", { class: "sub" }, r.lldp_platform) : null),
    h("td", {}, fmtTime(r.seen_at)))));
  const empty = $("#ctf-empty");
  empty.hidden = rows.length > 0;
  empty.textContent = !ct.foundScanned ? "The network hasn't been scanned yet: click Scan network now on the Circuit list tab."
    : ct.found.length ? "Nothing matches the filters." : "Everything the last scan saw on switch ports is on the list.";
  sync();
}
["#ctf-search", "#ctf-site", "#ctf-switch", "#ctf-vlan"].forEach((id) => $(id).addEventListener("input", renderFound));
$("#ctf-all").addEventListener("change", (ev) => {
  $$("#ctf-table tbody input").forEach((x) => { x.checked = ev.target.checked; });
  $("#ctf-add").disabled = !ev.target.checked || !$$("#ctf-table tbody input").length;
});

/** Add found devices: a preview of the list with them added, made live like an upload. */
async function adoptFound(macs, service = "") {
  try {
    const imp = await api("/api/circuits/discovered/adopt", { method: "POST", body: { macs, service } });
    ct.pending = imp;
    $("#ct-upload-form").hidden = true;
    renderPreview(imp);
    $("#ct-upload-dialog").showModal();
  } catch (e) {
    toast(e.message);
  }
}

$("#ctf-add").addEventListener("click", () => {
  const macs = $$("#ctf-table tbody input:checked").map((x) => x.value);
  if (!macs.length) return;
  const service = h("input", { type: "text", maxlength: 200, placeholder: "e.g. Printers (optional)" });
  const body = $("#ct-dialog-body");
  $("#ct-dialog-title").textContent = `Add ${macs.length} device(s) to the list`;
  body.replaceChildren(
    h("p", { class: "muted" }, "They are added with the switch, port, VLAN, IP and MAC from the scan, and the name they give over LLDP or CDP. You see the change before the list is updated."),
    h("label", {}, "Service (for all of them) ", service),
    h("div", { class: "dialog-actions" }, h("button", { class: "primary", onclick: async () => {
      $("#ct-dialog").close();
      await adoptFound(macs, service.value.trim());
    } }, "Show the change")));
  $("#ct-dialog").showModal();
});

// Carrier circuits: lines from providers, with their status from monitoring

const CC_CLS = { up: "success", down: "failed", device_down: "failed", admin_down: "never", not_found: "changed",
  not_read: "never", not_monitored: "never", no_link: "never" };
const cc = { rows: [], services: [], endingDays: 60, devices: null };

async function loadCarriers() {
  let d;
  try { d = await api("/api/circuits/carriers"); } catch (e) { return; }
  cc.rows = d.circuits;
  cc.services = d.services;
  cc.endingDays = d.ending_days;
  cc.monitoring = d.monitoring;
  const bad = cc.rows.filter((r) => ["down", "device_down"].includes(r.status)).length;
  $("#ct-carrier-count").textContent = cc.rows.length ? String(cc.rows.length) : "";
  $("#ct-carrier-count").classList.toggle("bad", bad > 0);
  const n = (f) => cc.rows.filter(f).length;
  const tiles = [
    ["", "Carrier circuits", cc.rows.length, ""],
    ["success", "Up", n((r) => r.status === "up"), "up"],
    ["failed", "Down", bad, "down"],
    ["never", "No live status", n((r) => !["up", "down", "device_down"].includes(r.status)), "nolive"],
    ["changed", `Contract ends within ${cc.endingDays} days`, n((r) => r.contract_ending), "ending"],
  ];
  $("#cc-summary").replaceChildren(...tiles.map(([cls, label, num, filter]) =>
    h("button", { class: `tile ${cls}`, onclick: () => { $("#cc-status").value = filter; renderCarriers(); } },
      h("span", { class: "num" }, num), h("span", { class: "lbl" }, label))));
  const keepSvc = $("#cc-service").value, keepSt = $("#cc-status").value;
  fillSelect($("#cc-service"), "All services", [...new Set(cc.rows.map((r) => r.service).filter(Boolean))].sort().map((x) => [x, x]));
  fillSelect($("#cc-status"), "All statuses", [["up", "Up"], ["down", "Down (line or router)"], ["nolive", "No live status"], ["ending", "Contract ending soon"]]);
  $("#cc-service").value = keepSvc;
  $("#cc-status").value = keepSt;
  renderCarriers();
}

function renderCarriers() {
  const q = $("#cc-search").value.trim().toLowerCase(), svc = $("#cc-service").value, st = $("#cc-status").value;
  const rows = cc.rows.filter((r) => (!svc || r.service === svc) &&
    (!st || (st === "up" && r.status === "up") || (st === "down" && ["down", "device_down"].includes(r.status)) ||
      (st === "nolive" && !["up", "down", "device_down"].includes(r.status)) || (st === "ending" && r.contract_ending)) &&
    (!q || [r.provider, r.circuit_ref, r.service, r.site, r.site_name, r.device, r.interface, r.wan_ip, r.support, r.notes]
      .some((x) => (x || "").toLowerCase().includes(q))));
  $("#cc-table tbody").replaceChildren(...rows.map((r) => h("tr", {},
    h("td", {}, h("span", { class: `badge ${CC_CLS[r.status] || "never"}`, title: r.since ? `Since ${fmtTime(new Date(r.since * 1000).toISOString())}` : "" }, r.status_label)),
    h("td", { class: "name" }, r.provider || "—"),
    h("td", {}, r.circuit_ref ? h("code", {}, r.circuit_ref) : "—", r.wan_ip ? h("small", { class: "sub" }, r.wan_ip) : null),
    h("td", {}, r.service || "—"), h("td", {}, r.bandwidth || "—"),
    h("td", {}, r.site_name ? siteLink(r.site_name, r.site_id) : (r.site || "—")),
    h("td", {}, r.device || "—", r.interface ? h("small", { class: "sub" }, r.interface) : null),
    h("td", {}, r.in_bps != null || r.out_bps != null ? `${fmtBps(r.in_bps)} in / ${fmtBps(r.out_bps)} out` : "—",
      r.util != null ? h("small", { class: "sub" }, `${r.util < 1 ? "under 1" : Math.round(r.util)}% of the port`) : null),
    h("td", {}, r.contract_end || "—", r.contract_days != null && r.contract_ending
      ? h("small", { class: `sub ${r.contract_days < 0 ? "errtext" : ""}` }, r.contract_days < 0 ? `ended ${-r.contract_days} day(s) ago` : `in ${r.contract_days} days`) : null),
    h("td", {}, can("circuits", "manage") ? h("button", { type: "button", class: "small", onclick: () => carrierDialog(r) }, "Edit") : ""))));
  const empty = $("#cc-empty");
  empty.hidden = rows.length > 0;
  empty.textContent = cc.rows.length ? "Nothing matches the filters." : "No carrier circuits yet: Add carrier circuit, or upload a spreadsheet (Blank template shows the columns).";
}
["#cc-search", "#cc-service", "#cc-status"].forEach((id) => $(id).addEventListener("input", renderCarriers));

/** Show one carrier circuit: the Circuits page, Carrier circuits tab, filtered to it. */
async function openCarrier(id) {
  switchView("circuits");
  selectCtTab("carriers");
  await loadCarriers();
  const r = cc.rows.find((x) => x.id === id);
  if (!r) return;
  $("#cc-search").value = r.circuit_ref || r.provider;
  renderCarriers();
}

async function carrierDialog(r = null) {
  if (!cc.devices) cc.devices = await api("/api/devices").catch(() => []);
  const v = r || {};
  const field = (name, label, attrs = {}) => h("label", {}, label, " ", h("input", { name, value: v[name] || "", ...attrs }));
  const service = h("input", { name: "service", value: v.service || "", list: "cc-services" });
  const device = h("select", { name: "device_id" }, h("option", { value: "" }, "— not linked —"),
    cc.devices.slice().sort((a, b) => a.name.localeCompare(b.name)).map((d) => h("option", { value: d.id }, `${d.name}${d.site ? ` (${d.site})` : ""}`)));
  device.value = v.device_id ? String(v.device_id) : "";
  const iface = h("input", { name: "interface", value: v.interface || "", list: "cc-ifaces", placeholder: "e.g. GigabitEthernet0/0" });
  const ifList = h("datalist", { id: "cc-ifaces" });
  const loadIfaces = async () => {
    ifList.replaceChildren();
    if (!device.value || !cc.monitoring || !can("monitoring", "view")) return;
    try {
      const d = await api(`/api/monitoring/devices/${device.value}/interfaces`);
      ifList.replaceChildren(...d.interfaces.filter((i) => i.type !== 24).map((i) => h("option", { value: i.name || i.descr }, i.alias || "")));
    } catch (e) { /* no monitoring data for it */ }
  };
  device.addEventListener("change", loadIfaces);
  loadIfaces();
  const err = h("p", { class: "error", hidden: true });
  const form = h("form", { class: "form" },
    h("div", { class: "grid2" }, field("provider", "Provider"), field("circuit_ref", "Circuit ID")),
    h("div", { class: "grid2" }, h("label", {}, "Service ", service), field("bandwidth", "Bandwidth", { placeholder: "e.g. 1 Gbps" })),
    h("div", { class: "grid2" }, field("site", "Site", { placeholder: "name or code; empty = the router's site" }), field("wan_ip", "WAN IP")),
    h("div", { class: "grid2" }, h("label", {}, "Router or firewall ", device), h("label", {}, "Interface ", iface)),
    h("datalist", { id: "cc-services" }, cc.services.map((x) => h("option", { value: x }))), ifList,
    h("div", { class: "grid2" }, field("contract_end", "Contract end", { type: "date" }), field("cost", "Cost")),
    field("support", "Fault line / account"),
    h("label", {}, "Notes ", h("textarea", { name: "notes", rows: 3 }, v.notes || "")),
    err,
    h("div", { class: "dialog-actions" },
      r ? h("button", { type: "button", class: "danger", onclick: async () => {
        if (!confirm(`Delete ${r.provider} ${r.circuit_ref}?`)) return;
        try { await api(`/api/circuits/carriers/${r.id}`, { method: "DELETE" }); $("#ct-dialog").close(); loadCarriers(); } catch (e) { showError(err, e); }
      } }, "Delete") : null,
      h("span", { class: "spacer" }),
      h("button", { class: "primary" }, r ? "Save" : "Add")));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    const f = new FormData(form);
    const body = Object.fromEntries([...f.entries()].map(([k, x]) => [k, String(x).trim()]));
    body.device_id = body.device_id ? Number(body.device_id) : null;
    body.contract_end = body.contract_end || null;
    try {
      await api(r ? `/api/circuits/carriers/${r.id}` : "/api/circuits/carriers", { method: r ? "PUT" : "POST", body });
      $("#ct-dialog").close();
      toast(r ? "Carrier circuit saved" : "Carrier circuit added");
      loadCarriers();
    } catch (e) { showError(err, e); }
  });
  $("#ct-dialog-title").textContent = r ? `${r.provider} ${r.circuit_ref}`.trim() : "Add carrier circuit";
  $("#ct-dialog-body").replaceChildren(form,
    h("p", { class: "muted" }, "Choose the router or firewall the line plugs into, and its interface as the device names it. ",
      "The status then comes from monitoring (the device must be monitored with SNMP). That port is watched: going down is an event and an email even without a description on it."));
  $("#ct-dialog").showModal();
}
$("#cc-add").addEventListener("click", () => carrierDialog());

$("#cc-upload").addEventListener("click", () => { $("#cc-file").value = ""; $("#cc-file").click(); });
$("#cc-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  try {
    const res = await fetch(`/api/circuits/carriers/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "PUT", credentials: "same-origin", body: file, headers: { "Content-Type": "application/octet-stream" } });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) return showLogin();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    const body = $("#ct-dialog-body");
    $("#ct-dialog-title").textContent = `Uploaded ${file.name}`;
    body.replaceChildren(h("p", {}, `${data.added} added, ${data.updated} updated. Nothing was removed.`),
      data.problems.length ? h("div", {}, h("h3", {}, "Rows to check"), h("ul", { class: "plain" }, data.problems.map((x) => h("li", {}, x)))) : null);
    $("#ct-dialog").showModal();
    loadCarriers();
  } catch (e) {
    toast(e.message);
  }
});

// History

$("#ct-history").addEventListener("click", async () => {
  const body = $("#ct-history-body");
  body.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  $("#ct-history-dialog").showModal();
  try {
    const imports = await api("/api/circuits/imports");
    if (!imports.length) return body.replaceChildren(h("p", { class: "empty" }, "No imports yet."));
    body.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["Uploaded", "File", "Rows", "Changes", "Status"].map((t) => h("th", {}, t)))),
      h("tbody", {}, imports.map((i) => {
        const d = (i.summary || {}).diff || {};
        return h("tr", {},
          h("td", {}, fmtTime(i.uploaded_at), h("small", { class: "sub" }, i.uploaded_by)),
          h("td", {}, i.filename, h("small", { class: "sub" }, `sheet "${i.sheet}"`)),
          h("td", {}, i.row_count),
          h("td", {}, `+${d.added ?? 0} ~${d.changed ?? 0} −${d.removed ?? 0}`),
          h("td", {}, h("span", { class: `badge ${i.status === "active" ? "success" : i.status === "pending" ? "running" : "never"}` },
            i.status), i.committed_at ? h("small", { class: "sub" }, `${fmtTime(i.committed_at)} ${i.committed_by}`) : null));
      }))));
  } catch (e) {
    body.replaceChildren(h("p", { class: "error" }, e.message));
  }
});
$("#ct-history-close").addEventListener("click", () => $("#ct-history-dialog").close());

// Device detail: circuits on this switch

async function loadDeviceCircuits() {
  const pane = $("#detail-circuits");
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const data = await api(`/api/circuits/for-device/${state.detailDevice.id}`);
    if (!data.import) return pane.replaceChildren(h("p", { class: "empty" }, "No circuit list has been uploaded yet."));
    if (!data.count) return pane.replaceChildren(h("p", { class: "empty" }, "No circuits in the list use this device."));
    pane.replaceChildren(h("p", { class: "muted" }, `${data.count} circuit(s) on ${data.device}, from ${data.import.filename}.`),
      ...data.groups.map((g) => h("div", {},
        h("h3", {}, `${g.service} — VLAN ${g.vlan} (${g.circuits.length})`),
        h("table", {}, h("thead", {}, h("tr", {}, ["Port (list)", "On the network", "Device", "Type", "IP", "MAC", "Location", "Drawing"].map((t) => h("th", {}, t)))),
          h("tbody", {}, g.circuits.map((c) => h("tr", {},
            h("td", {}, h("code", {}, c.port || "—")), liveCell(c), h("td", { class: "name" }, c.device_name || "—"), h("td", {}, c.device_type || "—"),
            h("td", {}, h("code", {}, c.ip || "—")), h("td", {}, h("code", {}, c.mac || "—")),
            h("td", {}, [c.floor, c.room].filter(Boolean).join(" / ") || "—"), h("td", {}, c.drawing_number || "—"))))))));
  } catch (e) {
    pane.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

// ---------- upgrade jobs ----------

const JOB_STATUS = {
  planned: "Planned", pre_checking: "Pre-checking…", blocked: "Blocked", ready: "Ready to start",
  staging: "Staging image…", running: "Running…", post_checking: "Post-checking…", paused: "Paused",
  completed: "Completed", completed_overrides: "Completed with overrides", failed: "Failed",
  cancelled: "Cancelled", rolling_back: "Rolling back…", rolled_back: "Rolled back",
  needs_attention: "Needs attention",
};
const JOB_OPEN = ["planned", "pre_checking", "blocked", "ready", "staging", "running", "post_checking",
  "paused", "failed", "rolling_back", "needs_attention"];
const JOB_WORKING = ["pre_checking", "staging", "running", "post_checking", "rolling_back"];
const UNIT_STATUS = { pending: "not changed yet", activated: "upgrading", checked: "upgraded, checked",
  failed: "post-checks failed", rolled_back: "rolled back" };
const jobs = { list: [], current: null, tab: "checks", timer: null, paths: null, worker: null };

async function upgradePaths() {
  if (!jobs.paths) jobs.paths = await api("/api/firmware/upgrade-paths");
  return jobs.paths;
}

async function toggleRecommended(img) {
  const ref = img.recommended ? img.release_ref : (prompt(`Why is ${img.filename} recommended? (e.g. "Cisco suggested release")`, img.release_ref || "") ?? null);
  if (ref === null) return;
  try {
    await api(`/api/firmware/images/${img.id}/info`, { method: "PUT", body: { recommended: !img.recommended, release_ref: ref } });
    loadFwImages();
  } catch (e) {
    toast(e.message);
  }
}

function workerBanner(w) {
  if (!w || w.alive) return "";
  return h("p", { class: "banner bad" }, h("b", {}, "The upgrade worker isn't running"),
    " (service netops-worker). Jobs can be viewed, but no checks or upgrade steps can run until it is started.");
}

async function loadJobs() {
  try {
    [jobs.list, jobs.worker] = await Promise.all([api("/api/firmware/jobs"), api("/api/firmware/worker")]);
  } catch (e) {
    return toast(e.message);
  }
  $("#worker-banner").replaceChildren(workerBanner(jobs.worker) || "");
  const count = (st) => jobs.list.filter((j) => st.includes(j.status)).length;
  $("#job-summary").replaceChildren(...[
    ["", "Open jobs", count(JOB_OPEN)], ["success", "Ready to start", count(["ready", "paused"])],
    ["failed", "Blocked / failed", count(["blocked", "failed", "needs_attention"])],
    ["success", "Completed", count(["completed", "completed_overrides"])],
    ["never", "Rolled back / cancelled", count(["rolled_back", "cancelled"])],
  ].map(([cls, label, n]) => h("div", { class: `tile ${cls}` }, h("span", { class: "num" }, n), h("span", { class: "lbl" }, label))));
  renderJobs();
}

function modeBadge(j) {
  return j.dry_run ? h("small", { class: "sub" }, "dry run") : h("span", { class: "badge live" }, "LIVE");
}

function renderJobs() {
  const f = $("#job-filter").value;
  const rows = jobs.list.filter((j) => !f || (f === "open" ? JOB_OPEN.includes(j.status) : !JOB_OPEN.includes(j.status)));
  $("#job-table tbody").replaceChildren(...rows.map((j) => h("tr", {},
    h("td", {}, `#${j.id}`),
    h("td", { class: "name" }, j.units.map((u) => u.name).join(" + "), h("small", {}, `${j.device.platform_label} · ${j.path_label}`)),
    h("td", {}, h("code", {}, `${j.from_version || "?"} → ${j.target_version}`), h("small", { class: "sub" }, j.image.filename)),
    h("td", {}, h("span", { class: `badge ${j.status}` }, JOB_STATUS[j.status] || j.status), " ", modeBadge(j)),
    h("td", {}, j.change_ref || "—"),
    h("td", {}, j.planned_start ? fmtTime(j.planned_start) : "—"),
    h("td", {}, fmtTime(j.created_at), h("small", { class: "sub" }, j.created_by)),
    h("td", { class: "actions" }, h("button", { class: "small", onclick: () => openJob(j.id) }, "Open")))));
  $("#job-empty").hidden = rows.length > 0;
}
$("#job-filter").addEventListener("change", renderJobs);

// New job

$("#job-new").addEventListener("click", async () => {
  const form = $("#job-new-form");
  form.reset();
  $(".error", form).hidden = true;
  try {
    [fw.rows, fw.images] = await Promise.all([api("/api/firmware/devices"), api("/api/firmware/images"), upgradePaths()]);
  } catch (e) {
    return toast(e.message);
  }
  form.device_id.replaceChildren(h("option", { value: "" }, "— choose a device —"),
    ...fw.rows.map((r) => h("option", { value: r.device.id }, `${r.device.name} (${r.device.platform_label}, ${r.facts.version || "version unknown"})`)));
  form.device_id.onchange = () => fillJobForm(form);
  form.path.onchange = () => describePath(form);
  $$("input[name=mode]", form).forEach((r) => (r.onchange = () => describePath(form)));
  fillJobForm(form);
  $("#job-new-dialog").showModal();
});

$("#job-new-settings").addEventListener("click", () => {
  const form = $("#job-new-form");
  const row = fw.rows.find((r) => String(r.device.id) === form.device_id.value);
  if (!row) return toast("Choose a device first");
  openUpgradeSettings(row.device, () => fillJobForm(form));
});

function globMatch(pattern, value) {
  return pattern === "*" || !value || new RegExp("^" + pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$", "i").test(value);
}

async function fillJobForm(form) {
  const row = fw.rows.find((r) => String(r.device.id) === form.device_id.value);
  const info = $("#job-new-device");
  form.image_id.replaceChildren();
  form.path.replaceChildren();
  $("#job-new-path").textContent = "";
  if (!row) return (info.textContent = "");
  const matches = fw.images.filter((i) => i.platform === row.device.platform && globMatch(i.model_pattern, row.facts.model));
  form.image_id.replaceChildren(...(matches.length ? matches.map((i) => h("option", { value: i.id },
    `${i.version} — ${i.filename}${i.recommended ? " (recommended)" : ""}`)) : [h("option", { value: "" }, "No image in the repository suits this device")]));
  const [settings, circ] = await Promise.all([
    api(`/api/firmware/devices/${row.device.id}/settings`).catch(() => ({ paths: [] })),
    api(`/api/circuits/for-device/${row.device.id}`).catch(() => ({ count: 0 }))]);
  form._settings = settings;
  const catalogue = (jobs.paths.find((p) => p.platform === row.device.platform) || { paths: [] }).paths;
  const preferred = settings.default_path || (row.device.platform === "cisco_ios" ? (row.facts.boot_mode === "install" ? "install" : "bundle")
    : (settings.peer ? (catalogue.find((p) => p.units === 2) || {}).id : catalogue[0] && catalogue[0].id));
  form.path.replaceChildren(...catalogue.map((p) => h("option", { value: p.id, disabled: p.units === 2 && !settings.peer },
    p.label + (p.units === 2 ? (settings.peer ? ` — with ${settings.peer}` : " — needs a peer (Upgrade settings)") : ""))));
  if (preferred && catalogue.some((p) => p.id === preferred && !(p.units === 2 && !settings.peer))) form.path.value = preferred;
  info.textContent = `Now running ${row.facts.version || "unknown"} on ${row.facts.model || "unknown model"}` +
    ` · ${circ.count || 0} affected circuit(s) in the circuit list` +
    (settings.upgrade_credential ? ` · upgrade account ${settings.upgrade_credential}` : " · no upgrade account set yet (an admin sets it in Upgrade settings)");
  describePath(form);
}

function describePath(form) {
  const row = fw.rows.find((r) => String(r.device.id) === form.device_id.value);
  if (!row) return;
  const p = ((jobs.paths.find((x) => x.platform === row.device.platform) || { paths: [] }).paths).find((x) => x.id === form.path.value);
  $("#job-new-path").textContent = p ? p.description : "";
  const liveRadio = $("input[name=mode][value=live]", form);
  liveRadio.disabled = !(p && p.live_allowed && can("upgrades", "live"));
  if (liveRadio.disabled && liveRadio.checked) $("input[name=mode][value=dry]", form).checked = true;
  const live = liveRadio.checked;
  form.planned_start.required = form.planned_end.required = live;
  $("#job-new-live").textContent = !p ? "" : !can("upgrades", "live")
    ? "Your account can plan and run dry runs only." : !p.live_allowed
    ? "Live upgrades are switched off for this platform (NETOPS_UPGRADE_LIVE_PLATFORMS). Dry run only."
    : live ? "A live upgrade needs a change window, and only starts inside it." : "";
}

$("#job-new-form").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const form = ev.target, err = $(".error", form);
  const toIso = (v) => (v ? new Date(v).toISOString().slice(0, 19) : null);
  try {
    const job = await api("/api/firmware/jobs", { method: "POST", body: {
      device_id: Number(form.device_id.value), image_id: Number(form.image_id.value), path: form.path.value,
      live: $("input[name=mode][value=live]", form).checked, change_ref: form.change_ref.value,
      notes: form.notes.value, planned_start: toIso(form.planned_start.value), planned_end: toIso(form.planned_end.value) } });
    $("#job-new-dialog").close();
    loadJobs();
    openJob(job.id);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
});

// Upgrade settings (admin)

async function openUpgradeSettings(device, after) {
  const form = $("#ups-form");
  form.reset();
  $(".error", form).hidden = true;
  let settings, creds, devices;
  try {
    [settings, creds, devices] = await Promise.all([api(`/api/firmware/devices/${device.id}/settings`),
      api("/api/credentials"), api("/api/devices")]);
  } catch (e) {
    return toast(e.message);
  }
  $("#ups-title").textContent = `Upgrade settings — ${device.name}`;
  form.upgrade_credential_id.replaceChildren(h("option", { value: "" }, "— none —"),
    ...creds.map((c) => h("option", { value: c.id }, `${c.name} (${c.username})`)));
  form.upgrade_credential_id.value = settings.upgrade_credential_id ?? "";
  form.default_path.replaceChildren(h("option", { value: "" }, "— decide per job —"),
    ...settings.paths.map((p) => h("option", { value: p.id }, p.label)));
  form.default_path.value = settings.default_path || "";
  const peers = devices.filter((d) => d.platform === device.platform && d.id !== device.id);
  form.peer_device_id.replaceChildren(h("option", { value: "" }, "— none (standalone) —"),
    ...peers.map((d) => h("option", { value: d.id }, `${d.name} (${d.address})`)));
  form.peer_device_id.value = settings.peer_device_id ?? "";
  form.file_system.value = settings.file_system || "";
  form.fdm_fingerprint.value = settings.fdm_fingerprint || "";
  $("#ups-fdm").hidden = !["cisco_ftd", "fortinet_fortios", "paloalto_panos"].includes(device.platform);
  $("#ups-fetch").onclick = async () => {
    try {
      const r = await api(`/api/firmware/devices/${device.id}/fdm-fingerprint`, { method: "POST" });
      if (confirm(`${device.name} presents this certificate:\n\n${r.fingerprint}\n\nDoes it match the fingerprint the device shows? Only then trust it.`)) {
        form.fdm_fingerprint.value = r.fingerprint;
      }
    } catch (e) {
      toast(e.message);
    }
  };
  form.onsubmit = async (ev) => {
    if (ev.submitter && ev.submitter.value === "cancel") return;
    ev.preventDefault();
    const num = (v) => (v ? Number(v) : null);
    try {
      await api(`/api/firmware/devices/${device.id}/settings`, { method: "PUT", body: {
        upgrade_credential_id: num(form.upgrade_credential_id.value), default_path: form.default_path.value,
        peer_device_id: num(form.peer_device_id.value), file_system: form.file_system.value.trim(),
        fdm_fingerprint: form.fdm_fingerprint.value.trim() } });
      $("#ups-dialog").close();
      toast("Upgrade settings saved");
      if (after) after();
    } catch (e) {
      $(".error", form).textContent = e.message;
      $(".error", form).hidden = false;
    }
  };
  $("#ups-dialog").showModal();
}

// Job window

async function openJob(id) {
  jobs.tab = "procedure";
  $$("#job-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === jobs.tab));
  $("#job-dialog").showModal();
  await refreshJob(id);
}
$("#job-close").addEventListener("click", () => {
  clearTimeout(jobs.timer);
  $("#job-dialog").close();
  if (state.view === "firmware" && fw.tab === "jobs") loadJobs();
});
$$("#job-tabs button").forEach((b) => b.addEventListener("click", () => {
  jobs.tab = b.dataset.tab;
  $$("#job-tabs button").forEach((x) => x.classList.toggle("active", x === b));
  renderJobPane();
}));

async function refreshJob(id) {
  clearTimeout(jobs.timer);
  try {
    [jobs.current, jobs.worker] = await Promise.all([api(`/api/firmware/jobs/${id}`), api("/api/firmware/worker")]);
  } catch (e) {
    return toast(e.message);
  }
  renderJob();
  const j = jobs.current;
  if ($("#job-dialog").open && (j.busy || JOB_WORKING.includes(j.status) || j.pending_commit)) {
    jobs.timer = setTimeout(() => refreshJob(id), j.busy || JOB_WORKING.includes(j.status) ? 2000 : 15000);
  }
}

function minutesUntil(t) {
  return Math.round((new Date(t + (t.endsWith("Z") ? "" : "Z")) - Date.now()) / 60000);
}

function renderJob() {
  const j = jobs.current;
  $("#job-title").textContent = `Upgrade job #${j.id} — ${j.units.map((u) => u.name).join(" + ")}`;
  const working = (j.busy && !j.queued) || JOB_WORKING.includes(j.status);
  const cls = ["blocked", "failed", "needs_attention"].includes(j.status) ? "bad"
    : ["ready", "completed"].includes(j.status) ? "good" : "";
  const hint = {
    blocked: " — fix the device and Re-check, or override each blocker with a reason.",
    failed: j.mode === "rollback" ? " — the roll back's post-checks failed: check the device, then Re-run post-checks or override with a note."
      : " — investigate, then Re-run post-checks, override with a note, or Roll back.",
    paused: " — Continue carries on from the next step.",
    needs_attention: " — the procedure stopped in an unclear state: check the device, then re-run the post-checks or roll back.",
  }[j.status] || "";
  $("#job-banner").replaceChildren(
    workerBanner(jobs.worker) || "",
    h("p", { class: `banner ${cls}` }, h("b", {}, JOB_STATUS[j.status] || j.status),
      j.queued ? ` — ${j.queued} queued for the upgrade worker…` : working ? [" — ", h("span", { class: "spin" }), " ", j.current_step || "working", " (updates by itself)"] : "",
      j.stop_requested && working ? " — will stop after this step" : "", j.busy ? "" : hint),
    unresolvedList(j),
    j.pending_commit && j.abort_deadline ? h("p", { class: "banner bad" }, h("b", {}, "Not committed: "),
      `the device goes back to ${j.from_version} by itself at ${fmtTime(j.abort_deadline)} (in about ${minutesUntil(j.abort_deadline)} min) unless the new version is committed (Continue after the post-checks pass or are overridden).`) : "",
    j.dry_run ? h("p", { class: "banner" }, "DRY RUN: checks really read the device; anything that would change it is only recorded.")
      : h("p", { class: "banner bad" }, h("b", {}, "LIVE upgrade: "), `copies, reloads and commits for real, only inside the change window (${j.in_window ? "now open" : "not open now"}).`));
  const item = (label, value, sub) => h("div", {}, h("small", {}, label), value, sub ? h("small", {}, sub) : null);
  $("#job-info").replaceChildren(
    item("Upgrade", h("code", {}, `${j.from_version || "?"} → ${j.target_version}`), `${j.image.vendor} · ${j.image.filename}`),
    item("Path", j.path_label, `${j.device.platform_label} · site ${j.device.site || "—"}`),
    item("Change", j.change_ref || "—", j.planned_start ? `${fmtTime(j.planned_start)} – ${fmtTime(j.planned_end)}` : "no window set"),
    item("Created", fmtTime(j.created_at), j.created_by),
    item("Started", j.started_at ? fmtTime(j.started_at) : "—", j.started_by || ""),
    h("div", { class: "units" }, j.units.map((u) => h("div", { class: "unit" },
      h("b", {}, u.name), h("small", {}, `${u.address}${u.role ? " · " + u.role : ""}`),
      h("small", {}, `was ${u.from_version || "?"} · ${j.dry_run && u.status === "checked" ? "rehearsed (dry run)" : UNIT_STATUS[u.status] || u.status}${u.staged ? " · image staged" : ""}`),
      h("small", {}, `account: ${u.upgrade_credential || "— not set —"}`)))));
  const allowed = (a) => j.allowed.includes(a) && canRunJob(j);
  const act = (label, action, cls = "", confirmText = null) => h("button", { class: cls, onclick: () => jobAction(action, confirmText) }, label);
  const live = !j.dry_run;
  $("#job-actions").replaceChildren(
    allowed("precheck") ? act(j.pre_run ? "Re-check" : "Run pre-checks", "precheck", j.status === "planned" ? "primary" : "") : "",
    allowed("stage") ? act("Stage image", "stage", "", `Copy ${j.image.filename} to ${j.units.map((u) => u.name).join(" and ")} and check it there?\n\nNothing is reloaded.`) : "",
    allowed("start") ? act(live ? "Start LIVE upgrade" : "Start (dry run)", "start", live ? "danger" : "primary",
      live ? null : `Start the dry run for ${j.device.name}?\n\nPre-checks run again first; nothing is changed on the device.`) : "",
    allowed("continue") ? act("Continue", "continue", "primary") : "",
    allowed("postcheck") ? act("Re-run post-checks", "postcheck") : "",
    allowed("rollback") ? act("Roll back", "rollback", "danger", live ? null : `Roll ${j.device.name} back to ${j.from_version}? (dry run)`) : "",
    allowed("stop") ? h("button", { class: "ghost", onclick: stopJob }, "Stop after this step") : "",
    allowed("cancel") ? h("button", { class: "ghost", onclick: cancelJob }, "Cancel job") : "",
    h("span", { class: "spacer" }),
    h("a", { class: "button", href: `/api/firmware/jobs/${j.id}/report.html`, target: "_blank", rel: "noopener" }, "Open report"),
    h("a", { class: "button", href: `/api/firmware/jobs/${j.id}/report.csv`, download: true }, "Checks CSV"));
  renderJobPane();
}

// Failed blockers without an override, named at the top of the job window.
function unresolvedList(j) {
  if (!["blocked", "failed", "needs_attention"].includes(j.status)) return "";
  const open = ["post", "stage", "pre"].map((ph) => j.checks[ph].filter((c) => c.severity === "blocker" && ["fail", "error"].includes(c.status) && !c.overridden_by))
    .find((list) => list.length && j.status !== "blocked") || j.checks.pre.filter((c) => c.severity === "blocker" && ["fail", "error"].includes(c.status) && !c.overridden_by);
  if (!open.length) return "";
  return h("ul", { class: "banner bad unresolved" }, open.map((c) =>
    h("li", {}, h("b", {}, (j.units.length > 1 && c.device ? `${c.device}: ` : "") + c.label), ": ", c.value || "", c.detail ? ` — ${c.detail.split("\n")[0]}` : "")));
}

function checksTable(rows, phase) {
  const j = jobs.current;
  if (!rows.length) return h("p", { class: "muted" }, { pre: "Pre-checks haven't run yet.", stage: "The image hasn't been staged yet.", post: "Post-checks run after each unit is upgraded." }[phase]);
  const canOverride = canRunJob(j) && !j.busy &&
    ((phase === "pre" && ["blocked", "ready"].includes(j.status)) || (phase === "post" && ["failed", "paused", "completed_overrides", "needs_attention"].includes(j.status)));
  const multi = j.units.length > 1;
  return h("table", {},
    h("thead", {}, h("tr", {}, [multi ? "Unit" : null, "Check", "Result", "Value", "Detail", ""].filter((t) => t !== null).map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((c) => {
      const failed = ["fail", "error"].includes(c.status);
      const sev = c.severity === "blocker" ? "" : c.severity === "warning" ? " (warning)" : " (info)";
      return h("tr", {},
        multi ? h("td", {}, c.device || "—") : null,
        h("td", { class: "name" }, c.label, h("small", {}, c.severity)),
        h("td", {}, h("span", { class: `badge ${failed && c.severity !== "blocker" ? "warnsev" : c.status}` },
          (failed && c.overridden_by ? "overridden" : c.status) + (failed ? sev : ""))),
        h("td", {}, c.value || "—"),
        h("td", {}, c.detail ? h("pre", { class: "detail" }, c.detail) : "",
          c.overridden_by ? h("div", { class: "override" }, `Override by ${c.overridden_by}: ${c.override_reason}`) : null),
        h("td", { class: "actions" }, canOverride && failed && c.severity === "blocker" && !c.overridden_by && c.overridable
          ? h("button", { class: "small", onclick: () => overrideCheck(c) }, "Override…") : ""));
    })));
}

function renderJobPane() {
  const j = jobs.current, pane = $("#job-pane");
  if (jobs.tab === "procedure") {
    if (!j.steps.length) return pane.replaceChildren(h("p", { class: "muted" }, "The procedure is worked out from the pre-checks when the job starts."));
    const working = (j.busy && !j.queued) || JOB_WORKING.includes(j.status);
    pane.replaceChildren(h("p", { class: "muted" }, j.mode === "rollback" ? "Roll back procedure" : `Upgrade procedure — ${j.path_label}`),
      h("ol", { class: "steps" }, j.steps.map((s, i) => h("li", { class: i < j.step_index ? "done" : i === j.step_index ? (working ? "current" : "next") : "" },
        h("span", { class: "n" }, i < j.step_index ? "" : i + 1),
        h("span", {}, s.label, i === j.step_index && working ? [" ", h("span", { class: "spin" })] : ""),
        h("span", {}, s.reload ? h("span", { class: "tag", title: "Takes the device down; only inside the change window" }, "reload") : "",
          s.gate ? h("span", { class: "tag gate", title: "Failures stop the job here" }, "check") : "")))));
  } else if (jobs.tab === "checks") {
    pane.replaceChildren(h("h3", {}, `Pre-checks${j.pre_run ? ` (run ${j.pre_run})` : ""}`), checksTable(j.checks.pre, "pre"),
      h("h3", {}, "Image on the device"), checksTable(j.checks.stage, "stage"),
      h("h3", {}, "Post-checks"), checksTable(j.checks.post, "post"));
  } else if (jobs.tab === "circuits") {
    const c = j.circuits.started || j.circuits.planned;
    if (!c || !c.count) return pane.replaceChildren(h("p", { class: "empty" }, "No circuits in the circuit list use this device."));
    pane.replaceChildren(h("p", { class: "muted" }, `${c.count} circuit(s) recorded ${j.circuits.started ? "at start" : "when the job was planned"} (${fmtTime(c.created_at)}), from ${c.source}.`),
      ...c.groups.map((g) => h("div", {}, h("h3", {}, `${g.service} — VLAN ${g.vlan} (${g.circuits.length})`),
        h("table", {}, h("thead", {}, h("tr", {}, ["Port (list)", "On the network", "Device", "Type", "IP", "MAC", "Location", "Drawing"].map((t) => h("th", {}, t)))),
          h("tbody", {}, g.circuits.map((x) => h("tr", {}, h("td", {}, h("code", {}, x.port || "—")), liveCell(x), h("td", { class: "name" }, x.device_name || "—"),
            h("td", {}, x.device_type || "—"), h("td", {}, h("code", {}, x.ip || "—")), h("td", {}, h("code", {}, x.live_mac || x.mac || "—")),
            h("td", {}, [x.floor, x.room].filter(Boolean).join(" / ") || "—"), h("td", {}, x.drawing_number || "—"))))))));
  } else {
    pane.replaceChildren(h("table", {}, h("thead", {}, h("tr", {}, ["Time", "Unit", "Step", "Event"].map((t) => h("th", {}, t)))),
      h("tbody", {}, [...j.events].reverse().map((e) => h("tr", { class: `evt-${e.level}` },
        h("td", {}, fmtTime(e.time)), h("td", {}, e.device || ""), h("td", {}, e.step), h("td", {}, h("pre", { class: "detail" }, e.message)))))));
  }
}

async function jobAction(action, confirmText) {
  const j = jobs.current;
  let body;
  if (!j.dry_run && ["start", "continue", "rollback"].includes(action)) {
    const words = { start: "start the LIVE upgrade", continue: "continue the LIVE upgrade", rollback: "roll back for real" }[action];
    const typed = prompt(`To ${words} of ${j.units.map((u) => u.name).join(" and ")} to ${action === "rollback" ? j.from_version : j.target_version}, type the device name (${j.device.name}):`);
    if (typed === null) return;
    body = { confirm: typed };
  } else if (confirmText && !confirm(confirmText)) {
    return;
  }
  try {
    await api(`/api/firmware/jobs/${j.id}/${action}`, { method: "POST", body });
    setTimeout(() => refreshJob(j.id), 300);
  } catch (e) {
    toast(e.message);
  }
}

async function stopJob() {
  if (!confirm("Stop after the step that is running now? The job pauses and Continue carries on later. A step that is already running (e.g. a reload) is never interrupted.")) return;
  try {
    jobs.current = await api(`/api/firmware/jobs/${jobs.current.id}/stop`, { method: "POST" });
    renderJob();
  } catch (e) {
    toast(e.message);
  }
}

async function overrideCheck(c) {
  const reason = prompt(`Override "${c.label}"${c.device ? ` on ${c.device}` : ""}\n\n${c.detail || c.value}\n\nWhy is it safe to continue? (at least 10 characters; this goes in the job record)`);
  if (reason === null) return;
  try {
    jobs.current = await api(`/api/firmware/jobs/${jobs.current.id}/checks/${c.id}/override`, { method: "POST", body: { reason } });
    renderJob();
  } catch (e) {
    toast(e.message);
  }
}

async function cancelJob() {
  const changed = jobs.current.units.filter((u) => ["activated", "checked", "failed"].includes(u.status));
  const reason = prompt((changed.length ? `Warning: ${changed.map((u) => u.name).join(", ")} already changed. Consider Roll back instead.\n\n` : "") +
    "Why is this job being cancelled? (at least 10 characters)");
  if (reason === null) return;
  try {
    jobs.current = await api(`/api/firmware/jobs/${jobs.current.id}/cancel`, { method: "POST", body: { reason } });
    renderJob();
  } catch (e) {
    toast(e.message);
  }
}

// Device detail: upgrade history

async function loadDeviceUpgrades() {
  const pane = $("#detail-upgrades");
  pane.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const list = await api(`/api/firmware/devices/${state.detailDevice.id}/jobs`);
    if (!list.length) return pane.replaceChildren(h("p", { class: "empty" }, "No upgrade jobs for this device yet."));
    pane.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["#", "Upgrade", "Status", "Change", "Started", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, list.map((j) => h("tr", {},
        h("td", {}, `#${j.id}`), h("td", {}, h("code", {}, `${j.from_version || "?"} → ${j.target_version}`), h("small", { class: "sub" }, j.path_label)),
        h("td", {}, h("span", { class: `badge ${j.status}` }, JOB_STATUS[j.status] || j.status), " ", modeBadge(j)),
        h("td", {}, j.change_ref || "—"), h("td", {}, j.started_at ? fmtTime(j.started_at) : "—"),
        h("td", { class: "actions" },
          h("a", { class: "button small", href: `/api/firmware/jobs/${j.id}/report.html`, target: "_blank", rel: "noopener" }, "Report"),
          h("button", { class: "small", onclick: () => { $("#detail-dialog").close(); openJob(j.id); } }, "Open")))))));
  } catch (e) {
    pane.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

// ---------- credentials ----------

async function loadCredentials() {
  try {
    state.credentials = await api("/api/credentials");
  } catch (e) {
    return toast(e.message);
  }
  $("#credential-table tbody").replaceChildren(...state.credentials.map((c) => h("tr", {},
    h("td", { class: "name" }, c.name),
    h("td", {}, c.username),
    h("td", {}, c.has_enable_secret ? "set" : "—"),
    h("td", {}, c.device_count),
    h("td", {}, fmtTime(c.updated_at)),
    h("td", { class: "actions" },
      h("button", { class: "small", onclick: () => openCredentialDialog(c) }, "Edit"),
      h("button", { class: "small danger", disabled: c.device_count > 0, onclick: () => deleteCredential(c) }, "Delete")))));
}

function openCredentialDialog(cred = null) {
  const form = $("#credential-form");
  form.reset();
  $(".error", form).hidden = true;
  $("#credential-dialog-title").textContent = cred ? `Edit ${cred.name}` : "Add credential";
  $("#credential-edit-hint").hidden = !cred;
  form.password.required = !cred;
  if (cred) {
    form.name.value = cred.name;
    form.username.value = cred.username;
  }
  $("#credential-dialog").dataset.credId = cred ? cred.id : "";
  $("#credential-dialog").showModal();
}
$("#add-credential").addEventListener("click", () => openCredentialDialog());

$("#credential-form").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const form = ev.target;
  const id = $("#credential-dialog").dataset.credId;
  const body = { name: form.name.value, username: form.username.value };
  if (form.password.value) body.password = form.password.value;
  if (form.enable_secret.value) body.enable_secret = form.enable_secret.value;
  try {
    await api(id ? `/api/credentials/${id}` : "/api/credentials", { method: id ? "PUT" : "POST", body });
    $("#credential-dialog").close();
    loadCredentials();
  } catch (e) {
    const err = $(".error", form);
    err.textContent = e.message;
    err.hidden = false;
  }
});

async function deleteCredential(cred) {
  if (!confirm(`Delete credential profile ${cred.name}?`)) return;
  try {
    await api(`/api/credentials/${cred.id}`, { method: "DELETE" });
    loadCredentials();
  } catch (e) {
    toast(e.message);
  }
}

// ---------- users ----------

const users = { rows: [], meta: null, editing: null };
const SOURCE_LABEL = { ad: "Active Directory", local: "Local password" };

async function loadUsers() {
  try {
    [users.meta, users.rows] = await Promise.all([users.meta || api("/api/users/meta"), api("/api/users")]);
  } catch (e) {
    return toast(e.message);
  }
  const m = users.meta, g = m.ad_groups;
  $("#users-intro").textContent = "Users added here get exactly the permissions set here. " +
    (m.ldap_enabled ? `Other AD users still sign in with their AD groups (admin: ${g.admin || "not set"}; viewer: ${g.viewer || "any domain user"}; upgrades: ${g.upgrader || "admins"}).`
      : "Active Directory isn't set up on this server, so add local users.") +
    (m.break_glass_user ? ` The break-glass account "${m.break_glass_user}" always has full rights.` : "");
  renderUsers();
}

function renderUsers() {
  const q = $("#users-search").value.trim().toLowerCase();
  const rows = users.rows.filter((u) => !q || [u.username, u.display_name, u.email, u.summary].some((v) => (v || "").toLowerCase().includes(q)));
  $("#users-table tbody").replaceChildren(...rows.map((u) => h("tr", { class: u.enabled ? "" : "disabled" },
    h("td", {}, h("span", { class: `dot ${u.enabled ? "success" : "disabled"}`, title: u.enabled ? "Enabled" : "Disabled" })),
    h("td", { class: "name" }, u.username, h("small", {}, [u.display_name, u.email].filter(Boolean).join(" · "))),
    h("td", {}, SOURCE_LABEL[u.source] || u.source, u.two_factor ? h("span", { class: "badge success", title: "Signs in with a code from an authenticator app too" }, "2FA") : null),
    h("td", {}, u.is_admin ? h("span", { class: "badge success" }, "Administrator") : permChips(u.permissions)),
    h("td", {}, u.last_login ? fmtTime(u.last_login) : "never"),
    h("td", {}, fmtTime(u.updated_at), h("small", { class: "sub" }, u.updated_by)),
    h("td", { class: "actions" },
      h("button", { class: "small", onclick: () => openUserDialog(u) }, "Edit"),
      u.source === "local" ? h("button", { class: "small", onclick: () => openPasswordDialog(u) }, "Reset password") : null,
      u.two_factor ? h("button", { class: "small", title: "For a lost phone: they set two-factor up again", onclick: async () => {
        if (!confirm(`Turn off two-factor sign-in for ${u.username}? They set it up again (at their next sign-in if it is required).`)) return;
        try { await api(`/api/users/${u.id}/two-factor/reset`, { method: "POST" }); toast("Two-factor reset"); loadUsers(); } catch (e) { toast(e.message); }
      } }, "Reset 2FA") : null,
      h("button", { class: "small danger", onclick: () => deleteUser(u) }, "Delete")))));
  $("#users-empty").hidden = users.rows.length > 0;
}

function permChips(perms) {
  const areas = users.meta.areas;
  return h("span", { class: "chips" }, Object.keys(areas).map((a) =>
    h("span", { class: `chip ${perms[a] === "none" ? "off" : ""}`, title: areas[a].levels[perms[a]] },
      `${areas[a].label}: ${perms[a].replace("_", " ")}`)));
}

$("#users-search").addEventListener("input", renderUsers);
$("#user-add").addEventListener("click", () => openUserDialog(null));
$("#user-cancel").addEventListener("click", () => $("#user-dialog").close());

function openUserDialog(u) {
  users.editing = u;
  const m = users.meta, form = $("#user-form");
  form.reset();
  $(".error", form).hidden = true;
  $("#user-dialog-title").textContent = u ? `Edit ${u.username}` : "Add user";
  form.source.replaceChildren(...Object.entries(m.sources).filter(([k]) => m.ldap_enabled || k === "local" || (u && u.source === k))
    .map(([k, label]) => h("option", { value: k }, label)));
  form.username.disabled = form.source.disabled = !!u;
  form.username.value = u ? u.username : "";
  form.source.value = u ? u.source : (m.ldap_enabled ? "ad" : "local");
  form.display_name.value = u ? u.display_name : "";
  form.email.value = u ? u.email : "";
  form.enabled.checked = u ? u.enabled : true;
  form.is_admin.checked = u ? u.is_admin : false;
  form.notes.value = u ? u.notes : "";
  $("#user-perms").replaceChildren(...Object.entries(m.areas).map(([a, def]) =>
    h("label", {}, def.label, h("select", { name: `perm_${a}` },
      Object.entries(def.levels).map(([lv, text]) => h("option", { value: lv }, `${lv.replace("_", " ")} - ${text}`))))));
  setPerms(u ? u.permissions : m.presets.viewer.perms);
  $("#user-presets").replaceChildren(h("span", { class: "muted" }, "Presets:"), ...Object.entries(m.presets).map(([k, p]) =>
    h("button", { type: "button", class: "small", onclick: () => { setPerms(p.perms); form.is_admin.checked = p.admin; syncAdmin(); } }, p.label)));
  const syncPassword = () => {
    const local = form.source.value === "local";
    $("#user-password-row").hidden = !local || !!u;
    form.password.required = local && !u;
  };
  form.source.onchange = syncPassword;
  form.is_admin.onchange = syncAdmin;
  syncPassword();
  syncAdmin();
  $("#user-dialog").showModal();
}

function setPerms(perms) {
  const form = $("#user-form");
  Object.entries(perms).forEach(([a, lv]) => { if (form[`perm_${a}`]) form[`perm_${a}`].value = lv; });
}

function syncAdmin() {
  const form = $("#user-form"), admin = form.is_admin.checked;
  if (admin) setPerms(users.meta.presets.admin.perms);
  $$("#user-perms select").forEach((sel) => (sel.disabled = admin));
}

$("#user-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, err = $(".error", form), u = users.editing;
  const permissions = Object.fromEntries(Object.keys(users.meta.areas).map((a) => [a, form[`perm_${a}`].value]));
  const body = { display_name: form.display_name.value, email: form.email.value, enabled: form.enabled.checked,
    is_admin: form.is_admin.checked, permissions, notes: form.notes.value };
  try {
    if (u) await api(`/api/users/${u.id}`, { method: "PUT", body });
    else await api("/api/users", { method: "POST", body: { ...body, username: form.username.value, source: form.source.value, password: form.password.value } });
    $("#user-dialog").close();
    toast(u ? "User updated" : "User added");
    loadUsers();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
});

async function deleteUser(u) {
  if (!confirm(`Delete ${u.username}? Their activity stays in the activity log.`)) return;
  try {
    await api(`/api/users/${u.id}`, { method: "DELETE" });
    loadUsers();
  } catch (e) {
    toast(e.message);
  }
}

// Password: an admin resets a local user's, or a local user changes their own
let passwordFor = null;
function openPasswordDialog(u) {
  passwordFor = u;
  const form = $("#password-form");
  form.reset();
  $(".error", form).hidden = true;
  $("#password-title").textContent = u ? `New password for ${u.username}` : "Change your password";
  $("#password-current-row").hidden = !!u;
  form.current.required = !u;
  $("#password-dialog").showModal();
}
$("#change-password").addEventListener("click", () => openPasswordDialog(null));
$("#password-cancel").addEventListener("click", () => $("#password-dialog").close());
$("#password-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, err = $(".error", form);
  err.hidden = true;
  if (form.new.value !== form.again.value) {
    err.textContent = "The two new passwords don't match";
    err.hidden = false;
    return;
  }
  try {
    if (passwordFor) await api(`/api/users/${passwordFor.id}/password`, { method: "POST", body: { password: form.new.value } });
    else await api("/api/auth/password", { method: "POST", body: { current: form.current.value, new: form.new.value } });
    $("#password-dialog").close();
    toast("Password changed");
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
});

// ---------- activity ----------

const JOB_DONE = { completed: "success", completed_overrides: "changed", rolled_back: "changed", failed: "failed",
  needs_attention: "failed", cancelled: "never" };

function activityParams() {
  const p = new URLSearchParams();
  const v = (id) => $(id).value;
  if (v("#act-user")) p.set("user", v("#act-user"));
  if (v("#act-area")) p.set("area", v("#act-area"));
  if (v("#act-since")) p.set("since", `${v("#act-since")}T00:00:00`);
  if (v("#act-until")) p.set("until", `${v("#act-until")}T23:59:59`);
  return p.toString();
}

async function loadAudit() {
  let d;
  try {
    d = await api(`/api/activity?${activityParams()}`);
  } catch (e) {
    return toast(e.message);
  }
  $("#act-csv").href = `/api/activity.csv?${activityParams()}`;
  const keepUser = $("#act-user").value, keepArea = $("#act-area").value;
  fillSelect($("#act-user"), "All users", d.users.map((u) => [u, u]));
  fillSelect($("#act-area"), "All areas", Object.entries(d.areas));
  $("#act-user").value = keepUser;
  $("#act-area").value = keepArea;
  $("#act-range").textContent = `From ${fmtTime(d.since)} to ${fmtTime(d.until)} (default: the last 30 days).`;
  const cols = d.columns.filter((c) => d.summary.some((s) => s[c.key]));
  $("#act-summary thead").replaceChildren(h("tr", {}, h("th", {}, "User"), ...cols.map((c) => h("th", {}, c.label)), h("th", {}, "Last activity")));
  $("#act-summary tbody").replaceChildren(...d.summary.map((s) => h("tr", {},
    h("td", { class: "name" }, h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); $("#act-user").value = s.username; loadAudit(); } }, s.username)),
    ...cols.map((c) => h("td", {}, s[c.key] || "")), h("td", {}, s.last_activity ? fmtTime(s.last_activity) : "—"))));
  $("#act-jobs tbody").replaceChildren(...(d.jobs.length ? d.jobs.map((j) => h("tr", {},
    h("td", {}, `#${j.id}`, j.change_ref ? h("small", { class: "sub" }, j.change_ref) : null), h("td", {}, j.device),
    h("td", {}, j.dry_run ? "dry run" : h("b", {}, "LIVE")), h("td", {}, `${j.from_version || "?"} → ${j.target_version}`),
    h("td", {}, j.created_by, h("small", { class: "sub" }, fmtTime(j.created_at))),
    h("td", {}, j.started_by || "—", j.started_at ? h("small", { class: "sub" }, fmtTime(j.started_at)) : null),
    h("td", {}, h("span", { class: `badge ${JOB_DONE[j.status] || "running"}` }, j.status.replace(/_/g, " ")))))
    : [h("tr", {}, h("td", { colspan: 7, class: "muted" }, "None in this period."))]));
  $("#act-backups tbody").replaceChildren(...(d.backups.length ? d.backups.map((b) => h("tr", {},
    h("td", {}, fmtTime(b.started_at)), h("td", {}, b.device), h("td", {}, b.by),
    h("td", {}, h("span", { class: `badge ${b.status === "success" ? "success" : b.status === "running" ? "running" : "failed"}` }, b.status),
      b.changed ? h("small", { class: "sub" }, "config changed") : null, b.status === "failed" ? h("span", { class: "errtext" }, b.message) : null)))
    : [h("tr", {}, h("td", { colspan: 4, class: "muted" }, "None in this period."))]));
  $("#audit-table tbody").replaceChildren(...d.events.map((r) => h("tr", {},
    h("td", {}, fmtTime(r.timestamp)), h("td", {}, r.username), h("td", {}, d.areas[r.area] || r.area),
    h("td", {}, r.action), h("td", {}, r.detail))));
}
["#act-user", "#act-area", "#act-since", "#act-until"].forEach((sel) => $(sel).addEventListener("change", loadAudit));

// ---------- first-run setup and Settings ----------
// A new install has no way to sign in, so the first visit shows the setup screen. Every
// step needs the setup code from the server (sudo cat /var/lib/netops/setup-token).
// Afterwards admins change the same AD and certificate settings on the Settings page.

const setup = { code: "", step: "code", done: new Set() };
const SETUP_STEPS = [["code", "Setup code"], ["admin", "Admin account"], ["ad", "Active Directory"],
  ["cert", "Certificate"], ["finish", "Finish"]];

/** The setup API: with the setup code during setup, as the signed-in admin afterwards. */
function sapi(path, options = {}) {
  return api(`/api/setup${path}`, { ...options, headers: setup.code ? { "X-Setup-Code": setup.code } : {} });
}

const field = (label, name, attrs = {}) => h("label", {}, label, h("input", { name, ...attrs }));
const errorLine = () => h("p", { class: "error", hidden: true });
function showError(el, e) { el.textContent = e.message || String(e); el.hidden = false; }

function showSetup() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = true;
  $("#setup-view").hidden = false;
  renderSetup();
}

function goStep(step) {
  setup.done.add(setup.step);
  setup.step = step;
  renderSetup();
}

function renderSetup() {
  $("#setup-steps").replaceChildren(...SETUP_STEPS.map(([id, label]) => h("li", {
    class: id === setup.step ? "current" : setup.done.has(id) ? "done" : "" }, label)));
  const steps = { code: setupCodeStep, admin: setupAdminStep, finish: setupFinishStep,
    ad: () => adPanel({ next: () => goStep("cert") }),
    cert: () => certPanel({ next: () => goStep("finish") }) };
  const body = $("#setup-body");
  body.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  Promise.resolve(steps[setup.step]()).then((el) => body.replaceChildren(el));
}

function setupCodeStep() {
  const err = errorLine();
  return h("form", { class: "panel", onsubmit: async (ev) => {
    ev.preventDefault();
    setup.code = ev.target.code.value.trim();
    try {
      await sapi("/check-code", { method: "POST" });
      goStep("admin");
    } catch (e) {
      setup.code = "";
      showError(err, e);
    }
  } },
  h("p", {}, "This server hasn't been set up yet. To prove you look after it, enter the setup code. ",
    "On the server, run:"),
  h("pre", {}, "sudo cat /var/lib/netops/setup-token"),
  field("Setup code", "code", { required: true, autocomplete: "off", autofocus: true, placeholder: "XXXX-XXXX-XXXX-XXXX-XXXX" }),
  err, h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "Continue")));
}

function setupAdminStep() {
  const err = errorLine();
  return h("form", { class: "panel", onsubmit: async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    if (f.password.value !== f.repeat.value) return showError(err, "The passwords don't match");
    try {
      await sapi("/admin", { method: "POST", body: { username: f.username.value,
        display_name: f.display_name.value, password: f.password.value } });
      goStep("ad");
    } catch (e) {
      showError(err, e);
    }
  } },
  h("h2", {}, "Admin account"),
  h("p", { class: "muted" }, "A local account with full rights. It also works when Active Directory is down: ",
    "keep the password in your vault. You can add AD users and more admins later on the Users page."),
  field("Username", "username", { required: true, value: "admin", autocomplete: "username" }),
  field("Display name", "display_name", { placeholder: "e.g. Network team admin" }),
  field("Password (at least 12 characters)", "password", { type: "password", required: true, minlength: 12, autocomplete: "new-password" }),
  field("Repeat the password", "repeat", { type: "password", required: true, autocomplete: "new-password" }),
  err, h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "Create and continue")));
}

const AD_FIELDS = [
  ["ldap_url", "Server", "ldaps://dc1.corp.local"],
  ["ldap_domain", "Domain", "corp.local"],
  ["ldap_base_dn", "Base DN", "DC=corp,DC=local"],
  ["ldap_admin_group", "Admin group DN", "CN=NetOps-Admins,OU=Groups,DC=corp,DC=local"],
  ["ldap_viewer_group", "Viewer group DN (empty: every domain user can sign in)", "CN=NetOps-Viewers,OU=Groups,DC=corp,DC=local"],
  ["ldap_upgrader_group", "Upgrader group DN (empty: admins run upgrades)", "CN=NetOps-Upgraders,OU=Groups,DC=corp,DC=local"],
];

/** The Active Directory form, used in setup (with next) and on the Settings page. */
async function adPanel({ next } = {}) {
  const ad = await sapi("/ad");
  const err = errorLine();
  const result = h("p", { hidden: true });
  const form = h("form", { class: "panel" });
  const values = () => {
    const v = Object.fromEntries(AD_FIELDS.map(([k]) => [k, form[k].value.trim()]));
    return { ...v, ca_pem: form.ca_pem.value.trim() };
  };
  form.replaceChildren(
    h("h2", {}, "Active Directory"),
    h("p", { class: "muted" }, "Users sign in with their domain account over LDAPS. The admin, viewer and upgrader groups ",
      "give permissions to anyone not added on the Users page. ", next ? "Skip this step to use local accounts only." : ""),
    ...AD_FIELDS.map(([k, label, placeholder]) => {
      const locked = ad.from_env.includes(k);
      return field(locked ? `${label} (set in netops.env)` : label, k,
        { value: ad.values[k] || "", placeholder: `e.g. ${placeholder}`, disabled: locked });
    }),
    h("label", {}, `CA certificate that signed the domain controllers' certificates (PEM)${ad.ca_saved ? " - one is saved; paste a new one to replace it" : ""}`,
      h("textarea", { name: "ca_pem", class: "pem", placeholder: "-----BEGIN CERTIFICATE-----" })),
    h("h2", {}, "Test with a real sign-in"),
    h("p", { class: "muted" }, "Uses the settings above before they are saved, and shows what this user would get."),
    h("div", { class: "grid2" }, field("Username", "test_user", { autocomplete: "off" }),
      field("Password", "test_password", { type: "password", autocomplete: "off" })),
    result, err,
    h("div", { class: "actions" },
      h("button", { type: "button", onclick: async () => {
        err.hidden = true;
        try {
          const r = await sapi("/ad/test", { method: "POST", body: { ...values(),
            username: form.test_user.value, password: form.test_password.value } });
          result.textContent = r.message;
          result.className = r.ok ? "ok-text" : "error";
          result.hidden = false;
        } catch (e) { showError(err, e); }
      } }, "Test sign-in"),
      h("button", { type: "submit", class: "primary" }, next ? "Save and continue" : "Save"),
      next ? h("button", { type: "button", class: "ghost", onclick: next }, "Skip") : null));
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    try {
      await sapi("/ad", { method: "PUT", body: values() });
      if (next) next(); else toast("Active Directory settings saved");
    } catch (e) { showError(err, e); }
  };
  return form;
}

function certSummary(c) {
  if (!c.certificate) return h("p", { class: "muted" }, "No certificate has been saved here yet: the server uses the one ",
    "the installer made (self-signed, so browsers warn about it).");
  const i = c.certificate;
  return h("dl", { class: "kv" },
    h("dt", {}, "Issued to"), h("dd", {}, i.subject),
    h("dt", {}, "Names"), h("dd", {}, i.names.join(", ") || "—"),
    h("dt", {}, "Issued by"), h("dd", {}, i.self_signed ? "itself (self-signed)" : i.issuer),
    h("dt", {}, "Valid until"), h("dd", {}, fmtTime(i.not_after)),
    h("dt", {}, "Installed"), h("dd", {}, c.applied || "waiting for the server to install it"));
}

/** The certificate panel: make a request or upload one; used in setup and on Settings. */
async function certPanel({ next } = {}) {
  const c = await sapi("/certificate");
  const err = errorLine();
  const csrBox = h("textarea", { class: "pem", readonly: true, hidden: !c.request });
  csrBox.value = c.request || "";
  const download = h("a", { class: "button", hidden: !c.request, download: "netops.csr" }, "Download the request");
  const setDownload = () => { download.href = URL.createObjectURL(new Blob([csrBox.value], { type: "application/pkcs10" })); };
  if (c.request) setDownload();
  const names = h("input", { name: "names", value: location.hostname });
  const certIn = h("textarea", { class: "pem", placeholder: "-----BEGIN CERTIFICATE----- (the server's certificate, then any intermediate)" });
  const keyIn = h("textarea", { class: "pem", placeholder: "-----BEGIN PRIVATE KEY----- (leave empty if you made the request here)" });
  const box = h("div", { class: "panel" });
  box.replaceChildren(
    h("h2", {}, "Web certificate"),
    certSummary(c),
    h("h2", {}, "A: make a key and a request here"),
    h("p", { class: "muted" }, "The private key is made on the server and never leaves it. Send the request to your CA, then paste the certificate it issues below."),
    h("label", {}, "DNS names (and IP addresses), separated by commas", names),
    h("div", { class: "actions" }, h("button", { type: "button", onclick: async () => {
      err.hidden = true;
      try {
        const r = await sapi("/certificate/request", { method: "POST", body: { names: names.value.split(",").map((n) => n.trim()).filter(Boolean) } });
        csrBox.value = r.request;
        csrBox.hidden = download.hidden = false;
        setDownload();
      } catch (e) { showError(err, e); }
    } }, "Make the request"), download),
    csrBox,
    h("h2", {}, "B: install the certificate"),
    h("label", {}, "Certificate (PEM)", certIn),
    h("label", {}, "Private key (PEM) - only if you didn't make the request here", keyIn),
    err,
    h("div", { class: "actions" },
      h("button", { type: "button", class: "primary", onclick: async () => {
        err.hidden = true;
        try {
          await sapi("/certificate", { method: "POST", body: { certificate: certIn.value, key: keyIn.value } });
          toast("Certificate saved: the server installs it within a few seconds. Reload the page to use it.");
          if (next) next(); else box.replaceWith(await certPanel());
        } catch (e) { showError(err, e); }
      } }, "Install"),
      next ? h("button", { type: "button", class: next ? "ghost" : "", onclick: next }, "Skip for now") : null));
  return box;
}

function setupFinishStep() {
  const err = errorLine();
  return h("div", { class: "panel" },
    h("h2", {}, "Finish"),
    h("p", {}, "Setup is complete when you press Finish: the setup code stops working, and you sign in with the admin account",
      " (or an AD account in the admin group)."),
    h("p", { class: "muted" }, "Active Directory and the certificate can be changed later by an admin, on the Settings page."),
    err,
    h("div", { class: "actions" },
      h("button", { class: "ghost", onclick: () => goStep("admin") }, "Back"),
      h("button", { class: "primary", onclick: async () => {
        try {
          await sapi("/finish", { method: "POST" });
          setup.code = "";
          $("#setup-view").hidden = true;
          showLogin();
          toast("Setup finished - sign in with the admin account");
        } catch (e) { showError(err, e); }
      } }, "Finish setup")));
}

// ---------- licence ----------
// Everyone sees the banner when new work is blocked; admins also see trial and renewal notices.

async function showLicenceBanner() {
  const banner = $("#licence-banner");
  try {
    const s = await api("/api/licence");
    const show = s.warning && (!s.active || isAdmin());
    banner.textContent = show ? s.warning : "";
    banner.classList.toggle("blocked", !s.active);
    banner.hidden = !show;
  } catch { banner.hidden = true; }
}

async function licencePanel() {
  const s = await api("/api/licence");
  const err = errorLine();
  const text = h("textarea", { class: "pem", placeholder: "-----BEGIN LICENCE----- … -----END LICENCE-----" });
  const l = s.licence;
  const box = h("div", { class: "panel" });
  box.replaceChildren(
    h("h2", {}, "Licence"),
    h("p", { class: s.active ? "" : "error" }, s.message),
    s.warning && s.active && s.mode !== "trial" ? h("p", { class: "muted" }, s.warning) : "",
    h("dl", { class: "kv" },
      h("dt", {}, "Tools unlocked"), h("dd", {}, h("span", { class: "chips" }, Object.entries(s.module_labels).map(([m, label]) =>
        h("span", { class: `chip ${s.modules.includes(m) ? "" : "off"}`, title: s.modules.includes(m) ? "Unlocked" : "Not in the licence" }, label)))),
      ...(s.edition ? [h("dt", {}, "Edition"), h("dd", {}, s.edition)] : []),
      h("dt", {}, "Devices"), h("dd", {}, s.max_devices == null ? `${s.devices} (no limit)` : `${s.devices} of ${s.max_devices}`,
        s.meraki_orgs ? h("small", { class: "muted" }, ` (${s.physical_devices} devices + ${s.meraki_orgs} Meraki organisation${s.meraki_orgs > 1 ? "s" : ""} × ${s.meraki_devices_each})`) : null),
      ...(l ? [h("dt", {}, "Licence"), h("dd", {}, `${l.id}${l.kind === "internal" ? " (internal use)" : ""}, issued ${l.issued}`)] : []),
      h("dt", {}, "Installation ID"), h("dd", {}, h("code", {}, s.install_id))),
    h("p", { class: "muted" }, "Send the installation ID when you ask for a licence. Paste the licence you receive below."),
    text, err,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: async () => {
      err.hidden = true;
      try {
        await api("/api/licence", { method: "POST", body: { text: text.value } });
        toast("Licence added");
        setTimeout(() => location.reload(), 800);  // the tools it unlocks appear straight away
      } catch (e) { showError(err, e); }
    } }, "Add licence")));
  return box;
}

/** Site name and day-to-day defaults; a value set in netops.env is shown but locked. */
async function optionsPanel() {
  const options = await sapi("/options");
  const err = errorLine();
  const inputs = {};
  const rows = options.map((o) => {
    const attrs = { name: o.key, disabled: o.locked };
    let input;
    if (o.kind === "bool") {
      input = h("input", { ...attrs, type: "checkbox", checked: o.value });
    } else if (o.kind === "int") {
      input = h("input", { ...attrs, type: "number", min: o.low, max: o.high, value: o.value });
    } else {
      input = h("input", { ...attrs, value: o.value, maxlength: o.high });
    }
    inputs[o.key] = { o, input };
    const note = o.locked ? "Set in netops.env" : (o.help || "");
    const extra = o.kind !== "str" && !o.locked ? `${note ? note + ". " : ""}Default ${o.kind === "bool" ? (o.default ? "yes" : "no") : o.default}` : note;
    return o.kind === "bool"
      ? h("label", { class: "check" }, input, " ", o.label, extra ? h("span", { class: "muted" }, ` (${extra})`) : "")
      : h("label", {}, o.label, input, extra ? h("span", { class: "muted" }, extra) : "");
  });
  const box = h("div", { class: "panel" });
  box.replaceChildren(
    h("h2", {}, "Site and defaults"),
    ...rows, err,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: async () => {
      err.hidden = true;
      const body = {};
      for (const [key, { o, input }] of Object.entries(inputs)) {
        if (o.locked) continue;
        body[key] = o.kind === "bool" ? input.checked : o.kind === "int" ? Number(input.value) : input.value;
      }
      try {
        await sapi("/options", { method: "PUT", body });
        $("#site-name").textContent = body.site_name || "";
        $("#site-name").hidden = !body.site_name;
        toast("Settings saved");
      } catch (e) { showError(err, e); }
    } }, "Save")));
  return box;
}

/** Wall displays: read-only status screens on their own port, each with its own link. */
async function displaysPanel() {
  const { port, screens, page_names: pageNames } = await api("/api/displays");
  const err = errorLine();
  const name = h("input", { name: "display_name", placeholder: "e.g. NOC wall 1", maxlength: 100 });
  // Which pages a screen rotates through (none ticked: all of them)
  const pagePicker = (chosen) => h("span", { class: "chips" }, ...Object.entries(pageNames).map(([k, l]) =>
    h("label", { class: "check" }, h("input", { type: "checkbox", "data-page": k, checked: chosen.includes(k) }), ` ${l}`)));
  const picked = (el) => $$("input[data-page]", el).filter((c) => c.checked).map((c) => c.dataset.page);
  const newPages = pagePicker(Object.keys(pageNames));
  const linkFor = (key) => `https://${location.hostname}:${port}/display/#key=${key}`;
  const shown = h("div", { hidden: true });
  const box = h("div", { class: "panel" });
  const rows = screens.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Screen"), h("th", {}, "Pages"), h("th", {}, "Last connected"), h("th", {}, "From"), h("th", {}, ""))),
    h("tbody", {}, screens.map((s) => { const pick = pagePicker(s.pages); return h("tr", {}, h("td", {}, s.name),
      h("td", {}, pick, h("button", { type: "button", class: "small", onclick: async () => {
        try { await api(`/api/displays/${s.id}`, { method: "PUT", body: { name: s.name, pages: picked(pick) } }); toast("Pages saved: the screen changes at its next refresh"); } catch (e) { showError(err, e); }
      } }, "Save pages")),
      h("td", {}, fmtTime(s.last_seen_at)),
      h("td", {}, s.last_seen_from || "—"),
      h("td", {}, h("button", { type: "button", class: "small", onclick: async () => {
        if (!confirm(`Remove "${s.name}"? Its link stops working straight away.`)) return;
        try { await api(`/api/displays/${s.id}`, { method: "DELETE" }); toast("Display removed"); loadSettings(); } catch (e) { showError(err, e); }
      } }, "Remove"))); })))
    : h("p", { class: "muted" }, "No wall displays yet.");
  box.replaceChildren(
    h("h2", {}, "Wall displays"),
    h("p", { class: "muted" }, `A read-only status screen for a NOC or office wall. Its pages take turns: the overview (backups, compliance, config changes, firmware, upgrades, server), the upgrades under way, a sites grid, and the network (syslog errors, config changes, circuits that moved or went missing). It shows names and counts only, never addresses or configs. It is served on port ${port} only; open that port in the server's firewall just for the screens' network.`),
    rows,
    h("label", {}, "Add a display", name), h("div", {}, h("span", { class: "muted" }, "Pages: "), newPages), err,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: async () => {
      err.hidden = true;
      try {
        const s = await api("/api/displays", { method: "POST", body: { name: name.value, pages: picked(newPages) } });
        const link = h("input", { readonly: true, value: linkFor(s.key) });
        shown.replaceChildren(h("p", {}, h("strong", {}, "Open this link on the screen's browser (full screen). It is shown only now: copy it before leaving the page."),
        ), link, h("div", { class: "actions" }, h("button", { type: "button", onclick: () => { link.select(); navigator.clipboard?.writeText(link.value); toast("Link copied"); } }, "Copy link")));
        shown.hidden = false;
        name.value = "";
        toast("Display added");
      } catch (e) { showError(err, e); }
    } }, "Add display")),
    shown);
  return box;
}

/** Email alerts through the customer's mail server. */
async function alertsPanel() {
  const a = await api("/api/alerts");
  const err = errorLine();
  const result = h("p", { class: "muted", hidden: true });
  const f = {};
  const check = (name, label, hint) => {
    f[name] = h("input", { type: "checkbox", checked: a[name] });
    return h("label", { class: "check" }, f[name], " ", label, hint ? h("span", { class: "muted" }, ` (${hint})`) : "");
  };
  const text = (name, label, attrs = {}) => {
    f[name] = h("input", { value: a[name] ?? "", ...attrs });
    return h("label", {}, label, f[name]);
  };
  f.smtp_security = h("select", {}, ...[["starttls", "STARTTLS (usually port 587)"], ["tls", "TLS (usually port 465)"], ["none", "None (port 25, internal relay only)"]]
    .map(([v, l]) => h("option", { value: v, selected: a.smtp_security === v }, l)));
  f.smtp_password = h("input", { type: "password", autocomplete: "new-password", placeholder: a.has_password ? "saved (leave empty to keep it)" : "" });
  f.clear_password = h("input", { type: "checkbox" });
  f.report_day = h("select", {}, ...[["", "Never (no scheduled report)"], ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"],
    ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]].map(([v, l]) => h("option", { value: v, selected: a.report_day === v }, l)));
  f.syslog_level = h("select", {}, ...[[0, "Emergency only"], [1, "Alert and worse"], [2, "Critical and worse"], [3, "Error and worse"]]
    .map(([v, l]) => h("option", { value: v, selected: a.syslog_level === v }, l)));
  // One row per recipient: the address and a tick for each kind of alert they get.
  const kinds = Object.entries(a.kinds);
  const rows = h("tbody");
  const recipientsTable = h("div", { class: "table-wrap" }, h("table", { class: "recipients" },
    h("thead", {}, h("tr", {}, h("th", {}, "Email address"), ...kinds.map(([, label]) => h("th", {}, label)), h("th", {}))), rows));
  const addRecipient = (r = { address: "", kinds: ["backups", "upgrades", "licence", "worker"] }) => {
    const tr = h("tr", {},
      h("td", {}, h("input", { type: "email", value: r.address, placeholder: "noc@corp.local", "aria-label": "Email address" })),
      ...kinds.map(([k, label]) => h("td", {}, h("input", { type: "checkbox", "data-kind": k, checked: r.kinds.includes(k), "aria-label": label }))),
      h("td", {}, h("button", { type: "button", class: "small ghost", title: "Remove", onclick: () => tr.remove() }, "✕")));
    rows.append(tr);
  };
  a.recipients.forEach(addRecipient);
  if (!a.recipients.length) addRecipient();
  const box = h("div", { class: "panel" });
  box.replaceChildren(
    h("h2", {}, "Email alerts"),
    h("p", { class: "muted" }, "Sent through your own mail server. Each event is sent once; checked every minute."),
    check("enabled", "Send email alerts"),
    text("smtp_host", "Mail server", { placeholder: "e.g. smtp.corp.local" }),
    text("smtp_port", "Port", { type: "number", min: 1, max: 65535 }),
    h("label", {}, "Security", f.smtp_security),
    text("smtp_user", "Username (if the server needs one)"),
    h("label", {}, "Password", f.smtp_password),
    a.has_password ? h("label", { class: "check" }, f.clear_password, " Remove the saved password") : "",
    text("mail_from", "From address", { placeholder: "e.g. netops@corp.local" }),
    h("h3", {}, "What is sent"),
    h("ul", { class: "muted" },
      h("li", {}, "Backups: a device's backup has been failing for longer than the hours below."),
      h("li", {}, "Config changes: a backup found a changed config (what changed, and who, when the device's syslog says)."),
      h("li", {}, "Compliance: a device's config starts failing a compliance rule."),
      h("li", {}, "Upgrades: a job completes, fails, rolls back or needs attention."),
      h("li", {}, "Licence: 30 and 7 days before it ends, and when it has ended."),
      h("li", {}, "Upgrade worker: stopped for more than 10 minutes."),
      h("li", {}, "Syslog: device messages at the level below or worse, gathered into one email.")),
    text("backup_hours", "Backups: alert when failing for more than (hours)", { type: "number", min: 1, max: 720 }),
    h("label", {}, "Syslog: messages at", f.syslog_level),
    text("syslog_minutes", "Syslog: at most one email every (minutes)", { type: "number", min: 1, max: 60 }),
    check("changes_diff", "Config changes: include the changed lines (lines that may hold a secret are left out)"),
    h("h3", {}, "Report"),
    h("p", { class: "muted" }, "A summary of backups, compliance, firmware, upgrades, circuits and syslog, emailed to everyone ticked for Report. The same report is on Activity › Report."),
    h("div", { class: "grid2" }, h("label", {}, "Send it every", f.report_day), text("report_time", "At (UTC, HH:MM)", { placeholder: "07:00" })),
    text("report_days", "Covering the last (days)", { type: "number", min: 1, max: 90 }),
    h("h3", {}, "Who gets what"),
    recipientsTable,
    h("div", { class: "actions" }, h("button", { type: "button", class: "small", onclick: () => addRecipient() }, "+ Add recipient")),
    a.last_error ? h("p", { class: "error" }, `Last error: ${a.last_error}`) : "",
    err, result,
    h("div", { class: "actions" },
      h("button", { type: "button", onclick: async () => {
        err.hidden = true;
        const body = { enabled: f.enabled.checked, smtp_host: f.smtp_host.value.trim(), smtp_port: Number(f.smtp_port.value),
          smtp_security: f.smtp_security.value, smtp_user: f.smtp_user.value.trim(), mail_from: f.mail_from.value.trim(),
          backup_hours: Number(f.backup_hours.value), syslog_level: Number(f.syslog_level.value),
          syslog_minutes: Number(f.syslog_minutes.value), changes_diff: f.changes_diff.checked,
          report_day: f.report_day.value, report_time: f.report_time.value.trim() || "07:00", report_days: Number(f.report_days.value) || 7,
          recipients: $$("tr", rows).map((tr) => ({ address: $("input[type=email]", tr).value.trim(),
            kinds: $$("input[data-kind]", tr).filter((c) => c.checked).map((c) => c.dataset.kind) })).filter((r) => r.address) };
        if (f.smtp_password.value) body.smtp_password = f.smtp_password.value;
        else if (f.clear_password.checked) body.smtp_password = "";
        try { await api("/api/alerts", { method: "PUT", body }); toast("Email alerts saved"); loadSettings(); } catch (e) { showError(err, e); }
      } }, "Save"),
      h("button", { type: "button", onclick: async () => {
        err.hidden = true;
        try {
          const r = await api("/api/alerts/test", { method: "POST" });
          result.textContent = r.ok ? `Test email: ${r.message}` : `Test email not sent: ${r.message}`;
          result.className = r.ok ? "ok-text" : "error";
          result.hidden = false;
        } catch (e) { showError(err, e); }
      } }, "Send test email"),
      h("button", { type: "button", title: "Email the report to its recipients now (save first)", onclick: async () => {
        err.hidden = true;
        try {
          const r = await api("/api/alerts/report-now", { method: "POST" });
          result.textContent = r.ok ? `Report: ${r.message}` : `Report not sent: ${r.message}`;
          result.className = r.ok ? "ok-text" : "error";
          result.hidden = false;
        } catch (e) { showError(err, e); }
      } }, "Send the report now")),
    a.recent.length ? h("div", {}, h("h2", {}, "Last alerts sent"), h("ul", {}, a.recent.map((r) => h("li", {}, `${fmtTime(r.sent_at)}: ${r.subject}`)))) : "");
  return box;
}

async function loadSettings() {
  const body = $("#settings-body");
  body.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const [lic, opts, mail, disp, ad, cert] = await Promise.all([licencePanel(), optionsPanel(), alertsPanel(), displaysPanel(), adPanel(), certPanel()]);
    body.replaceChildren(h("section", { class: "card" }, lic), h("section", { class: "card" }, opts),
      h("section", { class: "card" }, mail), h("section", { class: "card" }, disp), h("section", { class: "card" }, ad),
      h("section", { class: "card" }, cert));
  } catch (e) {
    body.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

// ---------- start ----------

api("/api/setup/status")
  .then((s) => (s.needed ? showSetup() : api("/api/auth/me").then(showApp).catch(showLogin)))
  .catch(showLogin);

// ---------- monitoring ----------

const mon = { rows: [], counts: {}, labels: {}, picked: new Set(), profiles: null, howto: null,
  device: null, hours: 24, editing: null };
const MON_ORDER = ["down", "warning", "unknown", "waiting", "up", "off"];
const MON_TILES = [["down", "Down"], ["warning", "Warning"], ["up", "Up"], ["hardware", "Hardware problems"],
  ["maintenance", "In maintenance"], ["unknown", "Can't check"], ["off", "Not monitored"]];
const tsIso = (t) => (t ? new Date(t * 1000).toISOString() : null);

function fmtDur(s) {
  if (s === null || s === undefined) return "";
  s = Math.max(0, Math.round(s));
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
  return `${Math.round(s / 86400)} days`;
}

async function loadMonitoring() {
  try {
    const [st, data, ev] = await Promise.all([api("/api/monitoring/status"), api("/api/monitoring/devices"),
      api("/api/monitoring/events?hours=24&limit=100")]);
    mon.rows = data.devices;
    mon.counts = data.counts;
    mon.labels = data.labels;
    const ids = new Set(mon.rows.map((r) => r.id));
    mon.picked = new Set([...mon.picked].filter((i) => ids.has(i)));
    monStatusLine(st);
    monSummary();
    monFilters();
    renderMonitoring();
    monEvents(ev.events);
    monPorts();
    monHardware();
    loadMeraki();
  } catch (e) {
    toast(e.message);
  }
}

function monStatusLine(st) {
  const p = st.poller || {};
  const parts = [];
  if (st.running) {
    parts.push(`Checking ${p.devices} device${p.devices === 1 ? "" : "s"} every ${st.interval} s`);
    if (p.last_round) parts.push(`last check ${fmtAgo(tsIso(p.last_round))} (took ${p.round_seconds} s)`);
    parts.push(`down after ${st.down_after} check${st.down_after === 1 ? "" : "s"} without an answer`);
  } else {
    parts.push("The monitoring poller isn't running (netops-monitor service): what is shown may be old");
  }
  if (p.licensed === false) parts.push("NOT CHECKING: Monitoring isn't in the licence");
  if (p.ping_allowed === false) parts.push("ping isn't allowed on this server, so devices are checked with SNMP only");
  if (!st.profiles) parts.push("no SNMP profile yet, so devices are only pinged: add one under SNMP profiles");
  else if (!st.default_profile) parts.push("no default SNMP profile: only devices given a profile are read with SNMP");
  if (p.last_error) parts.push(`ERROR: ${p.last_error}`);
  $("#mon-status").textContent = parts.join(" · ");
  $("#mon-status").classList.toggle("bad-text", !st.running || p.licensed === false || !!p.last_error);
}

function monSummary() {
  const c = mon.counts;
  $("#mon-summary").replaceChildren(...MON_TILES.filter(([k]) => k !== "unknown" || c.unknown).map(([key, label]) =>
    h("button", { class: `tile mon-${key}`, onclick: () => { $("#mon-filter-status").value = key; renderMonitoring(); } },
      h("span", { class: "num" }, c[key] ?? 0), h("span", { class: "lbl" }, label))));
}

function monFilters() {
  const st = $("#mon-filter-status"), site = $("#mon-filter-site");
  const keepSt = st.value, keepSite = site.value;
  st.replaceChildren(h("option", { value: "" }, "All statuses"),
    ...MON_ORDER.map((k) => h("option", { value: k }, mon.labels[k] || k)), h("option", { value: "maintenance" }, "In maintenance"),
    h("option", { value: "hardware" }, "Hardware problems"));
  const sites = [...new Set(mon.rows.map((r) => r.site).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  site.replaceChildren(h("option", { value: "" }, "All sites"), ...sites.map((x) => h("option", { value: x }, x)));
  st.value = keepSt;
  site.value = sites.includes(keepSite) ? keepSite : "";
}

function monShown() {
  const q = $("#mon-search").value.trim().toLowerCase();
  const st = $("#mon-filter-status").value, site = $("#mon-filter-site").value;
  return mon.rows.filter((r) => (!st || (st === "maintenance" ? r.maintenance : st === "hardware" ? r.hardware_problems.length : r.status === st))
    && (!site || r.site === site)
    && (!q || [r.name, r.address, r.site, r.reason, r.sys_name, ...r.hardware_problems].some((x) => (x || "").toLowerCase().includes(q))))
    .sort((a, b) => MON_ORDER.indexOf(a.status) - MON_ORDER.indexOf(b.status) || a.name.localeCompare(b.name, undefined, { numeric: true }));
}

function monBadge(r) {
  return [h("span", { class: `badge mon-${r.status}`, title: r.stale ? "From the last check before the poller stopped" : "" },
    `${r.status_label}${r.stale ? "?" : ""}`), r.maintenance && r.monitored ? h("span", { class: "badge mon-maint", title: "In a calendar window or an upgrade: not emailed" }, "maintenance") : null];
}

function renderMonitoring() {
  const rows = monShown();
  const manage = can("monitoring", "manage");
  $("#mon-all").hidden = !manage;
  $("#mon-all").checked = rows.length > 0 && rows.every((r) => mon.picked.has(r.id));
  const now = Date.now() / 1000;
  $("#mon-table tbody").replaceChildren(...rows.map((r) => h("tr", { class: `mon-row ${r.status}`, onclick: () => monOpen(r.id) },
    h("td", { class: "pick", onclick: (ev) => ev.stopPropagation() }, manage ? h("input", { type: "checkbox", "aria-label": `Select ${r.name}`,
      checked: mon.picked.has(r.id), onchange: (ev) => { ev.target.checked ? mon.picked.add(r.id) : mon.picked.delete(r.id); monBulkBar(); } }) : null),
    h("td", {}, ...monBadge(r).filter(Boolean)),
    h("td", {}, h("b", {}, r.name)),
    h("td", {}, siteLink(r.site)),
    h("td", { class: "muted" }, r.address),
    h("td", {}, r.rtt_ms !== null && r.rtt_ms !== undefined ? `${r.rtt_ms.toFixed(1)} ms` : "—",
      r.loss ? h("small", { class: "muted" }, ` ${Math.round(r.loss * 100)}% lost`) : null),
    h("td", {}, r.uptime !== null && r.uptime !== undefined ? fmtDur(r.uptime + Math.max(0, now - (r.last_poll || now))) : "—"),
    cpuMemCell(r),
    h("td", { class: r.availability_7d !== null && r.availability_7d < 99 ? "bad-text" : "" },
      r.availability_7d !== null && r.availability_7d !== undefined ? `${r.availability_7d}%` : "—"),
    h("td", { title: r.since ? fmtTime(tsIso(r.since)) : "" }, r.since ? fmtAgo(tsIso(r.since)) : "—"),
    h("td", { class: "muted note" }, r.reason || (r.profile ? "" : r.snmp ? "" : "SNMP off")))));
  $("#mon-empty").hidden = rows.length > 0;
  $("#mon-empty").textContent = mon.rows.length ? "No devices match these filters." : "No devices yet: add them on the Config backups or Inventory page.";
  monBulkBar();
}

function monEvents(events) {
  $("#mon-events tbody").replaceChildren(...events.map((e) => h("tr", { class: "link-row", onclick: () => monOpen(e.device_id) },
    h("td", { class: "when" }, fmtTime(e.time)), h("td", {}, e.device),
    h("td", {}, h("span", { class: `badge ev-${e.kind}` }, e.kind_label), e.maintenance ? h("span", { class: "badge mon-maint" }, "maintenance") : null),
    h("td", { class: "muted" }, e.detail))));
  $("#mon-events-empty").hidden = events.length > 0;
}

function monBulkBar() {
  const n = mon.picked.size;
  $("#mon-bulk").hidden = !n || !can("monitoring", "manage");
  $("#mon-bulk-count").textContent = `${n} selected`;
}

async function monSetChoices(ids, body, what) {
  try {
    await api("/api/monitoring/devices", { method: "PUT", body: { device_ids: [...ids], ...body } });
    toast(`${what} (${ids.length || ids.size} device${(ids.length || ids.size) === 1 ? "" : "s"}). The poller picks it up within a minute.`);
    await loadMonitoring();
  } catch (e) {
    toast(e.message);
  }
}

async function monLoadProfiles() {
  mon.profiles = await api("/api/monitoring/profiles");
  return mon.profiles;
}

function monProfileOptions(sel, current) {
  const def = mon.profiles.profiles.find((p) => p.is_default);
  sel.replaceChildren(h("option", { value: "" }, def ? `The default (${def.name})` : "The default (none set)"),
    ...mon.profiles.profiles.map((p) => h("option", { value: String(p.id) }, `${p.name} (v${p.version})`)));
  sel.value = current ? String(current) : "";
}

// --- one device

async function monOpen(id, hours = mon.hours) {
  mon.hours = hours;
  let d;
  try {
    [d] = await Promise.all([api(`/api/monitoring/devices/${id}?hours=${hours}`), mon.profiles ? null : monLoadProfiles()]);
  } catch (e) {
    return toast(e.message);
  }
  mon.device = d;
  $("#mon-d-title").replaceChildren(d.name, " ", ...monBadge(d).filter(Boolean));
  const state = [d.reason, d.since && d.monitored ? `${d.status_label.toLowerCase()} since ${fmtTime(tsIso(d.since))}` : "",
    d.last_poll ? `last check ${fmtAgo(tsIso(d.last_poll))}` : ""].filter(Boolean);
  $("#mon-d-state").textContent = state.join(" · ");
  $$("#mon-d-range button").forEach((b) => b.classList.toggle("active", Number(b.dataset.hours) === hours));
  const a = d.availability;
  const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`);
  $("#mon-d-avail").textContent = `Answered: today ${pct(a["1d"])} · 7 days ${pct(a["7d"])} · 30 days ${pct(a["30d"])} · year ${pct(a["365d"])}`;
  monGraph(d);
  const now = Date.now() / 1000;
  const facts = [["Name it reports", d.sys_name], ["Description", d.sys_descr], ["Address", d.address], ["Site", d.site],
    ["Up for", d.uptime !== null && d.uptime !== undefined ? fmtDur(d.uptime + Math.max(0, now - (d.last_poll || now))) : ""],
    ["Last restart", d.last_restart ? fmtTime(tsIso(d.last_restart)) : ""],
    ["SNMP profile", d.snmp ? (d.profile ? `${d.profile}${d.profile_is_default ? " (the default)" : ""}` : "none") : "SNMP off"],
    ["Ping", d.ping ? "on" : "off"]];
  $("#mon-d-info").replaceChildren(...facts.filter(([, v]) => v).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  const f = $("#mon-d-form");
  f.monitored.checked = d.monitored;
  f.ping.checked = d.ping;
  f.snmp.checked = d.snmp;
  monProfileOptions(f.profile_id, d.profile_id);
  f.profile_id.disabled = !can("inventory", "addresses");
  f.profile_id.title = f.profile_id.disabled ? "Choosing where SNMP secrets are sent needs the 'addresses' level" : "";
  f.querySelector(".error").hidden = true;
  $("#mon-d-events tbody").replaceChildren(...d.events.map((e) => h("tr", {},
    h("td", { class: "when" }, fmtTime(e.time)),
    h("td", {}, h("span", { class: `badge ev-${e.kind}` }, e.kind_label), e.maintenance ? h("span", { class: "badge mon-maint" }, "maintenance") : null),
    h("td", { class: "muted" }, e.detail))));
  if (!d.events.length) $("#mon-d-events tbody").append(h("tr", {}, h("td", { colspan: 3, class: "muted" }, "No events in the last 90 days")));
  if (!$("#mon-dialog").open) $("#mon-dialog").showModal();
  await Promise.all([monHealth(d), monInterfaces(d)]);
}

/** Response time over the period: the average line, the worst in a lighter band, and red
 * marks along the bottom where the device didn't answer. */
function monGraph(d) {
  const W = 1000, H = 200, L = 46, B = 22, T = 10;
  const x = (t) => L + ((t - d.since_ts) / (d.until_ts - d.since_ts)) * (W - L - 6);
  const pts = d.graph;
  const top = Math.max(1, ...pts.map((p) => p.rtt_max ?? p.rtt_ms ?? 0)) * 1.15;
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const kids = [];
  for (const f of [0, 0.5, 1]) {
    kids.push(svgEl("line", { x1: L, x2: W - 6, y1: y(top * f), y2: y(top * f), class: "grid" }),
      svgEl("text", { x: L - 6, y: y(top * f) + 4, "text-anchor": "end" }, `${(top * f).toFixed(top * f < 10 ? 1 : 0)} ms`));
  }
  const span = d.until_ts - d.since_ts;
  for (const f of [0, 0.25, 0.5, 0.75, 1]) {
    const t = d.since_ts + span * f;
    const label = span > 3 * 86400 ? new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" })
      : new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    kids.push(svgEl("text", { x: Math.min(W - 30, Math.max(L + 20, x(t))), y: H - 4, "text-anchor": "middle" }, label));
  }
  const step = pts.length > 1 ? (pts[pts.length - 1].ts - pts[0].ts) / (pts.length - 1) : span;
  const runs = [];
  let run = [];
  for (const p of pts) {
    if (p.rtt_ms === null || p.rtt_ms === undefined || (run.length && p.ts - run[run.length - 1].ts > step * 2.5)) {
      if (run.length) runs.push(run);
      run = [];
    }
    if (p.rtt_ms !== null && p.rtt_ms !== undefined) run.push(p);
  }
  if (run.length) runs.push(run);
  for (const r of runs) {
    if (r[0].rtt_max !== undefined) {
      const band = [...r.map((p) => `${x(p.ts)},${y(p.rtt_max ?? p.rtt_ms)}`), ...[...r].reverse().map((p) => `${x(p.ts)},${y(p.rtt_ms)}`)];
      kids.push(svgEl("polygon", { points: band.join(" "), class: "band" }));
    }
    kids.push(svgEl("polyline", { points: r.map((p) => `${x(p.ts)},${y(p.rtt_ms)}`).join(" "), class: "line" }));
  }
  const w = Math.max(2, (W - L) / Math.max(pts.length, 1));
  for (const p of pts) {
    if (p.ok !== null && p.ok < 1) {
      kids.push(svgEl("rect", { x: x(p.ts) - w / 2, y: H - B - 6, width: w, height: 6, class: p.ok === 0 ? "miss all" : "miss",
        "fill-opacity": Math.max(0.35, 1 - p.ok) }, svgEl("title", {}, `${Math.round((1 - p.ok) * 100)}% of checks unanswered`)));
    }
  }
  if (!pts.length) kids.push(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "none" }, "No checks in this period"));
  $("#mon-d-graph").replaceChildren(svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Response time" }, kids));
}

$("#mon-d-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, d = mon.device;
  const body = { device_ids: [d.id], monitored: f.monitored.checked, ping: f.ping.checked, snmp: f.snmp.checked };
  const profile = f.profile_id.value ? Number(f.profile_id.value) : null;
  if (can("inventory", "addresses") && profile !== (d.profile_id || null)) Object.assign(body, { set_profile: true, profile_id: profile });
  try {
    await api("/api/monitoring/devices", { method: "PUT", body });
    toast("Saved. The poller picks it up within a minute.");
    await Promise.all([monOpen(d.id), loadMonitoring()]);
  } catch (e) {
    f.querySelector(".error").textContent = e.message;
    f.querySelector(".error").hidden = false;
  }
});
$$("#mon-d-range button").forEach((b) => b.addEventListener("click", () => monOpen(mon.device.id, Number(b.dataset.hours))));
$("#mon-d-close").addEventListener("click", () => $("#mon-dialog").close());

// --- SNMP profiles

async function monProfiles() {
  try {
    await monLoadProfiles();
  } catch (e) {
    return toast(e.message);
  }
  const p = mon.profiles, edit = can("inventory", "credentials");
  const f = $("#mon-p-form");
  if (!f.version.options.length) {
    f.version.replaceChildren(...Object.entries(p.versions).map(([k, v]) => h("option", { value: k }, v)));
    f.level.replaceChildren(...Object.entries(p.levels).map(([k, v]) => h("option", { value: k }, v)));
    f.auth_protocol.replaceChildren(...p.auth.map((k) => h("option", { value: k }, k)));
    f.priv_protocol.replaceChildren(...p.priv.map((k) => h("option", { value: k }, k + (k.endsWith("-C") ? " (Cisco)" : ""))));
  }
  $("#mon-p-table tbody").replaceChildren(...p.profiles.map((x) => h("tr", {},
    h("td", {}, h("b", {}, x.name), x.is_default ? h("span", { class: "badge mon-up" }, "default") : null),
    h("td", {}, x.version === "3" ? "v3" : "v2c"),
    h("td", { class: "muted" }, x.version === "3" ? `${x.username} · ${p.levels[x.level]}${x.level !== "noAuthNoPriv" ? ` · ${x.auth_protocol}` : ""}${x.level === "authPriv" ? `/${x.priv_protocol}` : ""}` : "community"),
    h("td", {}, x.devices),
    h("td", { class: "actions" }, edit ? h("button", { class: "small", onclick: () => monProfileForm(x) }, "Edit") : null,
      edit ? h("button", { class: "small danger", onclick: () => monProfileDelete(x) }, "Delete") : null))));
  if (!p.profiles.length) $("#mon-p-table tbody").append(h("tr", {}, h("td", { colspan: 5, class: "muted" }, "No SNMP profiles yet. Add one with the user or community your devices are set up with (see Help: set up devices).")));
  $("#mon-p-test-device").replaceChildren(...mon.rows.map((r) => h("option", { value: String(r.id) }, r.name)));
  f.hidden = true;
  if (!$("#mon-p-dialog").open) $("#mon-p-dialog").showModal();
}

function monProfileForm(x = null) {
  const f = $("#mon-p-form");
  mon.editing = x;
  f.reset();
  $("#mon-p-form-title").textContent = x ? `Change ${x.name}` : "Add profile";
  const v = x || { version: "3", level: "authPriv", auth_protocol: "SHA", priv_protocol: "AES", port: 161, timeout: 2, retries: 1,
    is_default: !mon.profiles.profiles.some((p) => p.is_default), username: "netops-mon" };
  for (const k of ["name", "version", "username", "level", "auth_protocol", "priv_protocol", "port", "timeout", "retries"]) if (v[k] !== undefined) f[k].value = v[k];
  f.is_default.checked = !!v.is_default;
  $("#mon-p-keep").hidden = !x;
  $("#mon-p-test-result").hidden = true;
  f.querySelector(".error").hidden = true;
  monProfileFields();
  f.hidden = false;
  f.name.focus();
}

function monProfileFields() {
  const f = $("#mon-p-form"), v3 = f.version.value === "3", lvl = f.level.value;
  $$("#mon-p-form [data-v]").forEach((el) => {
    el.hidden = el.dataset.v !== (v3 ? "3" : "2c") || (el.dataset.l === "auth" && lvl === "noAuthNoPriv") || (el.dataset.l === "priv" && lvl !== "authPriv");
  });
}

async function monProfileDelete(x) {
  if (!confirm(`Delete the SNMP profile ${x.name}?${x.devices ? ` ${x.devices} device(s) use it: those given it go back to the default.` : ""}`)) return;
  try {
    await api(`/api/monitoring/profiles/${x.id}`, { method: "DELETE" });
    await monProfiles();
  } catch (e) {
    toast(e.message);
  }
}

$("#mon-p-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, x = mon.editing;
  const secret = (k) => (f[k].value ? f[k].value : x ? null : "");
  const body = { name: f.name.value, version: f.version.value, username: f.username.value, level: f.level.value,
    auth_protocol: f.auth_protocol.value, priv_protocol: f.priv_protocol.value, port: Number(f.port.value),
    timeout: Number(f.timeout.value), retries: Number(f.retries.value), is_default: f.is_default.checked,
    community: secret("community"), auth_key: secret("auth_key"), priv_key: secret("priv_key") };
  try {
    const saved = await api(x ? `/api/monitoring/profiles/${x.id}` : "/api/monitoring/profiles", { method: x ? "PUT" : "POST", body });
    toast(`Saved ${saved.name}`);
    await monProfiles();
    monProfileForm({ ...saved });
  } catch (e) {
    f.querySelector(".error").textContent = e.message;
    f.querySelector(".error").hidden = false;
  }
});
$("#mon-p-test").addEventListener("click", async () => {
  const out = $("#mon-p-test-result");
  if (!mon.editing) return toast("Save the profile first, then test it");
  out.hidden = false;
  out.className = "muted";
  out.textContent = "Asking the device…";
  try {
    const r = await api(`/api/monitoring/profiles/${mon.editing.id}/test`, { method: "POST", body: { device_id: Number($("#mon-p-test-device").value) } });
    out.className = r.ok ? "ok-text" : "bad-text";
    out.textContent = r.ok ? `${r.message}: ${r.sys_name || "(no name)"} · up ${fmtDur(r.uptime)} · ${r.sys_descr}` : r.message;
  } catch (e) {
    out.className = "bad-text";
    out.textContent = e.message;
  }
});
$("#mon-p-form").version.addEventListener("change", monProfileFields);
$("#mon-p-form").level.addEventListener("change", monProfileFields);
$("#mon-p-add").addEventListener("click", () => monProfileForm());
$("#mon-p-cancel").addEventListener("click", () => { $("#mon-p-form").hidden = true; });
$("#mon-p-close").addEventListener("click", () => $("#mon-p-dialog").close());
$("#mon-profiles").addEventListener("click", monProfiles);

// --- device setup help

async function monHelp() {
  if (!mon.howto) mon.howto = await api("/api/monitoring/howto").catch((e) => toast(e.message));
  if (!mon.howto) return;
  const sel = $("#mon-help-platform");
  if (!sel.options.length) {
    sel.replaceChildren(...mon.howto.platforms.map((p, i) => h("option", { value: i }, p.title)));
    $("#mon-help-server").value = mon.howto.server;
  }
  monHelpShow();
  $("#mon-help-dialog").showModal();
}

function monHelpShow() {
  const hw = mon.howto;
  const p = hw.platforms[Number($("#mon-help-platform").value) || 0];
  const server = $("#mon-help-server").value.trim() || "<server address>";
  const v2c = $("#mon-help-mode").value === "v2c";
  $("#mon-help-general").replaceChildren(...hw.general.map((g) => h("li", {}, g)));
  $("#mon-help-text").textContent = v2c ? (p.v2c ? p.v2c.replaceAll("{server}", server) : `${p.title}: use SNMPv3 (see the vendor's documentation for v2c).`)
    : p.text.replaceAll("{server}", server);
  $("#mon-help-notes").textContent = [p.kind === "gui" ? "In the device's web page or API." : "", v2c ? "Add these lines in configuration mode. The community is sent in clear text: keep it to the management network." : "", p.notes || ""].filter(Boolean).join(" ");
}

$("#mon-help").addEventListener("click", monHelp);
$("#mon-help-close").addEventListener("click", () => $("#mon-help-dialog").close());
$("#mon-help-platform").addEventListener("change", monHelpShow);
$("#mon-help-server").addEventListener("input", monHelpShow);
$("#mon-help-mode").addEventListener("change", monHelpShow);
$("#mon-help-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#mon-help-text").textContent);
    toast("Copied");
  } catch {
    toast("Select the text and copy it (the browser blocked copying)");
  }
});

// --- the page's controls

$("#mon-search").addEventListener("input", renderMonitoring);
$("#mon-filter-status").addEventListener("change", renderMonitoring);
$("#mon-filter-site").addEventListener("change", renderMonitoring);
$("#mon-map").addEventListener("click", () => openTopology(0));
$("#mon-all").addEventListener("change", (ev) => {
  monShown().forEach((r) => (ev.target.checked ? mon.picked.add(r.id) : mon.picked.delete(r.id)));
  renderMonitoring();
});
$$("#mon-bulk [data-bulk]").forEach((b) => b.addEventListener("click", () => {
  const [key, value] = b.dataset.bulk.split(":");
  monSetChoices(mon.picked, { [key]: value === "true" }, b.textContent);
}));
$("#mon-bulk-clear").addEventListener("click", () => { mon.picked.clear(); renderMonitoring(); });
$("#mon-bulk-profile-set").addEventListener("click", () => {
  const v = $("#mon-bulk-profile").value;
  monSetChoices(mon.picked, { set_profile: true, profile_id: v ? Number(v) : null }, "SNMP profile chosen");
});
$("#mon-bulk").addEventListener("pointerenter", async () => {
  if (!mon.profiles) await monLoadProfiles().catch(() => null);
  if (mon.profiles && !$("#mon-bulk-profile").options.length) monProfileOptions($("#mon-bulk-profile"), null);
});

// --- Meraki (Dashboard API)

const MK_PRODUCTS = { appliance: "MX security appliance", switch: "MS switch", wireless: "MR access point",
  camera: "MV camera", cellularGateway: "MG cellular", sensor: "MT sensor" };
const MK_STATUS = { online: "mon-up", alerting: "mon-warning", offline: "mon-down", dormant: "mon-off" };

async function loadMeraki() {
  const r = await api("/api/monitoring/meraki").catch(() => null);
  mon.meraki = r;
  $("#mk-box").hidden = !r || !r.connections.length;
  if (!r || !r.connections.length) return;
  const c = r.counts;
  const errors = r.connections.filter((x) => x.error);
  const last = Math.max(0, ...r.connections.map((x) => x.read_at || 0));
  $("#mk-note").textContent = [`${c.online} online`, c.alerting ? `${c.alerting} alerting` : "", c.offline ? `${c.offline} offline` : "",
    c.dormant ? `${c.dormant} dormant` : "", last ? `read ${fmtAgo(tsIso(last))}, every ${Math.round(r.interval / 60)} min` : "not read yet",
    ...errors.map((x) => `${x.name}: ${x.error}`)].filter(Boolean).join(" · ");
  $("#mk-note").classList.toggle("bad-text", errors.length > 0 || c.offline > 0);
  $("#mk-table tbody").replaceChildren(...r.devices.map((d) => h("tr", {},
    h("td", {}, h("span", { class: `badge ${MK_STATUS[d.status] || "mon-unknown"}` }, d.status_label)),
    h("td", {}, h("b", {}, d.name), r.connections.length > 1 ? h("small", { class: "muted" }, ` ${d.org}`) : null),
    h("td", {}, siteLink(d.network)), h("td", {}, d.model), h("td", { class: "muted" }, d.lan_ip || "—"),
    h("td", { class: "muted" }, d.public_ip || "—"), h("td", {}, d.firmware || "—"),
    h("td", {}, d.uplinks.map((u) => h("span", { class: `badge ${u.status === "active" ? "mon-up" : u.status === "ready" ? "mon-off" : "mon-down"}`, title: u.status }, `${u.interface} ${u.status}`))),
    h("td", { class: "muted", title: d.last_reported || "" }, d.since ? fmtAgo(tsIso(d.since)) : "—"))));
  const upg = r.upgrades.filter((u) => u.next_time);
  $("#mk-upgrades-box").hidden = !upg.length;
  $("#mk-upgrades tbody").replaceChildren(...upg.map((u) => h("tr", {},
    h("td", {}, fmtTime(u.next_time)), h("td", {}, siteLink(u.network)), h("td", {}, MK_PRODUCTS[u.product] || u.product),
    h("td", {}, u.current), h("td", {}, h("b", {}, u.next_version)))));
}

async function mkConnections() {
  const r = await api("/api/monitoring/meraki").catch((e) => toast(e.message));
  if (!r) return;
  mon.meraki = r;
  const f = $("#mk-form");
  if (!f.base_url.options.length) f.base_url.replaceChildren(...Object.entries(r.bases).map(([k, v]) => h("option", { value: k }, v)));
  $("#mk-conn-table tbody").replaceChildren(...r.connections.map((c) => h("tr", {},
    h("td", {}, h("b", {}, c.name), c.enabled ? null : h("span", { class: "badge mon-off" }, "off")),
    h("td", {}, `${c.org_name || ""} (${c.org_id})`), h("td", { class: "muted" }, c.base_label),
    h("td", { class: c.error ? "bad-text" : "muted" }, c.error || (c.read_at ? `${fmtAgo(tsIso(c.read_at))}: ${c.devices} devices in ${c.networks} networks` : "not yet")),
    h("td", { class: "actions" }, h("button", { class: "small", onclick: () => mkForm(c) }, "Edit"),
      h("button", { class: "small danger", onclick: () => mkDelete(c) }, "Delete")))));
  if (!r.connections.length) $("#mk-conn-table tbody").append(h("tr", {}, h("td", { colspan: 5, class: "muted" }, "No Meraki connections yet.")));
  f.hidden = true;
  if (!$("#mk-dialog").open) $("#mk-dialog").showModal();
}

function mkForm(c = null) {
  const f = $("#mk-form");
  mon.mkEditing = c;
  f.reset();
  $("#mk-form-title").textContent = c ? `Change ${c.name}` : "Add connection";
  f.name.value = c ? c.name : "";
  f.base_url.value = c ? c.base_url : Object.keys(mon.meraki.bases)[0];
  f.org_id.value = c ? c.org_id : "";
  f.enabled.checked = c ? c.enabled : true;
  f.org_pick.replaceChildren(h("option", { value: "" }, c ? `${c.org_name || c.org_id}` : "Find them with the API key →"));
  $("#mk-keep").hidden = !c;
  $("#mk-find-result").hidden = true;
  f.querySelector(".error").hidden = true;
  f.hidden = false;
  f.name.focus();
}

async function mkDelete(c) {
  if (!confirm(`Delete the Meraki connection ${c.name}? Its devices leave the Monitoring page (inventory rows stay).`)) return;
  try {
    await api(`/api/monitoring/meraki/connections/${c.id}`, { method: "DELETE" });
    await Promise.all([mkConnections(), loadMeraki()]);
  } catch (e) {
    toast(e.message);
  }
}

$("#mk-find").addEventListener("click", async () => {
  const f = $("#mk-form"), out = $("#mk-find-result");
  out.hidden = false;
  out.className = "muted";
  out.textContent = "Asking the Dashboard API…";
  try {
    const r = await api("/api/monitoring/meraki/organizations", { method: "POST", body: {
      base_url: f.base_url.value, api_key: f.api_key.value || null, connection_id: mon.mkEditing ? mon.mkEditing.id : null } });
    out.className = r.ok ? "ok-text" : "bad-text";
    out.textContent = r.message;
    if (r.ok) {
      f.org_pick.replaceChildren(...r.organizations.map((o) => h("option", { value: o.id, "data-name": o.name }, `${o.name} (${o.id})`)));
      if (r.organizations.length) { f.org_id.value = r.organizations[0].id; if (!f.name.value) f.name.value = r.organizations[0].name; }
    }
  } catch (e) {
    out.className = "bad-text";
    out.textContent = e.message;
  }
});
$("#mk-form").org_pick.addEventListener("change", (ev) => { if (ev.target.value) $("#mk-form").org_id.value = ev.target.value; });
$("#mk-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, c = mon.mkEditing;
  const picked = f.org_pick.selectedOptions[0];
  const body = { name: f.name.value, base_url: f.base_url.value, api_key: f.api_key.value || (c ? null : ""),
    org_id: f.org_id.value, org_name: picked && picked.value === f.org_id.value ? picked.dataset.name || "" : (c && c.org_id === f.org_id.value ? c.org_name : ""),
    enabled: f.enabled.checked };
  try {
    await api(c ? `/api/monitoring/meraki/connections/${c.id}` : "/api/monitoring/meraki/connections", { method: c ? "PUT" : "POST", body });
    toast("Saved. It is read within a few minutes.");
    await mkConnections();
  } catch (e) {
    f.querySelector(".error").textContent = e.message;
    f.querySelector(".error").hidden = false;
  }
});
$("#mk-add").addEventListener("click", () => mkForm());
$("#mk-cancel").addEventListener("click", () => { $("#mk-form").hidden = true; });
$("#mk-close").addEventListener("click", () => { $("#mk-dialog").close(); loadMeraki(); });
$("#mk-connections").addEventListener("click", mkConnections);
$("#mk-inventory").addEventListener("click", async () => {
  try {
    const r = await api("/api/monitoring/meraki/inventory", { method: "POST" });
    toast(`Inventory: ${r.added} added, ${r.updated} brought up to date (of ${r.total} Meraki devices)`);
  } catch (e) {
    toast(e.message);
  }
});

// --- custom SNMP sensors

const sn = { data: null, editing: null };
const SN_NUM = ["warn_above", "crit_above", "warn_below", "crit_below"];

function snFineWhen(x) {
  if (x.mode === "state") return `code ${x.ok_values}${x.warn_values ? ` (warning: ${x.warn_values})` : ""}`;
  const u = x.unit ? ` ${x.unit}` : "";
  const parts = [x.warn_above !== null ? `warn > ${x.warn_above}${u}` : "", x.crit_above !== null ? `critical > ${x.crit_above}${u}` : "",
    x.warn_below !== null ? `warn < ${x.warn_below}${u}` : "", x.crit_below !== null ? `critical < ${x.crit_below}${u}` : ""].filter(Boolean);
  return parts.join(", ") || "no thresholds (graph only)";
}

function snFor(x) {
  if (x.device_ids.length) return x.device_ids.map((id) => (mon.rows.find((r) => r.id === id) || {}).name || `#${id}`).join(", ");
  return [x.platform ? sn.data.platforms[x.platform] || x.platform : "", x.site].filter(Boolean).join(" · ") || "every SNMP device";
}

async function snOpen() {
  try {
    sn.data = await api("/api/monitoring/sensors");
  } catch (e) {
    return toast(e.message);
  }
  const d = sn.data, f = $("#sn-form");
  if (!f.mode.options.length) {
    f.mode.replaceChildren(...Object.entries(d.modes).map(([k, v]) => h("option", { value: k }, v)));
    f.platform.replaceChildren(h("option", { value: "" }, "any platform"),
      ...Object.entries(d.platforms).map(([k, v]) => h("option", { value: k }, v)));
    const groups = [...new Set(d.examples.map((x) => x.group))];
    $("#sn-example").replaceChildren(h("option", { value: "" }, "Start from an example…"),
      ...groups.map((g) => h("optgroup", { label: g }, ...d.examples.map((x, i) => [x, i]).filter(([x]) => x.group === g)
        .map(([x, i]) => h("option", { value: String(i) }, x.name)))));
  }
  f.device_ids.replaceChildren(...mon.rows.filter((r) => r.snmp).map((r) => h("option", { value: String(r.id) }, `${r.name}${r.site ? ` (${r.site})` : ""}`)));
  $("#sn-test-device").replaceChildren(...mon.rows.filter((r) => r.snmp).map((r) => h("option", { value: String(r.id) }, r.name)));
  $("#sn-sites").replaceChildren(...[...new Set(mon.rows.map((r) => r.site).filter(Boolean))].map((s) => h("option", { value: s })));
  const manage = can("monitoring", "manage");
  $("#sn-table tbody").replaceChildren(...d.sensors.map((x) => h("tr", {},
    h("td", {}, h("b", {}, x.name), x.enabled ? null : h("span", { class: "badge mon-off" }, "off"),
      x.notes ? h("div", { class: "muted small" }, x.notes) : null),
    h("td", {}, h("code", {}, x.oid), x.table ? h("small", { class: "muted" }, " table") : null),
    h("td", {}, x.mode === "rate" ? "rate /s" : x.mode, x.scale !== 1 && x.mode !== "state" ? h("small", { class: "muted" }, ` ×${x.scale}`) : null),
    h("td", {}, snFineWhen(x)), h("td", {}, snFor(x)), h("td", {}, String(x.devices)),
    h("td", { class: "actions" }, manage ? [h("button", { class: "small", onclick: () => snForm(x) }, "Edit"),
      h("button", { class: "small danger", onclick: () => snDelete(x) }, "Delete")] : null))));
  if (!d.sensors.length) $("#sn-table tbody").append(h("tr", {}, h("td", { colspan: 7, class: "muted" }, "No sensors yet. Open “How to set up a sensor”, or start from an example.")));
  $("#sn-help").open = !d.sensors.length;
  f.hidden = true;
  if (!$("#sn-dialog").open) $("#sn-dialog").showModal();
}

function snShowFields() {
  const f = $("#sn-form"), state = f.mode.value === "state";
  f.querySelectorAll("[data-sn=num]").forEach((el) => { el.hidden = state; });
  f.querySelectorAll("[data-sn=state]").forEach((el) => { el.hidden = !state; });
  f.querySelectorAll("[data-sn=table]").forEach((el) => { el.hidden = !f.table.checked; });
}

function snForm(x = null, copy = false) {
  const f = $("#sn-form");
  sn.editing = x && !copy ? x : null;
  f.reset();
  $("#sn-form-title").textContent = sn.editing ? `Change ${x.name}` : "Add sensor";
  const v = x || {};
  for (const k of ["name", "oid", "unit", "label_oid", "ok_values", "warn_values", "site", "notes"]) f[k].value = v[k] ?? "";
  f.mode.value = v.mode || "value";
  f.scale.value = v.scale ?? 1;
  for (const k of SN_NUM) f[k].value = v[k] ?? "";
  f.table.checked = !!v.table;
  f.enabled.checked = v.enabled ?? true;
  f.platform.value = v.platform || "";
  const ids = new Set((v.device_ids || []).map(String));
  [...f.device_ids.options].forEach((o) => { o.selected = ids.has(o.value); });
  $("#sn-test-result").hidden = true;
  f.querySelector(".error").hidden = true;
  snShowFields();
  f.hidden = false;
  f.name.focus();
}

function snBody() {
  const f = $("#sn-form"), num = (el) => (el.value.trim() === "" ? null : Number(el.value));
  return { name: f.name.value, oid: f.oid.value, mode: f.mode.value, table: f.table.checked, label_oid: f.label_oid.value,
    unit: f.unit.value, scale: num(f.scale) ?? 1, ...Object.fromEntries(SN_NUM.map((k) => [k, f.mode.value === "state" ? null : num(f[k])])),
    ok_values: f.ok_values.value, warn_values: f.warn_values.value, platform: f.platform.value, site: f.site.value,
    device_ids: [...f.device_ids.selectedOptions].map((o) => Number(o.value)), notes: f.notes.value, enabled: f.enabled.checked };
}

async function snDelete(x) {
  if (!confirm(`Delete the sensor ${x.name}? Its readings stop; the graphs already kept stay until they age out.`)) return;
  try {
    await api(`/api/monitoring/sensors/${x.id}`, { method: "DELETE" });
    snOpen();
  } catch (e) {
    toast(e.message);
  }
}

$("#sn-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    await api(sn.editing ? `/api/monitoring/sensors/${sn.editing.id}` : "/api/monitoring/sensors",
      { method: sn.editing ? "PUT" : "POST", body: snBody() });
    toast("Saved. It is read with the next health read (within a few minutes).");
    snOpen();
  } catch (e) {
    f.querySelector(".error").textContent = e.message;
    f.querySelector(".error").hidden = false;
  }
});
$("#sn-test").addEventListener("click", async () => {
  const out = $("#sn-test-result");
  out.hidden = false;
  out.replaceChildren(h("p", { class: "muted" }, "Reading it now…"));
  try {
    const r = await api("/api/monitoring/sensors/test", { method: "POST", body: { ...snBody(), name: $("#sn-form").name.value || "Test", test_device_id: Number($("#sn-test-device").value) } });
    out.replaceChildren(h("p", { class: r.ok ? "ok-text" : "bad-text" }, r.message),
      r.readings.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Reading"), h("th", {}, "Value"), h("th", {}, "Status"), h("th", {}, "Note"))),
        h("tbody", {}, ...r.readings.slice(0, 20).map((x) => {
          const [cls, lab] = HW_STATUS[x.status] || HW_STATUS.unknown;
          return h("tr", {}, h("td", {}, x.name), h("td", {}, x.value === null ? "—" : `${x.value}${x.unit ? ` ${x.unit}` : ""}`),
            h("td", {}, h("span", { class: `badge ${cls}` }, x.status === "critical" ? "critical" : lab)), h("td", { class: "muted" }, x.source));
        })))) : null);
  } catch (e) {
    out.replaceChildren(h("p", { class: "bad-text" }, e.message));
  }
});
$("#sn-form").mode.addEventListener("change", snShowFields);
$("#sn-form").table.addEventListener("change", snShowFields);
$("#sn-add").addEventListener("click", () => snForm());
$("#sn-example").addEventListener("change", (ev) => {
  const x = sn.data.examples[Number(ev.target.value)];
  ev.target.value = "";
  if (!x) return;
  snForm({ scale: 1, warn_above: null, crit_above: null, warn_below: null, crit_below: null, ok_values: "", warn_values: "",
    unit: "", device_ids: [], table: false, platform: "", ...x, notes: x.help }, true);
});
$("#sn-cancel").addEventListener("click", () => { $("#sn-form").hidden = true; });
$("#sn-close").addEventListener("click", () => $("#sn-dialog").close());
$("#mon-sensors").addEventListener("click", snOpen);

/** One custom sensor's graph in the device window (min to max of what was read). */
function monSensorGraph(r, name) {
  const box = $("#mon-d-sensor-graph");
  const pts = (r.graph[`s:${name}`] || []).filter((p) => p.value !== null);
  box.hidden = false;
  if (!pts.length) return box.replaceChildren(h("p", { class: "muted" }, `${name}: no readings to graph yet.`));
  const W = 520, H = 150, L = 50, B = 22;
  let lo = Math.min(...pts.map((p) => p.value)), hi = Math.max(...pts.map((p) => p.max ?? p.value));
  if (lo === hi) { lo -= 1; hi += 1; }
  if (lo > 0 && lo < hi * 0.5) lo = 0;
  const pad = (hi - lo) * 0.1;
  lo -= lo === 0 ? 0 : pad; hi += pad;
  const { x, kids } = monAxis(r, W, H, L, B, 1, () => "");
  const y = (v) => 10 + (1 - (v - lo) / (hi - lo)) * (H - 10 - B);
  const label = kids.filter((k) => k.tagName !== "text" || k.getAttribute("text-anchor") !== "end");
  const fmt = (v) => (Math.abs(v) >= 100 ? Math.round(v) : Number(v.toFixed(2)));
  for (const v of [lo, (lo + hi) / 2, hi]) label.push(svgEl("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, String(fmt(v))));
  label.push(...monLine(pts, "value", x, y, "line in"));
  const unit = (r.readings.find((q) => q.name === name) || {}).unit || "";
  label.push(svgEl("text", { x: W - 10, y: 22, "text-anchor": "end", class: "key" }, `${name}${unit ? `, ${unit}` : ""}`));
  box.replaceChildren(svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${name} graph` }, label));
}

// --- hardware health

const HW_STATUS = { ok: ["mon-up", "OK"], warning: ["mon-warning", "warning"], critical: ["mon-down", "failed"],
  absent: ["mon-off", "not present"], unknown: ["mon-unknown", "unknown"] };

function cpuMemCell(r) {
  if (r.cpu === null && r.memory === null) return h("td", { class: "muted" }, "—");
  const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v)}%`);
  return h("td", {}, h("span", { class: r.hardware_problems.length ? "bad-text" : "" }, `${pct(r.cpu)} · ${pct(r.memory)}`),
    r.hardware_problems.length ? h("span", { class: "badge mon-down", title: r.hardware_problems.join("\n") },
      ` ${r.hardware_problems.length} hardware`) : null);
}

function gauge(label, value, warn) {
  if (value === null || value === undefined) return null;
  const u = value / 100;
  return h("div", { class: "gauge" }, h("span", { class: "g-label" }, label),
    h("span", { class: `load ${value >= warn ? "hi" : value >= warn * 0.8 ? "mid" : ""}` },
      h("span", { class: "bar wide" }, h("span", { class: "fill", "data-w": Math.round(u * 100) })), ` ${Math.round(value)}%`),
    h("span", { class: "muted" }, ` warn at ${warn}%`));
}

async function monHealth(d) {
  const box = $("#mon-d-health-box");
  box.hidden = !d.snmp;
  if (!d.snmp) return;
  let r;
  try {
    r = await api(`/api/monitoring/devices/${d.id}/health?hours=${mon.hours}`);
  } catch (e) {
    return toast(e.message);
  }
  const first = (kind) => r.readings.find((x) => x.kind === kind && x.value !== null);
  const cpus = r.readings.filter((x) => x.kind === "cpu" && x.value !== null);
  $("#mon-d-gauges").replaceChildren(...[
    cpus.length ? gauge("CPU", Math.max(...cpus.map((x) => x.value)), r.cpu_warn) : null,
    first("memory") ? gauge("Memory", first("memory").value, r.mem_warn) : null].filter(Boolean));
  sizeBars($("#mon-d-gauges"));
  const parts = r.readings.filter((x) => x.kind !== "cpu" && x.kind !== "memory");
  $("#mon-d-sensor-graph").hidden = true;
  $("#mon-d-health tbody").replaceChildren(...parts.map((x) => {
    const [cls, label] = HW_STATUS[x.status] || HW_STATUS.unknown;
    const reading = x.value === null || x.value === undefined ? (x.kind === "sensor" ? h("small", { class: "muted" }, x.source) : "")
      : x.kind === "temperature" ? `${x.value} °C` : x.kind === "fan" ? `${Math.round(x.value)} rpm`
      : ["sensor", "optic", "poe"].includes(x.kind) ? `${x.value}${x.unit ? ` ${x.unit}` : ""}` : x.value;
    const role = ["stack", "ha"].includes(x.kind) ? x.unit : "";
    const sensor = x.kind === "sensor";
    const row = h("tr", sensor ? { class: "sensor-row", title: "Click for its graph" } : {}, h("td", {}, x.kind_label), h("td", {}, x.name),
      h("td", {}, role || reading, x.note ? h("small", { class: "muted" }, ` ${x.note}`) : null),
      h("td", {}, h("span", { class: `badge ${cls}` }, (sensor || ["optic", "poe", "ha", "stack"].includes(x.kind)) && x.status === "critical" ? "critical" : label)));
    if (sensor) row.addEventListener("click", () => {
      $("#mon-d-health").querySelectorAll("tr.picked").forEach((el) => el.classList.remove("picked"));
      row.classList.add("picked");
      monSensorGraph(r, x.name);
    });
    return row;
  }));
  $("#mon-d-health-empty").hidden = parts.length > 0;
  $("#mon-d-health-empty").textContent = r.read_at ? "The device gives no temperatures, fans, power supplies, stack, HA, optics or PoE over SNMP." : "Not read yet (every few minutes, with SNMP).";
  const mibs = [...new Set(r.readings.map((x) => x.source).filter(Boolean))];
  const src = mibs.length ? `from ${mibs.join(", ")}` : "";
  $("#mon-d-health-note").textContent = r.error ? `Can't read it: ${r.error}` : [
    r.problems.length ? `${r.problems.length} problem${r.problems.length > 1 ? "s" : ""}: ${r.problems.join("; ")}` : r.read_at ? "No problems" : "",
    r.read_at ? `${fmtAgo(tsIso(r.read_at))}, every ${Math.round(r.interval / 60)} min` : "", src].filter(Boolean).join(" · ");
  $("#mon-d-health-note").classList.toggle("bad-text", !!r.problems.length || !!r.error);
  monHealthGraph(r);
}

function monHealthGraph(r) {
  const W = 520, H = 170, L = 40, B = 22;
  const series = [["cpu", "line in", "CPU"], ["memory", "line out", "memory"]].filter(([k]) => (r.graph[k] || []).length);
  $("#mon-d-health-graph").hidden = !series.length;
  if (!series.length) return;
  const { x, y, kids } = monAxis(r, W, H, L, B, 100, (v) => `${Math.round(v)}%`);
  kids.push(svgEl("line", { x1: L, x2: W - 6, y1: y(r.cpu_warn), y2: y(r.cpu_warn), class: "limit" }));
  for (const [key, cls] of series) kids.push(...monLine(r.graph[key], "value", x, y, cls));
  kids.push(svgEl("text", { x: W - 10, y: 22, "text-anchor": "end", class: "key" }, `${series.map((s) => s[2]).join(" (blue) and ")}${series.length > 1 ? " (green)" : ""}, %`));
  $("#mon-d-health-graph").replaceChildren(svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "CPU and memory" }, kids));
}

async function monHardware() {
  const r = await api("/api/monitoring/hardware").catch(() => null);
  $("#mon-hw").hidden = !r || !r.devices.length;
  if (!r) return;
  $("#mon-hw-table tbody").replaceChildren(...r.devices.map((d) => h("tr", { class: "link-row", onclick: () => monOpen(d.device_id) },
    h("td", {}, h("b", {}, d.device)), h("td", {}, siteLink(d.site)),
    h("td", { class: d.status === "critical" ? "bad-text" : "" }, d.problems.join("; ")),
    h("td", { class: "muted" }, fmtAgo(tsIso(d.read_at))))));
}

// --- interfaces

function fmtBps(v) {
  if (v === null || v === undefined) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(v >= 1e10 ? 0 : 2)} Gb/s`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)} Mb/s`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)} kb/s`;
  return `${Math.round(v)} b/s`;
}

function fmtSpeed(v) {
  if (!v) return "—";
  return v >= 1e9 ? `${v / 1e9} G` : `${v / 1e6} M`;
}

function loadBar(u) {
  if (u === null || u === undefined) return h("span", { class: "muted" }, "—");
  const pct = Math.round(u * 100);
  return h("span", { class: `load ${u >= 0.8 ? "hi" : u >= 0.5 ? "mid" : ""}`, title: `${(u * 100).toFixed(1)}% of the port's speed (the busier direction)` },
    h("span", { class: "bar" }, h("span", { class: "fill", "data-w": pct })), ` ${pct}%`);
}

/** Bar widths are set from data-w after rendering (the page's CSP forbids style attributes). */
function sizeBars(root) {
  root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
}

const errCell = (v) => h("td", { class: v ? "bad-text" : "muted" }, v ? (v < 10 ? v.toFixed(1) : Math.round(v)) : "0");

async function monInterfaces(d) {
  const box = $("#mon-d-ifaces-box");
  box.hidden = !d.snmp;
  if (!d.snmp) return;
  let r;
  try {
    r = await api(`/api/monitoring/devices/${d.id}/interfaces`);
  } catch (e) {
    return toast(e.message);
  }
  mon.ifaces = { device: d, ...r };
  monRenderInterfaces();
}

function monRenderInterfaces() {
  const r = mon.ifaces, all = $("#mon-d-ifaces-all").checked, sort = $("#mon-d-ifaces-sort").value;
  let rows = r.interfaces.filter((i) => all || i.admin_up);
  const by = { load: (a, b) => (b.util ?? -1) - (a.util ?? -1),
    errors: (a, b) => ((b.errors || 0) * 10 + (b.discards || 0)) - ((a.errors || 0) * 10 + (a.discards || 0)),
    down: (a, b) => (a.oper === 1) - (b.oper === 1) || b.watched - a.watched,
    index: (a, b) => a.if_index - b.if_index }[sort];
  rows = [...rows].sort(by);
  const up = r.interfaces.filter((i) => i.admin_up && i.oper === 1).length, admin = r.interfaces.filter((i) => i.admin_up).length;
  $("#mon-d-ifaces-note").textContent = r.error ? `Can't read the interfaces: ${r.error}`
    : r.read_at ? `${up} of ${admin} up · read ${fmtAgo(tsIso(r.read_at))}, every ${Math.round(r.interval / 60)} min` : "Not read yet";
  $("#mon-d-ifaces-note").classList.toggle("bad-text", !!r.error);
  $("#mon-d-ifaces tbody").replaceChildren(...rows.map((i) => h("tr", { class: i.graphed ? "link-row" : "", onclick: () => i.graphed && monOpenIface(r.device.id, i.if_index) },
    h("td", {}, h("b", {}, i.name || i.descr)),
    h("td", { class: "muted" }, i.alias || (i.name && i.descr !== i.name ? i.descr : "")),
    h("td", {}, h("span", { class: `badge ${!i.admin_up ? "mon-off" : i.oper === 1 ? "mon-up" : i.watched ? "mon-down" : "mon-unknown"}` },
      !i.admin_up ? "switched off" : i.oper_label)),
    h("td", {}, fmtSpeed(i.speed)),
    h("td", {}, loadBar(i.util)),
    h("td", {}, fmtBps(i.in_bps)), h("td", {}, fmtBps(i.out_bps)),
    errCell(i.errors), errCell(i.discards),
    h("td", { class: "muted", title: i.since ? fmtTime(tsIso(i.since)) : "" }, i.since ? fmtAgo(tsIso(i.since)) : "—"))));
  sizeBars($("#mon-d-ifaces"));
  $("#mon-d-ifaces-empty").hidden = rows.length > 0;
  $("#mon-d-ifaces-empty").textContent = r.interfaces.length ? "Every port is switched off (tick 'Switched-off ports too')." : "No interfaces read yet (they are read every few minutes with SNMP).";
}

$("#mon-d-ifaces-all").addEventListener("change", monRenderInterfaces);
$("#mon-d-ifaces-sort").addEventListener("change", monRenderInterfaces);

async function monOpenIface(deviceId, ifIndex, hours = mon.ifHours || 24) {
  mon.ifHours = hours;
  let r;
  try {
    r = await api(`/api/monitoring/devices/${deviceId}/interfaces/${ifIndex}?hours=${hours}`);
  } catch (e) {
    return toast(e.message);
  }
  mon.iface = { deviceId, ifIndex };
  const i = r.interface;
  $("#mon-if-title").textContent = `${r.device} ${i.name || i.descr}`;
  $("#mon-if-state").textContent = [i.alias, `${i.oper_label}${i.since ? ` since ${fmtTime(tsIso(i.since))}` : ""}`, i.speed ? `${fmtSpeed(i.speed)}b/s` : "",
    i.util !== null ? `now ${Math.round(i.util * 100)}% (in ${fmtBps(i.in_bps)}, out ${fmtBps(i.out_bps)})` : ""].filter(Boolean).join(" · ");
  $$("#mon-if-range button").forEach((b) => b.classList.toggle("active", Number(b.dataset.hours) === hours));
  monTrafficGraph(r, i.speed);
  monErrorGraph(r);
  $("#mon-if-note").textContent = r.detail ? "Every reading (averaged into the width of the graph)." : "Hourly averages, with the peak of each hour as the band.";
  if (!$("#mon-if-dialog").open) $("#mon-if-dialog").showModal();
}

function monAxis(r, W, H, L, B, top, unit) {
  const x = (t) => L + ((t - r.since_ts) / (r.until_ts - r.since_ts)) * (W - L - 6);
  const y = (v) => 10 + (1 - v / top) * (H - 10 - B);
  const kids = [];
  for (const f of [0, 0.5, 1]) {
    kids.push(svgEl("line", { x1: L, x2: W - 6, y1: y(top * f), y2: y(top * f), class: "grid" }),
      svgEl("text", { x: L - 6, y: y(top * f) + 4, "text-anchor": "end" }, unit(top * f)));
  }
  const span = r.until_ts - r.since_ts;
  for (const f of [0, 0.25, 0.5, 0.75, 1]) {
    const t = r.since_ts + span * f;
    kids.push(svgEl("text", { x: Math.min(W - 30, Math.max(L + 20, x(t))), y: H - 4, "text-anchor": "middle" },
      span > 3 * 86400 ? new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" })
        : new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })));
  }
  return { x, y, kids };
}

function monLine(pts, key, x, y, cls) {
  const runs = [];
  let run = [];
  const step = pts.length > 1 ? (pts[pts.length - 1].ts - pts[0].ts) / (pts.length - 1) : 0;
  for (const p of pts) {
    if (p[key] === null || p[key] === undefined || (run.length && p.ts - run[run.length - 1].ts > step * 2.5)) {
      if (run.length) runs.push(run);
      run = [];
    }
    if (p[key] !== null && p[key] !== undefined) run.push(p);
  }
  if (run.length) runs.push(run);
  return runs.map((r) => svgEl("polyline", { points: r.map((p) => `${x(p.ts)},${y(p[key])}`).join(" "), class: cls }));
}

function monTrafficGraph(r, speed) {
  const W = 1000, H = 220, L = 70, B = 22, pts = r.graph;
  const peak = Math.max(1, ...pts.flatMap((p) => [p.in_max ?? p.in_bps ?? 0, p.out_max ?? p.out_bps ?? 0]));
  const top = peak * 1.15;
  const { x, y, kids } = monAxis(r, W, H, L, B, top, fmtBps);
  if (speed && speed <= top) kids.push(svgEl("line", { x1: L, x2: W - 6, y1: y(speed), y2: y(speed), class: "limit" }));
  for (const [avg, max] of [["in_bps", "in_max"], ["out_bps", "out_max"]]) {
    const band = pts.filter((p) => p[max] !== null && p[max] !== undefined && p[max] > (p[avg] ?? 0));
    for (const p of band) kids.push(svgEl("line", { x1: x(p.ts), x2: x(p.ts), y1: y(p[max]), y2: y(p[avg] ?? 0), class: `peak ${avg === "in_bps" ? "in" : "out"}` }));
  }
  kids.push(...monLine(pts, "in_bps", x, y, "line in"), ...monLine(pts, "out_bps", x, y, "line out"));
  if (!pts.length) kids.push(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "none" }, "No readings in this period"));
  $("#mon-if-graph").replaceChildren(svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Traffic in and out" }, kids));
}

function monErrorGraph(r) {
  const pts = r.graph;
  const any = pts.some((p) => p.errors || p.discards);
  $("#mon-if-errors").hidden = !any;
  if (!any) return;
  const W = 1000, H = 110, L = 70, B = 22;
  const top = Math.max(1, ...pts.flatMap((p) => [p.errors || 0, p.discards || 0])) * 1.15;
  const { x, y, kids } = monAxis(r, W, H, L, B, top, (v) => `${v.toFixed(v < 10 ? 1 : 0)}/min`);
  kids.push(...monLine(pts, "errors", x, y, "line err"), ...monLine(pts, "discards", x, y, "line disc"),
    svgEl("text", { x: W - 10, y: 22, "text-anchor": "end", class: "key" }, "errors (red) and discards (orange) a minute"));
  $("#mon-if-errors").replaceChildren(svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Errors and discards" }, kids));
}

$$("#mon-if-range button").forEach((b) => b.addEventListener("click", () => monOpenIface(mon.iface.deviceId, mon.iface.ifIndex, Number(b.dataset.hours))));
$("#mon-if-close").addEventListener("click", () => $("#mon-if-dialog").close());

async function monPorts() {
  const r = await api("/api/monitoring/ports").catch(() => null);
  $("#mon-ports").hidden = !r || (!r.busiest.length && !r.errors.length);
  if (!r) return;
  const port = (i) => h("td", {}, h("b", {}, i.name || i.descr), i.alias ? h("small", { class: "muted" }, ` ${i.alias}`) : null);
  $("#mon-busiest tbody").replaceChildren(...r.busiest.map((i) => h("tr", { class: "link-row", onclick: () => monOpenIface(i.device_id, i.if_index) },
    h("td", {}, i.device), port(i), h("td", {}, loadBar(i.util)), h("td", {}, fmtBps(i.in_bps)), h("td", {}, fmtBps(i.out_bps)))));
  $("#mon-errors tbody").replaceChildren(...r.errors.map((i) => h("tr", { class: "link-row", onclick: () => monOpenIface(i.device_id, i.if_index) },
    h("td", {}, i.device), port(i), errCell(i.errors), errCell(i.discards))));
  $("#mon-errors-empty").hidden = r.errors.length > 0;
  sizeBars($("#mon-ports"));
}

/** Traffic on the ports at both ends of each line on the network map. */
async function monLinkLoad(data) {
  if (!hasModule("monitoring") || !can("monitoring", "view")) return new Map();
  const ids = new Map(data.nodes.filter((n) => n.id !== undefined && (n.kind === "device" || n.kind === "other_site")).map((n) => [n.key, n.id]));
  const ports = [];
  for (const e of data.edges) {
    for (const l of e.links) {
      if (ids.has(e.a) && l.a_port) ports.push({ device_id: ids.get(e.a), port: l.a_port });
      if (ids.has(e.b) && l.b_port) ports.push({ device_id: ids.get(e.b), port: l.b_port });
    }
  }
  if (!ports.length) return new Map();
  const r = await api("/api/monitoring/link-load", { method: "POST", body: { ports } }).catch(() => null);
  return new Map((r ? r.ports : []).map((p) => [`${p.device_id}|${p.port}`, p]));
}

/** Up/down per device for the network map (empty when monitoring can't be seen). */
async function monStatesForMap() {
  if (!hasModule("monitoring") || !can("monitoring", "view")) return new Map();
  const data = await api("/api/monitoring/devices").catch(() => null);
  return new Map((data ? data.devices : []).filter((r) => r.monitored).map((r) => [r.id, r]));
}

// ---------- syslog ----------

const SEV_NAMES = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"];
const sl = { sev: null, next: null, timer: null, devices: [], howto: null, counts: [0, 0, 0, 0, 0, 0, 0, 0] };

/** The filters as query parameters (severities only when asked: the counts show them all). */
function slParams(withSev = true) {
  const p = new URLSearchParams();
  const range = $("#sl-range").value;
  if (range === "custom") {
    if ($("#sl-from").value) p.set("since", new Date($("#sl-from").value).toISOString());
    if ($("#sl-to").value) p.set("until", new Date($("#sl-to").value).toISOString());
  } else {
    p.set("since", new Date(Date.now() - Number(range) * 1000).toISOString());
  }
  if ($("#sl-device").value) p.set("device", $("#sl-device").value);
  if ($("#sl-search").value.trim()) p.set("q", $("#sl-search").value.trim());
  if (withSev && sl.sev) p.set("severities", [...sl.sev].join(","));
  return p;
}

async function loadSyslog() {
  const chosen = $("#sl-device").value;
  sl.devices = await api("/api/devices").catch(() => sl.devices);
  {
    $("#sl-device").replaceChildren(h("option", { value: "" }, "All devices"),
      h("option", { value: "unknown" }, "Senders not in the inventory"),
      ...sl.devices.map((d) => h("option", { value: d.id }, d.name)));
    $("#sl-device").value = chosen;
  }
  if (sl.pick !== undefined) {  // from a device's Logs button
    $("#sl-device").value = sl.pick;
    delete sl.pick;
  }
  await Promise.all([slStatus(), slSearch()]);
}

async function slStatus() {
  const s = await api("/api/syslog/status").catch(() => null);
  if (!s) return;
  const used = (s.bytes / 2 ** 30).toFixed(s.bytes < 2 ** 30 ? 2 : 1);
  const r = s.receiver;
  const parts = [s.running ? "Receiving" : "The syslog receiver isn't running (netops-syslog service)",
    r && r.last_message ? `last message ${fmtAgo(new Date(r.last_message * 1000).toISOString())}` : null,
    r && r.tls_port ? (r.tls_error ? `TLS NOT LISTENING: ${r.tls_error}` : `TLS on port ${r.tls_port}`) : null,
    `${s.days} day(s) kept, ${used} GB of ${s.max_bytes / 2 ** 30} GB, up to ${s.keep_days} days`,
    r && r.stopped_reason ? `NOT STORING: ${r.stopped_reason}` : null,
    r && r.dropped_rate ? `${r.dropped_rate} dropped (too many from one sender)` : null];
  $("#sl-status").textContent = parts.filter(Boolean).join(" · ");
  $("#sl-status").classList.toggle("bad-text", !s.running || !!(r && (r.stopped_reason || r.tls_error)));
}

async function slSearch() {
  const p = slParams();
  $("#sl-export").href = `/api/syslog/export.log?${p}`;
  try {
    const [page, sum] = await Promise.all([api(`/api/syslog/messages?${p}`),
      api(`/api/syslog/summary?${slParams(false)}&buckets=80`)]);
    sl.next = page.next;
    $("#sl-table tbody").replaceChildren(...page.rows.map(slRow));
    $("#sl-empty").hidden = page.rows.length > 0;
    $("#sl-empty").textContent = "No messages for these filters. Widen the period, or use Help to set up the devices.";
    $("#sl-more").hidden = !sl.next;
    sl.counts = sum.severity;
    slSevChips();
    slTimeline(sum);
  } catch (e) {
    toast(e.message);
  }
}

async function slMore() {
  if (!sl.next) return;
  const p = slParams();
  p.set("before", sl.next);
  const page = await api(`/api/syslog/messages?${p}`).catch((e) => toast(e.message));
  if (!page) return;
  sl.next = page.next;
  $("#sl-table tbody").append(...page.rows.map(slRow));
  $("#sl-more").hidden = !sl.next;
}

function slRow(r) {
  const when = new Date(r.time);
  const device = r.device
    ? h("span", { class: "link", title: `Only ${r.device}`, onclick: () => slPick(String(r.device_id)) }, r.device)
    : h("span", { class: "link", title: "Only senders not in the inventory", onclick: () => slPick("unknown") }, r.src);
  return h("tr", {},
    h("td", { class: "when", title: when.toISOString() },
      when.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" })),
    h("td", {}, device, r.device ? h("small", { class: "muted" }, ` ${r.src}`) : null),
    h("td", {}, h("span", { class: `badge s${r.sev}` }, SEV_NAMES[r.sev] || r.sev)),
    h("td", {}, r.tag || "", h("small", { class: "muted" }, ` ${r.facility}`)),
    h("td", { class: "msg", title: r.text }, r.message));
}

function slPick(device) {
  $("#sl-device").value = device;
  slSearch();
}

function slSevChips() {
  $("#sl-sev").replaceChildren(...SEV_NAMES.map((name, i) => h("button", {
    class: `sev s${i}${sl.sev && !sl.sev.has(i) ? " off" : ""}`,
    title: sl.sev && !sl.sev.has(i) ? `Show ${name}` : `Hide ${name}`,
    onclick: () => {
      const all = new Set(sl.sev || [0, 1, 2, 3, 4, 5, 6, 7]);
      all.has(i) ? all.delete(i) : all.add(i);
      sl.sev = all.size === 8 ? null : all;
      slSearch();
    },
  }, `${name} ${sl.counts[i]}`)));
}

function slTimeline(sum) {
  // Only the severities chosen above (the counts on the buttons show them all).
  const shown = sum.timeline.map((b) => b.map((n, s) => (!sl.sev || sl.sev.has(s) ? n : 0)));
  sum = { ...sum, timeline: shown };
  const totals = sum.timeline.map((b) => b.reduce((a, n) => a + n, 0));
  const max = Math.max(1, ...totals);
  const start = new Date(sum.since).getTime();
  const groups = [["bad", [0, 1, 2, 3]], ["warn", [4]], ["note", [5]], ["info", [6, 7]]];
  $("#sl-timeline").replaceChildren(...sum.timeline.map((b, i) => {
    const from = new Date(start + i * sum.bucket_seconds * 1000);
    const to = new Date(from.getTime() + sum.bucket_seconds * 1000);
    const bar = h("div", {
      class: "bar",
      title: `${from.toLocaleString()} – ${to.toLocaleTimeString()}: ${totals[i]} message(s)` +
        (b[0] + b[1] + b[2] + b[3] ? `, ${b[0] + b[1] + b[2] + b[3]} error(s) or worse` : "") +
        (b[4] ? `, ${b[4]} warning(s)` : "") + "\nClick to look at this period",
      onclick: () => slZoom(from, to),
    }, ...groups.map(([cls, sevs]) => {
      const n = sevs.reduce((a, s) => a + b[s], 0);
      if (!n) return null;
      const seg = h("div", { class: `seg ${cls}` });
      seg.style.height = `${(n / max) * 100}%`;
      return seg;
    }));
    return bar;
  }));
}

function toLocalInput(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function slZoom(from, to) {
  $("#sl-range").value = "custom";
  $("#sl-custom").hidden = false;
  $("#sl-from").value = toLocalInput(from);
  $("#sl-to").value = toLocalInput(new Date(to.getTime() + 60000));
  $("#sl-live").checked = false;
  slLive();
  slSearch();
}

function slLive() {
  clearInterval(sl.timer);
  if ($("#sl-live").checked && $("#sl-range").value !== "custom") {
    sl.timer = setInterval(() => {
      if (state.view === "syslog" && !document.hidden) { slSearch(); slStatus(); }
    }, 5000);
  }
}

$("#sl-range").addEventListener("change", () => {
  const custom = $("#sl-range").value === "custom";
  $("#sl-custom").hidden = !custom;
  if (custom && !$("#sl-from").value) {
    $("#sl-from").value = toLocalInput(new Date(Date.now() - 86400000));
    $("#sl-to").value = toLocalInput(new Date(Date.now() + 60000));
  }
  if (custom) $("#sl-live").checked = false;
  slLive();
  slSearch();
});
["#sl-from", "#sl-to", "#sl-device"].forEach((s) => $(s).addEventListener("change", slSearch));
let slTyping;
$("#sl-search").addEventListener("input", () => { clearTimeout(slTyping); slTyping = setTimeout(slSearch, 400); });
$("#sl-live").addEventListener("change", slLive);
$("#sl-more").addEventListener("click", slMore);
$$(".sev-filter [data-sev]").forEach((b) => b.addEventListener("click", () => {
  sl.sev = b.dataset.sev ? new Set(b.dataset.sev.split(",").map(Number)) : null;
  slSearch();
}));

// Help: suggested device configs, with this server's address filled in.
async function slHelp() {
  if (!sl.howto) sl.howto = await api("/api/syslog/howto").catch((e) => toast(e.message));
  if (!sl.howto) return;
  const hw = sl.howto;
  const sel = $("#sl-help-platform");
  if (!sel.options.length) {
    sel.replaceChildren(...hw.platforms.map((p, i) => h("option", { value: i }, p.title)));
    $("#sl-help-server").value = hw.server;
  }
  slHelpShow();
  $("#sl-help-dialog").showModal();
}

function slHelpShow() {
  const hw = sl.howto;
  const p = hw.platforms[Number($("#sl-help-platform").value) || 0];
  const server = $("#sl-help-server").value.trim() || "<server address>";
  const tls = $("#sl-help-mode").value === "tls";
  const general = tls ? [...hw.tls_general, ...hw.general.slice(0, 2)] : hw.general;
  if (tls && !hw.tls_port) general.unshift("Syslog over TLS is OFF on this server: an admin switches it on first (docs/syslog.md).");
  $("#sl-help-general").replaceChildren(...general.map((g) => h("li", {}, g)));
  if (tls && !p.tls) {
    $("#sl-help-text").textContent = `${p.title} can't send syslog over TLS (or not on every release). ` +
      "Use plain syslog over the management network, or check the vendor's documentation for your release.";
    $("#sl-help-notes").textContent = "";
    return;
  }
  $("#sl-help-text").textContent = (tls ? p.tls : p.text).replaceAll("{server}", server);
  $("#sl-help-notes").textContent = (p.kind === "gui" ? "In the device's web page. " : "") + (tls ? "" : p.notes || "");
}

$("#sl-help").addEventListener("click", slHelp);
$("#sl-help-close").addEventListener("click", () => $("#sl-help-dialog").close());
$("#sl-help-platform").addEventListener("change", slHelpShow);
$("#sl-help-server").addEventListener("input", slHelpShow);
$("#sl-help-mode").addEventListener("change", slHelpShow);
$("#sl-help-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#sl-help-text").textContent);
    toast("Copied");
  } catch {
    toast("Select the text and copy it (the browser blocked copying)");
  }
});

// ---------- network inventory ----------

const inv = { meta: null, rows: [], cols: null };
const invColsKey = () => `inventory-columns:${state.user ? state.user.username : ""}`;

/** The columns this person chose (and their order); the defaults until they choose. */
function invColumns() {
  const all = inv.meta.fields;
  let keys = null;
  try { keys = JSON.parse(localStorage.getItem(invColsKey()) || "null"); } catch { keys = null; }
  if (!Array.isArray(keys)) keys = all.filter((f) => f.default_shown).map((f) => f.key);
  const known = new Map(all.map((f) => [f.key, f]));
  return keys.filter((k) => known.has(k)).map((k) => known.get(k));
}

function invSaveColumns(keys) {
  try { localStorage.setItem(invColsKey(), JSON.stringify(keys)); } catch { /* private window */ }
}

async function loadInventory() {
  try {
    [inv.meta, inv.rows] = await Promise.all([api("/api/inventory/meta"), api("/api/inventory/assets")]);
  } catch (e) {
    return toast(e.message);
  }
  const fill = (sel, values, all) => {
    const keep = $(sel).value;
    $(sel).replaceChildren(h("option", { value: "" }, all), ...values.map((v) => h("option", { value: v }, v)));
    $(sel).value = values.includes(keep) ? keep : "";
  };
  const distinct = (key) => [...new Set(inv.rows.map((r) => invValue(r, key)).filter(Boolean))].sort();
  fill("#inv-type", distinct("type"), "All types");
  fill("#inv-site", distinct("site"), "All sites");
  fill("#inv-status", distinct("status"), "All statuses");
  const n = (f) => inv.rows.filter(f).length;
  $("#inv-summary").replaceChildren(
    ...[["Items", n(() => true), ""], ["Managed by the tools", n((r) => r.managed), "success"],
      ["Inventory only", n((r) => !r.managed), "never"],
      ["Spare or faulty", n((r) => ["spare", "faulty"].includes(invValue(r, "status"))), "failed"]]
      .map(([lbl, num, cls]) => h("div", { class: `tile card ${cls}` }, h("span", { class: "num" }, num), h("span", { class: "lbl" }, lbl))));
  renderInventory();
}

const invValue = (r, key) => {
  const v = r.values[key];
  return v === null || v === undefined || v === "" ? (r.auto[key] ?? "") : v;
};

function renderInventory() {
  const cols = invColumns();
  const q = $("#inv-search").value.trim().toLowerCase();
  const want = { type: $("#inv-type").value, site: $("#inv-site").value, status: $("#inv-status").value };
  const managed = $("#inv-managed").value;
  const rows = inv.rows.filter((r) => {
    if (Object.entries(want).some(([k, v]) => v && invValue(r, k) !== v)) return false;
    if (managed && (managed === "yes") !== r.managed) return false;
    if (!q) return true;
    return inv.meta.fields.some((f) => String(invValue(r, f.key)).toLowerCase().includes(q));
  });
  $("#inv-table thead").replaceChildren(h("tr", {}, ...cols.map((f) => h("th", {}, f.label)), h("th", {}, "Tools")));
  $("#inv-table tbody").replaceChildren(...rows.map((r) => h("tr", {},
    ...cols.map((f) => {
      const v = invValue(r, f.key);
      if (f.key === "name") return h("td", {}, h("span", { class: "link", onclick: () => invEdit(r) }, v || "(no name)"));
      if (f.key === "site" && siteOf(v)) return h("td", {}, siteLink(v));
      if (f.key === "rack" && v) return h("td", {}, h("span", { class: "link", title: "Show the rack", onclick: () => showInRack(r.id) }, v));
      const auto = (r.values[f.key] === null || r.values[f.key] === "" || r.values[f.key] === undefined) && r.auto[f.key];
      return h("td", { class: f.key === "notes" || f.max_length > 1000 ? "wrap" : "", title: auto ? "From the device" : "" },
        auto ? h("span", { class: "muted" }, v) : String(v ?? ""));
    }),
    h("td", {}, invTools(r)))));
  $("#inv-empty").hidden = rows.length > 0;
  $("#inv-empty").textContent = inv.rows.length ? "Nothing matches the filters." :
    "The inventory is empty. Devices added on Config backups appear here; add anything else with + Add item, or import a spreadsheet.";
}

function invTools(r) {
  if (!r.managed) return h("span", { class: "badge never", title: "Recorded only: not backed up or checked" }, "Inventory only");
  const out = [];
  if (r.backup) out.push(h("span", { class: `badge ${r.backup === "success" ? "success" : r.backup === "failed" ? "failed" : "never"}`, title: "Config backup" },
    { success: "Backup OK", failed: "Backup failed", never: "Never backed up" }[r.backup] || r.backup));
  if (r.compliance) out.push(h("span", { class: `badge ${r.compliance}`, title: "Firmware against the standard" },
    { compliant: "On standard", behind: "Behind", ahead: "Ahead", no_standard: "No standard", unknown: "Version unknown" }[r.compliance] || r.compliance));
  if (hasModule("backups") && can("backups", "view")) out.push(h("button", { class: "small", onclick: async () => {
    try { openDetail(await api(`/api/backup/devices/${r.device.id}`)); } catch (e) { toast(e.message); }
  } }, "Backups"));
  if (hasModule("syslog") && can("syslog", "view")) out.push(h("button", { class: "small", onclick: () => { sl.pick = String(r.device.id); switchView("syslog"); } }, "Logs"));
  if (hasModule("circuits") && can("circuits", "view") && ["switch", "router", "firewall"].includes(r.values ? r.values.type : r.type)) {
    out.push(h("button", { class: "small", title: "What is on each port", onclick: () => openPorts(r.device) }, "Ports"));
  }
  return h("span", { class: "actions" }, ...out);
}

// The one dialog: an item, the columns, the custom columns or an import.
function invDialog(title, ...content) {
  $("#inv-dialog-title").textContent = title;
  $("#inv-dialog-body").replaceChildren(...content);
  if (!$("#inv-dialog").open) $("#inv-dialog").showModal();
}
$("#inv-dialog-close").addEventListener("click", () => $("#inv-dialog").close());

function invInput(f, value, auto, locked) {
  const attrs = { name: f.key, disabled: locked };
  if (f.kind === "choice") {
    return h("select", attrs, h("option", { value: "" }, auto ? `(${auto})` : "—"),
      ...f.choices.map((c) => h("option", { value: c, selected: c === value }, c)));
  }
  if (["notes", "access", "circuits"].includes(f.key)) return h("textarea", { ...attrs, rows: 3 }, value ?? "");
  const type = f.kind === "number" ? "number" : f.kind === "date" ? "date" : "text";
  return h("input", { ...attrs, type, value: value ?? "", placeholder: auto ? `From the device: ${auto}` : "", min: type === "number" ? 0 : null,
    list: f.key === "site" && inv.meta && inv.meta.sites ? "inv-site-names" : null });
}

function invEdit(r = null, after = loadInventory) {
  const canEdit = inv.meta.can_manage;
  const err = errorLine();
  const groups = new Map();
  inv.meta.fields.forEach((f) => groups.set(f.group, [...(groups.get(f.group) || []), f]));
  const form = h("form", { class: "form" },
    r && r.managed ? h("p", { class: "muted" }, `Managed by the tools as ${r.device.name}. Grey values come from the device; type over them to replace them. ` +
      "Rename it on Config backups.") : "",
    h("div", { class: "inv-groups" }, ...[...groups].map(([group, list]) => h("fieldset", {}, h("legend", {}, group),
      ...list.map((f) => h("label", {}, f.label,
        invInput(f, r ? r.values[f.key] : (f.key === "status" ? "in service" : ""), r ? r.auto[f.key] : "",
          !canEdit || (r && r.managed && f.key === "name"))))))),
    h("datalist", { id: "inv-site-names" }, ...(inv.meta.sites || []).map((n) => h("option", { value: n }))),
    err);
  const save = async () => {
    err.hidden = true;
    const values = {};
    inv.meta.fields.forEach((f) => {
      const el = form.elements[f.key];
      if (!el || el.disabled) return;
      values[f.key] = el.value;
    });
    try {
      if (r) await api(`/api/inventory/assets/${r.id}`, { method: "PUT", body: { values } });
      else await api("/api/inventory/assets", { method: "POST", body: { values } });
      $("#inv-dialog").close();
      toast("Saved");
      after();
    } catch (e) { showError(err, e); }
  };
  const buttons = h("div", { class: "dialog-actions" });
  if (r && r.managed && hasModule("circuits") && can("circuits", "view")) {
    buttons.append(h("button", { type: "button", onclick: () => { $("#inv-dialog").close(); openPorts(r.device); } }, "Ports"));
  }
  if (r && (r.values.type === "rack" || r.values.rack)) {
    buttons.append(h("button", { type: "button", onclick: () => { $("#inv-dialog").close(); showInRack(r.id); } },
      r.values.type === "rack" ? "Show the rack" : "Show in its rack"));
  }
  if (r && !r.managed && inv.meta.can_add_devices) buttons.append(h("button", { type: "button", onclick: () => invManage(r) }, "Manage this device…"));
  if (r && !r.managed && canEdit) buttons.append(h("button", { type: "button", class: "danger", onclick: async () => {
    if (!confirm(`Delete ${invValue(r, "name")} from the inventory?`)) return;
    try { await api(`/api/inventory/assets/${r.id}`, { method: "DELETE" }); $("#inv-dialog").close(); after(); } catch (e) { showError(err, e); }
  } }, "Delete"));
  if (canEdit) buttons.append(h("button", { type: "button", class: "primary", onclick: save }, "Save"));
  invDialog(r ? invValue(r, "name") : "Add to the inventory", form, buttons);
}

/** Turn an inventory-only row into a device the tools back up and check. */
async function invManage(r) {
  const creds = await api("/api/credentials").catch(() => []);
  const err = errorLine();
  const platform = h("select", { required: true }, h("option", { value: "" }, "— choose —"), ...platformOptions());
  const address = h("input", { value: invValue(r, "mgmt_ip"), placeholder: "10.0.0.1", required: true });
  const cred = h("select", {}, h("option", { value: "" }, "— none —"), ...creds.map((c) => h("option", { value: c.id }, `${c.name} (${c.username})`)));
  invDialog(`Manage ${invValue(r, "name")}`,
    h("p", { class: "muted" }, "The tools will back it up, check its firmware and match its syslog. It then counts towards the licence's devices."),
    h("label", {}, "Platform", platform), h("label", {}, "Management address", address), h("label", {}, "Credential profile", cred), err,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "primary", onclick: async () => {
      err.hidden = true;
      try {
        await api(`/api/inventory/assets/${r.id}/manage`, { method: "POST", body: {
          platform: platform.value, address: address.value.trim(), credential_id: cred.value ? Number(cred.value) : null } });
        $("#inv-dialog").close();
        toast("Now managed: its first backup and version check follow on their schedules");
        loadInventory();
      } catch (e) { showError(err, e); }
    } }, "Manage")));
}

/** Choose and order the columns you see (remembered for you, in this browser). */
function invColumnsDialog() {
  chooseColumns(invDialog, () => $("#inv-dialog").close(), inv.meta.fields, invColumns().map((f) => f.key),
    (keys) => { invSaveColumns(keys); renderInventory(); },
    () => { saveLocal(invColsKey(), null); renderInventory(); });
}

/** Admins: the site's own columns, for everyone. */
function invFieldsDialog() {
  const custom = inv.meta.fields.filter((f) => f.group === "Custom");
  const err = errorLine();
  const label = h("input", { placeholder: "e.g. Power feed", maxlength: 100 });
  const kind = h("select", {}, ...[["text", "Text"], ["number", "Number"], ["date", "Date"], ["choice", "Pick-list"]].map(([v, l]) => h("option", { value: v }, l)));
  const choices = h("input", { placeholder: "For a pick-list: A, B, C" });
  const call = async (fn) => { err.hidden = true; try { await fn(); await loadInventory(); invFieldsDialog(); } catch (e) { showError(err, e); } };
  invDialog("Custom columns",
    h("p", { class: "muted" }, "Columns you add here are there for everyone at this site, in the item form, the Columns list, imports and exports."),
    custom.length ? h("ul", { class: "col-list" }, ...custom.map((f) => h("li", {},
      h("span", {}, f.label, h("small", { class: "muted" }, ` ${f.kind}${f.choices.length ? `: ${f.choices.join(", ")}` : ""}`)), h("span", { class: "spacer" }),
      h("button", { type: "button", class: "small", onclick: () => {
        const name = prompt("New name for the column", f.label);
        if (!name) return;
        const list = f.kind === "choice" ? prompt("Choices, separated by commas", f.choices.join(", ")) : "";
        call(() => api(`/api/inventory/fields/${f.key}`, { method: "PUT", body: { label: name, kind: f.kind,
          choices: (list || "").split(",").map((c) => c.trim()).filter(Boolean) } }));
      } }, "Rename"),
      h("button", { type: "button", class: "small danger", onclick: () => {
        if (confirm(`Delete the column ${f.label} and everything typed in it?`)) call(() => api(`/api/inventory/fields/${f.key}`, { method: "DELETE" }));
      } }, "Delete")))) : h("p", { class: "muted" }, "No custom columns yet."),
    h("h3", {}, "Add a column"),
    h("div", { class: "grid2" }, h("label", {}, "Name", label), h("label", {}, "Kind", kind)),
    h("label", {}, "Choices", choices), err,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "primary", onclick: () => call(() =>
      api("/api/inventory/fields", { method: "POST", body: { label: label.value, kind: kind.value,
        choices: choices.value.split(",").map((c) => c.trim()).filter(Boolean) } })) }, "Add column")));
}

/** Import a spreadsheet: first what would change, then make the changes. */
function importDialog(dialog, close, base, intro, done) {
  const err = errorLine();
  const file = h("input", { type: "file", accept: ".xlsx,.xlsm,.csv" });
  const plan = h("div", { class: "inv-plan" });
  const go = h("button", { type: "button", class: "primary", disabled: true }, "Import");
  const send = async (commit) => {
    const f = file.files[0];
    const res = await fetch(`${base}/import?filename=${encodeURIComponent(f.name)}&commit=${commit}`, {
      method: "PUT", body: f, credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    return data;
  };
  file.addEventListener("change", async () => {
    err.hidden = true;
    plan.replaceChildren();
    go.disabled = true;
    if (!file.files[0]) return;
    try {
      const p = await send(false);
      plan.replaceChildren(
        h("p", {}, `${p.new.length} new, ${p.updated.length} to update, ${p.errors.length} with errors. Columns read: ${p.columns.join(", ")}.`),
        p.unknown_columns.length ? h("p", { class: "muted" }, `Not read (no such column): ${p.unknown_columns.join(", ")}. An admin can add them as custom columns.`) : "",
        p.errors.length ? h("ul", { class: "error" }, ...p.errors.slice(0, 50).map((e) => h("li", {}, `Row ${e.row}: ${e.message}`))) : "",
        p.updated.length ? h("ul", {}, ...p.updated.slice(0, 50).map((u) => h("li", {}, `${u.name}: ${u.changes.join(", ")}`))) : "");
      go.disabled = !!p.errors.length || !(p.new.length + p.updated.length);
    } catch (e) { showError(err, e); }
  });
  go.addEventListener("click", async () => {
    try {
      const p = await send(true);
      close();
      toast(`Imported: ${p.new.length} new, ${p.updated.length} updated`);
      done();
    } catch (e) { showError(err, e); }
  });
  dialog("Import a spreadsheet", h("p", { class: "muted" }, intro), file, plan, err, h("div", { class: "dialog-actions" }, go));
}

function invImportDialog() {
  importDialog(invDialog, () => $("#inv-dialog").close(), "/api/inventory",
    "Excel (.xlsx) or CSV, column names in the first row (the same names as in an export or a Blank template). Rows are matched to the inventory by serial number, then asset tag, then name; " +
    "anything not matched is added. Empty cells leave a value as it is. Nothing changes until you press Import.", loadInventory);
}

["#inv-type", "#inv-site", "#inv-status", "#inv-managed"].forEach((s) => $(s).addEventListener("change", renderInventory));
$("#inv-search").addEventListener("input", renderInventory);
$("#inv-add").addEventListener("click", () => invEdit());
$("#inv-columns").addEventListener("click", invColumnsDialog);
$("#inv-fields").addEventListener("click", invFieldsDialog);
$("#inv-import").addEventListener("click", invImportDialog);
$("#inv-template").addEventListener("click", () => templateDialog(invDialog, "/api/inventory", invColumns().map((f) => f.key),
  "Fill it in (one row per item) and bring it in with Import. Name is always in it. Rows are matched by serial number, then asset tag, then name; " +
  "you see what changes before anything is changed."));

// ---------- sites ----------

const site = { meta: null, data: { sites: [], unlisted: [] }, loading: Promise.resolve() };
const siteColsKey = () => `site-columns:${state.user ? state.user.username : ""}`;
const SITE_DEFAULT_COUNTS = ["#items", "#devices", "#backup_failed", "#circuits"];

function siteAllColumns() {
  return [...site.meta.fields, ...site.meta.counts.map((c) => ({ key: `#${c.key}`, label: c.label,
    group: c.key === "circuits" ? "From the circuit list" : "From the inventory" }))];
}

function siteColumns() {
  const all = new Map(siteAllColumns().map((c) => [c.key, c]));
  let keys = null;
  try { keys = JSON.parse(localStorage.getItem(siteColsKey()) || "null"); } catch { keys = null; }
  if (!Array.isArray(keys)) keys = [...site.meta.fields.filter((f) => f.default_shown).map((f) => f.key), ...SITE_DEFAULT_COUNTS];
  return keys.filter((k) => all.has(k)).map((k) => all.get(k));
}

function siteDialog(title, ...content) {
  $("#site-dialog-title").textContent = title;
  $("#site-dialog-body").replaceChildren(...content);
  if (!$("#site-dialog").open) $("#site-dialog").showModal();
}
const siteClose = () => $("#site-dialog").close();
$("#site-dialog-close").addEventListener("click", siteClose);

function loadSites() {
  $("#sites-list").hidden = false;
  $("#site-page").hidden = true;
  site.loading = fetchSites();
  return site.loading;
}

async function fetchSites() {
  try {
    [site.meta, site.data] = await Promise.all([api("/api/sites/meta"), api("/api/sites"), loadSiteIndex()]);
  } catch (e) {
    return toast(e.message);
  }
  const rows = site.data.sites;
  const fill = (sel, key, all) => {
    const keep = $(sel).value;
    const values = [...new Set(rows.map((r) => r.values[key]).filter(Boolean))].sort();
    $(sel).replaceChildren(h("option", { value: "" }, all), ...values.map((v) => h("option", { value: v }, v)));
    $(sel).value = values.includes(keep) ? keep : "";
  };
  fill("#site-type", "type", "All types");
  fill("#site-region", "region", "All regions");
  fill("#site-status", "status", "All statuses");
  const sum = (k) => rows.reduce((n, r) => n + r.counts[k], 0);
  $("#site-summary").replaceChildren(
    ...[["Sites", rows.length, ""], ["Live", rows.filter((r) => r.values.status === "live").length, "success"],
      ["Items at a site", sum("items"), ""], ["Managed devices", sum("devices"), "success"],
      ["Backups failing", sum("backup_failed"), "failed"]]
      .map(([lbl, num, cls]) => h("div", { class: `tile card ${cls}` }, h("span", { class: "num" }, num), h("span", { class: "lbl" }, lbl))));
  const un = site.data.unlisted;
  const note = $("#site-unlisted");
  note.hidden = !un.length;
  note.replaceChildren(...(un.length ? [
    h("span", {}, `The inventory uses ${un.length === 1 ? "a site" : `${un.length} sites`} not on this list: ` +
      un.map((u) => `${u.name} (${u.items})`).join(", ") + ". Add them, or correct the Site on those items."),
    site.meta.can_manage ? h("button", { class: "small", onclick: async () => {
      try {
        const r = await api("/api/sites/from-inventory", { method: "POST" });
        toast(`Added ${r.added.length} site(s)`);
        loadSites();
      } catch (e) { toast(e.message); }
    } }, "Add them to the list") : null] : []));
  renderSites();
}

function renderSites() {
  const cols = siteColumns();
  const q = $("#site-search").value.trim().toLowerCase();
  const want = { type: $("#site-type").value, region: $("#site-region").value, status: $("#site-status").value };
  const rows = site.data.sites.filter((r) => {
    if (Object.entries(want).some(([k, v]) => v && r.values[k] !== v)) return false;
    return !q || Object.values(r.values).some((v) => String(v ?? "").toLowerCase().includes(q));
  });
  $("#site-table thead").replaceChildren(h("tr", {}, ...cols.map((c) => h("th", {}, c.label))));
  $("#site-table tbody").replaceChildren(...rows.map((r) => h("tr", {}, ...cols.map((c) => {
    if (c.key === "name") return h("td", {}, h("span", { class: "link", onclick: () => openSitePage(r.id) }, r.values.name));
    if (c.key.startsWith("#")) {
      const n = r.counts[c.key.slice(1)];
      if (c.key === "#circuits") {
        return h("td", {}, h("span", { class: "count-link", onclick: () => openSiteCircuits(r.id), title: "See this site's circuits" }, n));
      }
      const cls = c.key === "#backup_failed" || c.key === "#behind" ? (n ? "badge failed" : "muted") : "count-link";
      return h("td", {}, h("span", { class: cls, onclick: () => openSitePage(r.id), title: "See what's at this site" }, n));
    }
    const v = r.values[c.key];
    return h("td", { class: ["address", "access", "circuits", "notes"].includes(c.key) ? "wrap" : "" }, String(v ?? ""));
  }))));
  $("#site-empty").hidden = rows.length > 0;
  $("#site-empty").textContent = site.data.sites.length ? "Nothing matches the filters." :
    "No sites yet. Add them with + Add site, import a spreadsheet (Blank template gives you one to fill in), or add the ones the inventory already uses.";
}

/** After a site's details change: refresh the page you are on (the list or the site's page). */
function siteChanged() {
  if ($("#site-page").hidden) return loadSites();
  site.loading = fetchSites();
  refreshSitePage();
}

/** A site: its details, and what the inventory has there. */
async function siteEdit(r = null, itemsFirst = false) {
  const canEdit = site.meta.can_manage;
  const err = errorLine();
  const groups = new Map();
  site.meta.fields.forEach((f) => groups.set(f.group, [...(groups.get(f.group) || []), f]));
  const form = h("form", { class: "form" },
    h("div", { class: "inv-groups" }, ...[...groups].map(([group, list]) => h("fieldset", {}, h("legend", {}, group),
      ...list.map((f) => h("label", {}, f.label, invInput(f, r ? r.values[f.key] : (f.key === "status" ? "live" : ""), "", !canEdit)))))),
    err);
  const save = async () => {
    err.hidden = true;
    const values = {};
    site.meta.fields.forEach((f) => { const el = form.elements[f.key]; if (el && !el.disabled) values[f.key] = el.value; });
    try {
      if (r) {
        const res = await api(`/api/sites/${r.id}`, { method: "PUT", body: { values } });
        toast(res.renamed_on ? `Saved; the Site was changed on ${res.renamed_on} item(s) and device(s)` : "Saved");
      } else {
        await api("/api/sites", { method: "POST", body: { values } });
        toast("Saved");
      }
      siteClose();
      siteChanged();
    } catch (e) { showError(err, e); }
  };
  const buttons = h("div", { class: "dialog-actions" });
  if (r && canEdit) buttons.append(h("button", { type: "button", class: "danger", onclick: async () => {
    if (!confirm(`Delete the site ${r.values.name}? Items at the site keep their Site value.`)) return;
    try { await api(`/api/sites/${r.id}`, { method: "DELETE" }); siteClose(); loadSites(); } catch (e) { showError(err, e); }
  } }, "Delete"));
  if (canEdit) buttons.append(h("button", { type: "button", class: "primary", onclick: save }, "Save"));
  if (!r) return siteDialog("Add a site", form, buttons);

  const items = h("div", {}, h("p", { class: "muted" }, "Loading…"));
  const parts = [h("h3", {}, `At this site (${r.counts.items})`),
    r.counts.circuits !== undefined && can("circuits", "view")
      ? h("p", {}, h("button", { type: "button", onclick: () => openSiteCircuits(r.id) }, `Circuits at this site (${r.counts.circuits})`)) : "",
    items];
  const details = [form, h("p", { class: "muted" }, "Renaming the site, or changing its code, changes the Site on the items and devices that use the old one."), buttons];
  siteDialog(r.values.name, ...(itemsFirst ? [...parts, ...details] : [...details, ...parts]));
  try {
    const list = await api(`/api/sites/${r.id}/items`);
    items.replaceChildren(list.length ? h("table", {},
      h("thead", {}, h("tr", {}, ["Name", "Type", "Model", "Address", "Where", "Status", "Tools"].map((t) => h("th", {}, t)))),
      h("tbody", {}, list.map((i) => h("tr", {},
        h("td", { class: "name" }, h("span", { class: "link", title: "Open in the inventory", onclick: () => openItem(i.id) }, i.name)),
        h("td", {}, i.type || "—"), h("td", {}, i.model || "—"),
        h("td", {}, i.mgmt_ip ? h("code", {}, i.mgmt_ip) : "—"),
        h("td", {}, [i.building, i.room, i.rack].filter(Boolean).join(" / ") || "—"),
        h("td", {}, i.status || "—"), h("td", {}, invTools(i))))))
      : h("p", { class: "muted" }, "Nothing in the inventory has this site yet: set the Site on items (name or code) or on devices on Config backups."));
  } catch (e) { items.replaceChildren(h("p", { class: "error" }, e.message)); }
}

/** Admins: the site list's own columns. */
function siteFieldsDialog() {
  const custom = site.meta.fields.filter((f) => f.group === "Custom");
  const err = errorLine();
  const label = h("input", { placeholder: "e.g. Power supply", maxlength: 100 });
  const kind = h("select", {}, ...[["text", "Text"], ["number", "Number"], ["date", "Date"], ["choice", "Pick-list"]].map(([v, l]) => h("option", { value: v }, l)));
  const choices = h("input", { placeholder: "For a pick-list: A, B, C" });
  const call = async (fn) => { err.hidden = true; try { await fn(); await loadSites(); siteFieldsDialog(); } catch (e) { showError(err, e); } };
  siteDialog("Custom columns",
    h("p", { class: "muted" }, "Columns you add here are there for everyone: in the site form, Columns, imports, exports and the blank template."),
    custom.length ? h("ul", { class: "col-list" }, ...custom.map((f) => h("li", {},
      h("span", {}, f.label, h("small", { class: "muted" }, ` ${f.kind}${f.choices.length ? `: ${f.choices.join(", ")}` : ""}`)), h("span", { class: "spacer" }),
      h("button", { type: "button", class: "small", onclick: () => {
        const name = prompt("New name for the column", f.label);
        if (!name) return;
        const list = f.kind === "choice" ? prompt("Choices, separated by commas", f.choices.join(", ")) : "";
        call(() => api(`/api/sites/fields/${f.key}`, { method: "PUT", body: { label: name, kind: f.kind,
          choices: (list || "").split(",").map((c) => c.trim()).filter(Boolean) } }));
      } }, "Rename"),
      h("button", { type: "button", class: "small danger", onclick: () => {
        if (confirm(`Delete the column ${f.label} and everything typed in it?`)) call(() => api(`/api/sites/fields/${f.key}`, { method: "DELETE" }));
      } }, "Delete")))) : h("p", { class: "muted" }, "No custom columns yet."),
    h("h3", {}, "Add a column"),
    h("div", { class: "grid2" }, h("label", {}, "Name", label), h("label", {}, "Kind", kind)),
    h("label", {}, "Choices", choices), err,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "primary", onclick: () => call(() =>
      api("/api/sites/fields", { method: "POST", body: { label: label.value, kind: kind.value,
        choices: choices.value.split(",").map((c) => c.trim()).filter(Boolean) } })) }, "Add column")));
}

["#site-type", "#site-region", "#site-status"].forEach((sel) => $(sel).addEventListener("change", renderSites));
$("#site-search").addEventListener("input", renderSites);
$("#site-add").addEventListener("click", () => siteEdit());
$("#site-fields").addEventListener("click", siteFieldsDialog);
$("#site-columns").addEventListener("click", () => chooseColumns(siteDialog, siteClose, siteAllColumns(), siteColumns().map((c) => c.key),
  (keys) => { saveLocal(siteColsKey(), keys); renderSites(); }, () => { saveLocal(siteColsKey(), null); renderSites(); }));
$("#site-template").addEventListener("click", () => templateDialog(siteDialog, "/api/sites",
  siteColumns().map((c) => c.key).filter((k) => !k.startsWith("#")),
  "Fill it in (one row per site) and bring it in with Import. Name is always in it. Rows are matched by site code, then name; you see what changes before anything is changed."));
$("#site-import").addEventListener("click", () => importDialog(siteDialog, siteClose, "/api/sites",
  "Excel (.xlsx) or CSV, column names in the first row (the same names as in an export or a Blank template). Rows are matched to the list by site code, then name; " +
  "anything not matched is added. Empty cells leave a value as it is. Nothing changes until you press Import.", loadSites));

// ---------- one site: buildings, floors, rooms and rack elevations ----------

const sp = { siteId: null, locId: null, layout: null, data: null, focusRack: null };
const KIND_LABEL = { building: "Building", floor: "Floor", room: "Room" };

async function openSitePage(siteId, locId = null, focusRack = null) {
  Object.assign(sp, { siteId, locId, focusRack });
  $("#sites-list").hidden = true;
  $("#site-page").hidden = false;
  await refreshSitePage();
}

async function refreshSitePage() {
  try {
    const q = new URLSearchParams({ site_id: sp.siteId });
    if (sp.locId) q.set("location_id", sp.locId);
    [sp.layout, sp.data] = await Promise.all([api(`/api/sites/${sp.siteId}/layout`), api(`/api/racks?${q}`)]);
  } catch (e) {
    if (sp.locId) { sp.locId = null; return refreshSitePage(); } // the place was deleted
    return toast(e.message);
  }
  renderSiteTree();
  renderSiteMain();
  if (sp.focusRack) {
    const el = document.getElementById(`rack-${sp.focusRack}`);
    if (el) { el.scrollIntoView({ block: "nearest" }); el.classList.add("focus"); }
    sp.focusRack = null;
  }
}

function spGo(locId) {
  sp.locId = locId;
  refreshSitePage();
}

function renderSiteTree() {
  const manage = can("inventory", "manage");
  const L = sp.layout;
  const addChild = async (kind, parentId) => {
    const name = prompt(`Name of the new ${kind}`);
    if (!name) return;
    try {
      const r = await api(`/api/sites/${sp.siteId}/locations`, { method: "POST", body: { kind, name, parent_id: parentId } });
      sp.locId = r.id;
      refreshSitePage();
    } catch (e) { toast(e.message); }
  };
  const node = (n) => {
    const tools = !manage ? null : h("span", { class: "tools" },
      n.kind === "building" ? h("button", { class: "small", title: "Add a floor", onclick: (ev) => { ev.stopPropagation(); addChild("floor", n.id); } }, "+ floor") : null,
      n.kind !== "room" ? h("button", { class: "small", title: "Add a room", onclick: (ev) => { ev.stopPropagation(); addChild("room", n.id); } }, "+ room") : null,
      h("button", { class: "small", title: "Rename", onclick: async (ev) => {
        ev.stopPropagation();
        const name = prompt(`New name for ${n.name} (items there get the new name too)`, n.name);
        if (!name) return;
        try {
          const r = await api(`/api/locations/${n.id}`, { method: "PUT", body: { name, notes: n.notes } });
          toast(r.renamed_on ? `Renamed; changed on ${r.renamed_on} item(s)` : "Renamed");
          refreshSitePage();
        } catch (e) { toast(e.message); }
      } }, "✎"),
      h("button", { class: "small danger", title: "Delete", onclick: async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Delete ${n.name} and everything in it from the layout? Items keep their Building, Floor and Room values.`)) return;
        try { await api(`/api/locations/${n.id}`, { method: "DELETE" }); refreshSitePage(); } catch (e) { toast(e.message); }
      } }, "✕"));
    return h("li", {},
      h("div", { class: `tree-node${sp.locId === n.id ? " selected" : ""}`, onclick: () => spGo(n.id) },
        h("span", {}, n.name), h("span", { class: "kind muted" }, ` ${KIND_LABEL[n.kind]} · ${n.items}${n.racks ? ` · ${n.racks} rack${n.racks > 1 ? "s" : ""}` : ""}`), tools),
      n.children.length ? h("ul", {}, ...n.children.map(node)) : null);
  };
  $("#sp-tree").replaceChildren(
    h("ul", {}, h("li", {},
      h("div", { class: `tree-node${sp.locId ? "" : " selected"}`, onclick: () => spGo(null) }, h("b", {}, L.site.name),
        manage ? h("span", { class: "tools" }, h("button", { class: "small", onclick: (ev) => { ev.stopPropagation(); addChild("building", null); } }, "+ building")) : null),
      L.tree.length ? h("ul", {}, ...L.tree.map(node)) : h("p", { class: "muted" }, manage ? "No buildings yet: + building." : "No buildings yet."))),
    L.not_placed ? h("p", { class: "muted" }, `${L.not_placed} item(s) at the site aren't in a building yet.`) : "",
    L.missing.length ? h("div", { class: "notice" },
      h("span", {}, "Used by items but not in the layout: " + L.missing.map((m) => `${m.path.join(" / ")} (${m.items})`).join(", ")),
      manage ? h("button", { class: "small", onclick: async () => {
        try {
          const r = await api(`/api/sites/${sp.siteId}/layout/from-inventory`, { method: "POST" });
          toast(`Added ${r.added.length}`);
          refreshSitePage();
        } catch (e) { toast(e.message); }
      } }, "Add them") : null) : "");
  const path = sp.data.path || [];
  $("#sp-crumbs").replaceChildren(
    h("span", { class: "link", onclick: () => switchView("sites") }, "Sites"), h("span", { class: "sep" }, "›"),
    h("span", { class: "link", onclick: () => spGo(null) }, L.site.name),
    ...path.flatMap((p) => [h("span", { class: "sep" }, "›"), h("span", { class: "link", onclick: () => spGo(p.id) }, p.name)]));
}

function renderSiteMain() {
  const manage = can("inventory", "manage");
  const d = sp.data;
  const here = d.path.length ? d.path[d.path.length - 1] : null;
  const parts = [];
  parts.push(h("h2", {}, here ? `${KIND_LABEL[here.kind]}: ${here.name}` : `${sp.layout.site.name}: every rack`));
  if (manage && here) {
    parts.push(h("div", { class: "toolbar no-print" },
      h("button", { onclick: () => spAddRack(here) }, "+ Add a rack here"),
      d.unknown_racks.length ? h("span", { class: "muted" }, `Racks named on items but not in the inventory: ${d.unknown_racks.join(", ")}`) : null,
      ...d.unknown_racks.slice(0, 5).map((name) => h("button", { class: "small", onclick: () => spAddRack(here, name) }, `Add ${name}`))));
  } else if (d.unknown_racks.length) {
    parts.push(h("p", { class: "muted" }, `Racks named on items but not in the inventory: ${d.unknown_racks.join(", ")}`));
  }
  if (!d.racks.length) {
    parts.push(h("p", { class: "muted" }, here ? "No racks here yet. A rack is an inventory item of type rack; its items name it in their Rack column." :
      "No racks at this site yet. Pick a room on the left and add one."));
  }
  parts.push(h("div", { class: "racks" }, ...d.racks.map((r) => rackCard(r, manage))));
  if (d.racks.length) {
    parts.push(h("p", { class: "muted rack-key" }, "Key: red, backup failing · orange edge, firmware behind · grey edge, inventory only (not managed) · " +
      "dashed, a full-depth item seen from the other side." + (manage ? " Drag an item to move it; click it to open it." : " Click an item to open it.")));
  }
  if (here) {
    const loose = h("div", { class: "loose-items" },
      h("h3", {}, `Here, not in a rack (${d.items.length})`),
      manage && d.racks.length ? h("p", { class: "muted no-print" }, "Drag an item onto a rack to put it in; drag it back here to take it out.") : null,
      d.items.length ? h("div", { class: "rack-tray" }, ...d.items.map((i) => rackBlock(i, manage, null))) : h("p", { class: "muted" }, "Nothing."));
    if (manage) dropTarget(loose, (id) => spMove(id, null, null, "front"));
    parts.push(loose);
  }
  $("#sp-main").replaceChildren(...parts);
}

async function spAddRack(here, name = null) {
  name = name || prompt("Name of the rack (e.g. HQ-R03)");
  if (!name) return;
  const u = Number(prompt("Height in U", "42")) || 42;
  const values = { name, type: "rack", rack_units: u, site: sp.layout.site.name };
  for (const p of sp.data.path) values[p.kind] = p.name;
  try {
    await api("/api/inventory/assets", { method: "POST", body: { values } });
    toast(`Added ${name}`);
    refreshSitePage();
  } catch (e) { toast(e.message); }
}

function rackBlockClass(i) {
  return ["rack-item", i.backup === "failed" ? "failed" : "", i.compliance === "behind" ? "behind" : "", i.managed ? "" : "inventory"].join(" ");
}

/** One item as a block: click to open it, drag to move it. */
function rackBlock(i, manage, extra = "") {
  const tip = [i.name, i.model, i.type, i.position ? `U${i.position}${i.height > 1 ? `-U${i.position + i.height - 1}` : ""}` : "",
    i.depth === "half" ? "half depth" : "", i.backup === "failed" ? "backup failing" : "", i.compliance === "behind" ? "firmware behind" : ""]
    .filter(Boolean).join(" · ");
  return h("div", { class: `${rackBlockClass(i)} ${extra || ""}`, title: tip, draggable: manage && extra !== "other-side" ? "true" : null,
    ondragstart: (ev) => {
      // Where in the item it was picked up (U from its bottom), so it lands where it is dropped
      const box = ev.currentTarget.getBoundingClientRect();
      const fromTop = Math.floor((ev.clientY - box.top) / U_PX);
      const grab = i.position ? Math.max(0, Math.min((i.height || 1) - 1, (i.height || 1) - 1 - fromTop)) : 0;
      ev.dataTransfer.setData("text/plain", JSON.stringify({ id: i.id, grab }));
      ev.dataTransfer.effectAllowed = "move";
    },
    onclick: () => spOpenItem(i.id) },
  h("b", {}, i.name), i.height !== 1 || !i.position ? h("small", {}, [i.model, i.type].filter(Boolean).join(" · ")) : null);
}

const U_PX = 20; // the height of one U on screen (style.css .rack-face)

function dropTarget(el, onDrop) {
  el.addEventListener("dragover", (ev) => { ev.preventDefault(); el.classList.add("drop-ok"); });
  el.addEventListener("dragleave", () => el.classList.remove("drop-ok"));
  el.addEventListener("drop", (ev) => {
    ev.preventDefault();
    el.classList.remove("drop-ok");
    let data = null;
    try { data = JSON.parse(ev.dataTransfer.getData("text/plain")); } catch { return; }
    if (data && data.id) onDrop(data.id, ev, data.grab || 0);
  });
}

/** A rack: front and rear, U1 at the bottom, 0U items on the side, unplaced items below. */
function rackCard(r, manage) {
  const face = (side) => {
    const grid = h("div", { class: "rack-face" });
    for (let u = r.height; u >= 1; u--) {
      const row = r.height - u + 1;
      const num = h("div", { class: "u-num" }, u);
      num.style.gridRow = String(row);
      const slot = h("div", { class: "u-slot", title: `U${u}` });
      slot.style.gridRow = String(row);
      grid.append(num, slot);
    }
    for (const i of r.items) {
      if (i.depth === "half" && i.face !== side) continue; // a half-depth item is on one face only
      const behind = i.depth !== "half" && i.face !== side;
      const top = i.position + i.height - 1;
      if (i.position < 1 || top > r.height) continue; // listed in the problems
      const el = rackBlock(i, manage, behind ? "other-side" : "");
      el.style.gridRow = `${r.height - top + 1} / span ${i.height}`;
      grid.append(el);
    }
    // Drop anywhere on the face: the U under the pointer is where the picked-up part lands.
    if (manage) dropTarget(grid, (id, ev, grab) => {
      const box = grid.getBoundingClientRect();
      const u = r.height - Math.floor((ev.clientY - box.top - 2) / U_PX);
      spMove(id, r.id, Math.max(1, Math.min(r.height, u) - grab), side);
    });
    return h("div", {}, h("div", { class: "rack-face-title" }, side === "front" ? "Front" : "Rear"), grid);
  };
  const tray = h("div", { class: "rack-tray" },
    r.unplaced.length ? r.unplaced.map((i) => rackBlock(i, manage)) : h("span", { class: "muted" }, "In the rack, no position: none"));
  if (manage) dropTarget(tray, (id) => spMove(id, r.id, null, "front"));
  return h("div", { class: "rack", id: `rack-${r.id}` },
    h("h3", {}, h("span", { class: "link", title: "Open the rack in the inventory", onclick: () => spOpenItem(r.id) }, r.name)),
    h("p", { class: "muted" }, `${r.path.map((p) => p.name).join(" / ") || "Not in a room"} · ${r.height}U · ${r.used_u}U used, ${r.free_u}U free`),
    r.problems.length ? h("ul", { class: "errtext" }, ...r.problems.map((p) => h("li", {}, p))) : null,
    h("div", { class: "rack-faces" }, face("front"), face("rear"),
      r.zero_u.length ? h("div", { class: "rack-side" }, h("div", { class: "rack-face-title" }, "0U"), ...r.zero_u.map((i) => rackBlock(i, manage))) : null),
    h("div", { class: "muted" }, "In the rack, not placed:"), tray);
}

async function spMove(assetId, rackId, position, face) {
  try {
    await api("/api/racks/move", { method: "POST", body: { asset_id: assetId, rack_id: rackId, position, face } });
    refreshSitePage();
  } catch (e) { toast(e.message); }
}

/** Open an item's form over the site page; the page refreshes after a change. */
async function spOpenItem(id) {
  try {
    if (!inv.meta) inv.meta = await api("/api/inventory/meta");
    inv.rows = await api("/api/inventory/assets");
    const r = inv.rows.find((x) => x.id === id);
    if (r) invEdit(r, refreshSitePage);
  } catch (e) { toast(e.message); }
}

$("#sp-back").addEventListener("click", () => switchView("sites"));
$("#sp-print").addEventListener("click", () => window.print());
$("#sp-details").addEventListener("click", async () => {
  await site.loading;
  const r = site.data.sites.find((x) => x.id === sp.siteId);
  if (r) siteEdit(r);
});
