// The wall display. The link is  https://<server>:<port>/display/#key=<key>[&rotate=20]
// The key stays in the #fragment, so it never reaches the web server's logs; it is sent
// in the Authorization header. Two pages take turns: the overview and the upgrades.
"use strict";

const params = new URLSearchParams(location.hash.slice(1));
const KEY = params.get("key") || "";
const ROTATE = Math.max(5, Number(params.get("rotate")) || 20) * 1000;
const REFRESH = 30000;
const STALE_AFTER = 2 * 60000;

const $ = (sel) => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "width") el.style.width = v; // (the page's CSP forbids style="" attributes)
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c !== null && c !== undefined && c !== false && c !== "") el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

/** The server sends UTC times without a zone. */
const when = (iso) => (iso ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z") : null);
const hhmm = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function ago(iso) {
  const d = when(iso);
  if (!d) return "never worked";
  const mins = Math.max(0, Math.round((Date.now() - d) / 60000));
  if (mins < 60) return `${mins} min`;
  const hours = Math.round(mins / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

const state = { data: null, lastOk: 0, page: 0, error: "" };

// ---------- page 1: overview ----------

function tile(label, num, sub, level) {
  return h("div", { class: `tile ${level}` }, h("div", { class: "label" }, label),
    h("div", { class: "num" }, num), h("div", { class: "sub" }, sub));
}

function overview(d) {
  const b = d.backups, f = d.firmware, u = d.upgrades, s = d.server;
  const running = u.under_way.length;
  const stuck = u.under_way.filter((j) => ["failed", "needs_attention"].includes(j.status)).length;
  const serverOk = s.worker && s.licence.active;
  const tiles = h("div", { class: "tiles" },
    tile("Failing backups", b.failing,
      `${b.ok} OK · ${b.never} never backed up${b.disabled ? ` · ${b.disabled} off` : ""}`,
      b.failing ? "bad" : b.never ? "warn" : ""),
    tile("Firmware on standard", f.percent === null ? "–" : `${f.percent}%`,
      `${f.behind} behind · ${f.ahead} ahead · ${f.no_standard} no standard`,
      f.behind ? "warn" : ""),
    tile("Upgrades running", running,
      `${u.coming_up.length} coming up in the next 12 h${stuck ? ` · ${stuck} need attention` : ""}`,
      stuck ? "bad" : running ? "warn" : ""),
    tile("Server", serverOk ? "OK" : "Check",
      [s.worker ? "upgrade worker running" : "upgrade worker STOPPED", s.licence.message].join(" · "),
      serverOk ? (s.licence.days_left !== null && s.licence.days_left <= 30 ? "warn" : "") : "bad"));

  const attention = h("div", { class: "panel" }, h("h2", {}, "Needs attention"));
  if (!d.attention.length) {
    attention.append(h("div", { class: "empty" }, "All backups working"));
  } else {
    attention.append(h("ul", { class: "list" }, d.attention.map((a) => h("li", {},
      h("span", {}, h("span", { class: "what" }, a.device), a.site ? h("span", { class: "dim" }, ` · ${a.site}`) : ""),
      h("span", { class: "why" }, `${a.reason} · ${ago(a.since)}`)))));
    if (d.attention_more) attention.append(h("div", { class: "more" }, `and ${d.attention_more} more`));
  }

  const sites = h("div", { class: "panel" }, h("h2", {}, "Sites"), h("div", { class: "sites" }, d.sites.map((x) => {
    const level = x.failing ? "bad" : x.upgrading ? "info" : x.behind ? "warn" : "";
    const notes = [x.failing && `${x.failing} failing`, x.upgrading && `${x.upgrading} upgrading`,
      x.behind && `${x.behind} behind`].filter(Boolean);
    return h("div", { class: `site ${level}` }, h("div", { class: "name" }, x.site),
      h("div", { class: "sub" }, notes.length ? notes.join(" · ") : `${x.devices} devices OK`));
  })));
  return [tiles, h("div", { class: "columns" }, attention, sites)];
}

// ---------- page 2: upgrades ----------

const STATUS = { pre_checking: "Pre-checks", staging: "Copying the image", running: "Running",
  post_checking: "Post-checks", paused: "Paused", failed: "Failed", rolling_back: "Rolling back",
  needs_attention: "Needs attention", ready: "Ready", blocked: "Blocked", planned: "Planned" };

function jobCard(j) {
  const level = ["failed", "needs_attention"].includes(j.status) ? "bad" : j.status === "paused" ? "warn" : "";
  const pct = j.steps ? Math.round((100 * Math.min(j.step, j.steps)) / j.steps) : 0;
  const end = when(j.planned_end);
  const c = j.circuits || { count: 0, groups: [] };
  return h("div", { class: `job ${level}` },
    h("div", { class: "head" }, h("span", { class: "dev" }, j.devices.join(" + ")),
      h("span", { class: `badge ${j.live ? "live" : ""}` }, j.live ? "LIVE" : "DRY RUN")),
    h("div", { class: "dim" }, [j.site, j.platform, j.change_ref].filter(Boolean).join(" · ")),
    h("div", { class: "ver" }, `${j.from_version || "?"} → ${j.target_version}`),
    h("div", { class: "step" }, `${STATUS[j.status] || j.status}${j.step_label ? `: ${j.step_label}` : ""}`),
    h("div", { class: "bar" }, h("span", { width: `${pct}%` })),
    h("div", { class: "dim" }, `Step ${Math.min(j.step + 1, j.steps)} of ${j.steps}${end ? ` · window ends ${hhmm(end)}` : ""}`),
    h("div", { class: "circuits" }, h("b", {}, `${c.count} circuit${c.count === 1 ? "" : "s"} affected`),
      c.groups.length ? h("ul", {}, c.groups.slice(0, 5).map((g) => h("li", {}, `${g.service} · VLAN ${g.vlan} · ${g.count}`)),
        c.groups.length > 5 ? h("li", {}, `${c.groups.length - 5} more services`) : "") : ""));
}

function upgrades(d) {
  const u = d.upgrades;
  const out = [];
  out.push(u.under_way.length ? h("div", { class: "jobs" }, u.under_way.map(jobCard))
    : h("div", { class: "panel" }, h("div", { class: "empty" }, "No upgrades running")));
  const planned = h("div", { class: "panel planned" }, h("h2", {}, "Coming up (next 12 hours)"));
  planned.append(u.coming_up.length ? h("ul", { class: "list" }, u.coming_up.map((j) => h("li", {},
    h("span", {}, h("span", { class: "what" }, j.devices.join(" + ")),
      h("span", { class: "dim" }, ` · ${j.site || "-"} · ${j.from_version || "?"} → ${j.target_version}${j.live ? "" : " (dry run)"}`)),
    h("span", {}, [when(j.planned_start), when(j.planned_end)].filter(Boolean).map(hhmm).join("–")))))
    : h("div", { class: "dim" }, "No other upgrades planned"));
  out.push(planned);
  return out;
}

// ---------- drawing, rotation, refresh ----------

const PAGES = [["Overview", "#page-overview", overview], ["Upgrades", "#page-upgrades", upgrades]];

function pagesToShow(d) {
  // Skip the upgrades page when there is nothing on it.
  return d && (d.upgrades.under_way.length || d.upgrades.coming_up.length) ? [0, 1] : [0];
}

function draw() {
  const d = state.data;
  const stale = $("#stale");
  const old = !state.lastOk || Date.now() - state.lastOk > STALE_AFTER;
  stale.hidden = !old;
  if (old) {
    stale.textContent = state.lastOk
      ? `No data since ${hhmm(new Date(state.lastOk))}: ${state.error || "the server can't be reached"}`
      : state.error || "Waiting for data…";
  }
  if (!d) return;
  $("#product").textContent = d.product_name;
  $("#site").textContent = d.site_name ? `· ${d.site_name}` : "";
  document.title = d.site_name ? `${d.product_name} · ${d.site_name}` : d.product_name;
  $("#updated").textContent = `Updated ${hhmm(when(d.generated_at))}`;
  $("#screen").textContent = d.screen;
  const show = pagesToShow(d);
  if (!show.includes(state.page)) state.page = show[0];
  PAGES.forEach(([name, sel, render], i) => {
    const el = $(sel);
    el.hidden = i !== state.page;
    if (i === state.page) {
      el.replaceChildren(...render(d));
      $("#page-name").textContent = name;
    }
  });
  $("#dots").replaceChildren(...show.map((i) => h("span", { class: i === state.page ? "on" : "" })));
}

async function refresh() {
  if (!KEY) {
    state.error = "This link has no display key: copy the whole link from the Settings page";
    draw();
    return;
  }
  try {
    const res = await fetch("/api/display/data", { headers: { Authorization: `Bearer ${KEY}` }, cache: "no-store" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `the server answered ${res.status}`);
    }
    state.data = await res.json();
    state.lastOk = Date.now();
    state.error = "";
  } catch (e) {
    state.error = e.message;
  }
  draw();
}

function rotate() {
  const show = pagesToShow(state.data);
  state.page = show[(show.indexOf(state.page) + 1) % show.length];
  draw();
}

function tick() {
  $("#clock").textContent = hhmm(new Date());
}

tick();
refresh();
setInterval(tick, 1000);
setInterval(refresh, REFRESH);
setInterval(rotate, ROTATE);
setInterval(draw, 30000); // keep the stale warning honest even if a request hangs
