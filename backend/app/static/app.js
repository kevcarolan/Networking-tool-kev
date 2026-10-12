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
const VIEW_MODULE = { firmware: "firmware", circuits: "circuits", syslog: "syslog" };

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
  $("#site-name").textContent = user.site_name || "";
  $("#site-name").hidden = !user.site_name;
  $("#demo-banner").hidden = !user.demo;
  $$("[data-admin]").forEach((el) => (el.hidden = !isAdmin()));
  $$("[data-upgrader]").forEach((el) => (el.hidden = !canUpgrade()));
  $$("[data-perm]").forEach((el) => (el.hidden = !permitted(el.dataset.perm)));
  state.platforms = await api("/api/platforms");
  state.licence = await api("/api/licence").catch(() => null);
  applyModules();
  showLicenceBanner();
  const first = $$("#nav button").find((b) => !b.hidden && !b.classList.contains("locked"));
  if (first) switchView(first.dataset.view);
  clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    if (document.hidden) return;
    if (state.view === "backups") loadBackups();
    else if (state.view === "firmware" && fw.tab === "versions") loadFwVersions();
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
    await showApp(user);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
});

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
  ({ backups: loadBackups, inventory: loadInventory, sites: loadSites, firmware: loadFirmware, circuits: loadCircuits, syslog: loadSyslog, credentials: loadCredentials,
    audit: loadAudit, users: loadUsers, settings: loadSettings })[view]();
}
$$("#nav button").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));

// ---------- config backups ----------

function effectiveStatus(row) {
  if (row.backup.busy) return "running";
  if (!row.device.enabled || !row.backup.enabled) return "disabled";
  return row.backup.status;
}

const STATUS_LABEL = { success: "OK", failed: "Failed", running: "Running", never: "Never", disabled: "Disabled" };

async function loadBackups() {
  try {
    const [rows, summary] = await Promise.all([api("/api/backup/devices"), api("/api/backup/summary")]);
    state.rows = rows;
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
  const actions = [];
  if (hasModule("backups")) actions.push(h("button", { class: "small", onclick: () => openDetail(r) }, "History"));
  if (can("backups", "run") && hasModule("backups")) {
    actions.push(h("button", { class: "small", disabled: b.busy, onclick: () => runNow(d) }, "Backup now"));
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
    h("td", {}, d.site || "—"),
    h("td", {}, d.platform_label),
    h("td", {}, fmtFreq(b.frequency_minutes)),
    h("td", { title: fmtTime(b.last_success) }, fmtAgo(b.last_success)),
    h("td", { title: fmtTime(b.last_change) }, b.last_change ? fmtAgo(b.last_change) : "—"),
    h("td", { class: "result" }, result),
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
    form.backup_enabled.checked = row.backup.enabled;
    const freq = String(row.backup.frequency_minutes);
    if (![...form.frequency_minutes.options].some((o) => o.value === freq)) {
      form.frequency_minutes.append(h("option", { value: freq }, fmtFreq(row.backup.frequency_minutes)));
    }
    form.frequency_minutes.value = freq;
  } else if (state.credentials.length === 1) {
    form.credential_id.value = state.credentials[0].id;
  }
  // Where a device account's password is sent is a separate permission.
  const where = can("inventory", "addresses");
  form.address.disabled = form.credential_id.disabled = !where;
  form.address.title = form.credential_id.title = where ? "" :
    "Changing the address or credential profile needs the 'addresses' level for Devices and credentials";
  dlg.dataset.deviceId = row ? row.device.id : "";
  showSshKey(row);
  dlg.showModal();
}

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
    credential_id: form.credential_id.value ? Number(form.credential_id.value) : null,
  };
  try {
    const device = await api(id ? `/api/devices/${id}` : "/api/devices", { method: id ? "PUT" : "POST", body });
    await api(`/api/backup/devices/${device.id}/settings`, {
      method: "PUT",
      body: { frequency_minutes: Number(form.frequency_minutes.value), enabled: form.backup_enabled.checked },
    });
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
  $("#detail-title").textContent = `${row.device.name} — ${row.device.address}`;
  $("#detail-text").hidden = true;
  selectDetailTab("runs");
  $("#detail-dialog").showModal();
}

function selectDetailTab(tab) {
  $$("#detail-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("#detail-runs").hidden = tab !== "runs";
  $("#detail-versions").hidden = tab !== "versions";
  $("#detail-circuits").hidden = tab !== "circuits";
  $("#detail-upgrades").hidden = tab !== "upgrades";
  $("#detail-text").hidden = true;
  ({ runs: loadRuns, versions: loadVersions, circuits: loadDeviceCircuits, upgrades: loadDeviceUpgrades })[tab]();
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
    h("td", {}, d.site || "—"),
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

const ct = { rows: [], imp: null, pending: null, meta: null };
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
const CT_DEFAULT = ["@service", "@device", "@type", "mac", "@location", "@ip", "@vlan", "@switch", "@live", "@drawing"];

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
    ? `Network last read ${fmtTime(full.finished_at)} (${full.trigger.startsWith("schedule") ? "weekly scan" : full.trigger.replace("manual:", "by ")}): ` +
      `${full.devices_ok} device(s) read` + (full.devices_failed ? `, ${full.devices_failed} failed` : "") + "."
    : "The network hasn't been scanned yet: the weekly scan or Scan network now fills in where each circuit is.";
  $("#ct-scan-info").title = full && full.errors ? full.errors : "";
  const uniq = (key) => [...new Set(rows.map((r) => r[key]).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  fillSelect($("#ct-filter-service"), "All services", uniq("service").map((x) => [x, x]));
  fillSelect($("#ct-filter-switch"), "All switches", uniq("switch").map((x) => [x, x]));
  fillSelect($("#ct-filter-vlan"), "All VLANs", uniq("vlan").map((x) => [x, `VLAN ${x}`]));
  renderCircuits();
}

function renderCircuits() {
  const q = $("#ct-search").value.trim().toLowerCase();
  const service = $("#ct-filter-service").value, sw = $("#ct-filter-switch").value;
  const vlan = $("#ct-filter-vlan").value, match = $("#ct-filter-match").value;
  const rows = ct.rows.filter((r) => {
    if (service && r.service !== service) return false;
    if (sw && r.switch !== sw) return false;
    if (vlan && r.vlan !== vlan) return false;
    if (match === "matched" && r.match !== "matched") return false;
    if (match === "unlinked" && r.match === "matched") return false;
    if (match === "warnings" && !r.warnings) return false;
    if (match.startsWith("live:") && r.live_status !== match.slice(5)) return false;
    if (q && ![r.device_name, r.eng_prefix, r.ip, r.mac, r.port, r.switch, r.drawing_number, r.drawing_ref,
      r.room, r.device_type, r.live_switch, r.live_port, r.live_mac,
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
  ["#ct-search", "#ct-filter-service", "#ct-filter-switch", "#ct-filter-vlan", "#ct-filter-match"]
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
});
$("#ct-upload-close").addEventListener("click", () => $("#ct-upload-dialog").close());

$("#ct-upload-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, err = $(".error", form), file = form.file.files[0];
  const btn = $("button", form);
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const res = await fetch(`/api/circuits/imports/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "PUT", credentials: "same-origin", body: file, headers: { "Content-Type": "application/octet-stream" },
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) return showLogin();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    ct.pending = data;
    form.hidden = true;
    renderPreview(data);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Check file";
  }
});

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
    h("td", {}, SOURCE_LABEL[u.source] || u.source),
    h("td", {}, u.is_admin ? h("span", { class: "badge success" }, "Administrator") : permChips(u.permissions)),
    h("td", {}, u.last_login ? fmtTime(u.last_login) : "never"),
    h("td", {}, fmtTime(u.updated_at), h("small", { class: "sub" }, u.updated_by)),
    h("td", { class: "actions" },
      h("button", { class: "small", onclick: () => openUserDialog(u) }, "Edit"),
      u.source === "local" ? h("button", { class: "small", onclick: () => openPasswordDialog(u) }, "Reset password") : null,
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
      h("dt", {}, "Devices"), h("dd", {}, s.max_devices == null ? `${s.devices} (no limit)` : `${s.devices} of ${s.max_devices}`),
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
  const { port, screens } = await api("/api/displays");
  const err = errorLine();
  const name = h("input", { name: "display_name", placeholder: "e.g. NOC wall 1", maxlength: 100 });
  const linkFor = (key) => `https://${location.hostname}:${port}/display/#key=${key}`;
  const shown = h("div", { hidden: true });
  const box = h("div", { class: "panel" });
  const rows = screens.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Screen"), h("th", {}, "Last connected"), h("th", {}, "From"), h("th", {}, ""))),
    h("tbody", {}, screens.map((s) => h("tr", {}, h("td", {}, s.name), h("td", {}, fmtTime(s.last_seen_at)),
      h("td", {}, s.last_seen_from || "—"),
      h("td", {}, h("button", { type: "button", class: "small", onclick: async () => {
        if (!confirm(`Remove "${s.name}"? Its link stops working straight away.`)) return;
        try { await api(`/api/displays/${s.id}`, { method: "DELETE" }); toast("Display removed"); loadSettings(); } catch (e) { showError(err, e); }
      } }, "Remove"))))))
    : h("p", { class: "muted" }, "No wall displays yet.");
  box.replaceChildren(
    h("h2", {}, "Wall displays"),
    h("p", { class: "muted" }, `A read-only status screen for a NOC or office wall: failing backups, firmware compliance and the upgrades under way. It is served on port ${port} only; open that port in the server's firewall just for the screens' network.`),
    rows,
    h("label", {}, "Add a display", name), err,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: async () => {
      err.hidden = true;
      try {
        const s = await api("/api/displays", { method: "POST", body: { name: name.value } });
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
      h("li", {}, "Upgrades: a job completes, fails, rolls back or needs attention."),
      h("li", {}, "Licence: 30 and 7 days before it ends, and when it has ended."),
      h("li", {}, "Upgrade worker: stopped for more than 10 minutes."),
      h("li", {}, "Syslog: device messages at the level below or worse, gathered into one email.")),
    text("backup_hours", "Backups: alert when failing for more than (hours)", { type: "number", min: 1, max: 720 }),
    h("label", {}, "Syslog: messages at", f.syslog_level),
    text("syslog_minutes", "Syslog: at most one email every (minutes)", { type: "number", min: 1, max: 60 }),
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
          syslog_minutes: Number(f.syslog_minutes.value),
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
      } }, "Send test email")),
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

function invEdit(r = null) {
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
      loadInventory();
    } catch (e) { showError(err, e); }
  };
  const buttons = h("div", { class: "dialog-actions" });
  if (r && !r.managed && inv.meta.can_add_devices) buttons.append(h("button", { type: "button", onclick: () => invManage(r) }, "Manage this device…"));
  if (r && !r.managed && canEdit) buttons.append(h("button", { type: "button", class: "danger", onclick: async () => {
    if (!confirm(`Delete ${invValue(r, "name")} from the inventory?`)) return;
    try { await api(`/api/inventory/assets/${r.id}`, { method: "DELETE" }); $("#inv-dialog").close(); loadInventory(); } catch (e) { showError(err, e); }
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

const site = { meta: null, data: { sites: [], unlisted: [] } };
const siteColsKey = () => `site-columns:${state.user ? state.user.username : ""}`;
const SITE_DEFAULT_COUNTS = ["#items", "#devices", "#backup_failed"];

function siteAllColumns() {
  return [...site.meta.fields, ...site.meta.counts.map((c) => ({ key: `#${c.key}`, label: c.label, group: "From the inventory" }))];
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

async function loadSites() {
  try {
    [site.meta, site.data] = await Promise.all([api("/api/sites/meta"), api("/api/sites")]);
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
    if (c.key === "name") return h("td", {}, h("span", { class: "link", onclick: () => siteEdit(r) }, r.values.name));
    if (c.key.startsWith("#")) {
      const n = r.counts[c.key.slice(1)];
      const cls = c.key === "#backup_failed" || c.key === "#behind" ? (n ? "badge failed" : "muted") : "count-link";
      return h("td", {}, h("span", { class: cls, onclick: () => siteEdit(r, true), title: "See what's at this site" }, n));
    }
    const v = r.values[c.key];
    return h("td", { class: ["address", "access", "circuits", "notes"].includes(c.key) ? "wrap" : "" }, String(v ?? ""));
  }))));
  $("#site-empty").hidden = rows.length > 0;
  $("#site-empty").textContent = site.data.sites.length ? "Nothing matches the filters." :
    "No sites yet. Add them with + Add site, import a spreadsheet (Blank template gives you one to fill in), or add the ones the inventory already uses.";
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
      loadSites();
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
  const parts = [h("h3", {}, `At this site (${r.counts.items})`), items];
  const details = [form, h("p", { class: "muted" }, "Renaming the site, or changing its code, changes the Site on the items and devices that use the old one."), buttons];
  siteDialog(r.values.name, ...(itemsFirst ? [...parts, ...details] : [...details, ...parts]));
  try {
    const list = await api(`/api/sites/${r.id}/items`);
    items.replaceChildren(list.length ? h("table", {},
      h("thead", {}, h("tr", {}, ["Name", "Type", "Model", "Address", "Where", "Status", "Tools"].map((t) => h("th", {}, t)))),
      h("tbody", {}, list.map((i) => h("tr", {},
        h("td", { class: "name" }, i.name), h("td", {}, i.type || "—"), h("td", {}, i.model || "—"),
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
