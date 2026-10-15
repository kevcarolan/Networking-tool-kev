// The wall display. The link is  https://<server>:<port>/display/#key=<key>[&rotate=20]
// The key stays in the #fragment, so it never reaches the web server's logs; it is sent
// in the Authorization header. The pages the screen was set up with take turns: the
// overview, monitoring (devices down), the upgrades, the sites and the network (syslog,
// config changes, circuits).
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
  const b = d.backups, f = d.firmware, u = d.upgrades, s = d.server, c = d.compliance, ch = d.changes;
  const running = u.under_way.length;
  const stuck = u.under_way.filter((j) => ["failed", "needs_attention"].includes(j.status)).length;
  const serverOk = s.worker && s.licence.active;
  const m = d.monitoring;
  const tiles = h("div", { class: "tiles" },
    m ? tile("Devices down", m.counts.down,
      `${m.counts.up} up · ${m.counts.warning} warning${m.counts.hardware ? ` · ${m.counts.hardware} hardware` : ""}${m.counts.maintenance ? ` · ${m.counts.maintenance} in maintenance` : ""}${m.meraki && m.meraki.counts.offline ? ` · ${m.meraki.counts.offline} Meraki offline` : ""}${m.running ? "" : " · NOT CHECKING"}`,
      m.down.some((x) => !x.maintenance) || !m.running ? "bad" : m.counts.warning || m.counts.down || (m.meraki && m.meraki.counts.offline) ? "warn" : "") : null,
    tile("Failing backups", b.failing,
      `${b.ok} OK · ${b.never} never backed up${b.disabled ? ` · ${b.disabled} off` : ""}`,
      b.failing ? "bad" : b.never ? "warn" : ""),
    c ? tile("Compliance", c.failing,
      c.rules ? `device${c.failing === 1 ? "" : "s"} failing a rule · ${c.critical} critical · ${c.checked} checked` : "no rules set",
      c.critical ? "bad" : c.failing ? "warn" : "") : null,
    ch ? tile("Config changes", ch.count, "in the last 24 hours", ch.count ? "info" : "") : null,
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

  const sites = h("div", { class: "panel" }, h("h2", {}, "Sites"), h("div", { class: "sites" }, d.sites.filter((x) => x.devices).map((x) => siteTile(x))));
  return [tiles, h("div", { class: "columns" }, attention, sites)];
}

function siteTile(x, big = false) {
  const level = x.down || x.failing ? "bad" : x.upgrading ? "info" : (x.behind || x.compliance || x.circuits) ? "warn" : "";
  const notes = [x.down && `${x.down} device${x.down > 1 ? "s" : ""} DOWN`, x.failing && `${x.failing} backup${x.failing > 1 ? "s" : ""} failing`, x.upgrading && `${x.upgrading} upgrading`,
    x.behind && `${x.behind} firmware behind`, x.compliance && `${x.compliance} failing compliance`,
    x.circuits && `${x.circuits} circuit${x.circuits > 1 ? "s" : ""} moved or missing`].filter(Boolean);
  return h("div", { class: `site ${level}${big ? " big" : ""}` }, h("div", { class: "name" }, x.site),
    h("div", { class: "sub" }, x.devices ? `${x.devices} device${x.devices > 1 ? "s" : ""}` : "no managed devices"),
    big ? h("ul", { class: "notes" }, (notes.length ? notes : ["All OK"]).map((n) => h("li", {}, n)))
      : h("div", { class: "sub" }, notes.length ? notes.join(" · ") : "OK"));
}

// ---------- page: monitoring ----------

function monitoringPage(d) {
  const m = d.monitoring, c = m.counts;
  const out = [h("div", { class: "sevs big" },
    h("div", { class: `sev ${c.down ? "s0" : "zero"}` }, h("div", { class: "num" }, c.down), h("div", { class: "sub" }, "down")),
    h("div", { class: `sev ${c.warning ? "s3" : "zero"}` }, h("div", { class: "num" }, c.warning), h("div", { class: "sub" }, "warning")),
    h("div", { class: "sev ok" }, h("div", { class: "num" }, c.up), h("div", { class: "sub" }, "up")),
    h("div", { class: `sev ${c.maintenance ? "info" : "zero"}` }, h("div", { class: "num" }, c.maintenance), h("div", { class: "sub" }, "in maintenance")))];
  if (!m.running) out.push(h("div", { class: "panel" }, h("div", { class: "empty bad-text" }, "The monitoring poller isn't running: what is shown may be old")));
  const row = (x, right, cls) => h("li", {},
    h("span", {}, h("span", { class: "what" }, x.device), x.site ? h("span", { class: "dim" }, ` · ${x.site}`) : "",
      x.maintenance ? h("span", { class: "badge" }, "maintenance") : ""),
    h("span", { class: cls }, right));
  const panels = [
    h("div", { class: "panel" }, h("h2", {}, `Down (${c.down})`),
      m.down.length ? h("ul", { class: "list" }, m.down.map((x) => row(x, `for ${ago(x.since)}`, x.maintenance ? "dim" : "why")))
        : h("div", { class: "empty" }, "Every device answering"),
      m.down_more ? h("div", { class: "more" }, `and ${m.down_more} more`) : ""),
    h("div", { class: "panel" }, h("h2", {}, `Warnings (${c.warning})`),
      m.warnings.length ? h("ul", { class: "list" }, m.warnings.map((x) => row(x, x.problem, "dim")))
        : h("div", { class: "empty" }, "None"),
      m.warnings_more ? h("div", { class: "more" }, `and ${m.warnings_more} more`) : ""),
    h("div", { class: "panel" }, h("h2", {}, "Last 24 hours"),
      m.events.length ? h("ul", { class: "list" }, m.events.map((e) => h("li", {},
        h("span", {}, h("span", { class: "what" }, e.device), h("span", { class: "dim" }, ` · ${e.label}`)),
        h("span", { class: e.kind === "down" && !e.maintenance ? "why" : "dim" }, hhmm(when(e.at))))))
        : h("div", { class: "empty" }, "Nothing went down or restarted"))];
  if (m.meraki) {
    const mc = m.meraki.counts;
    panels.push(h("div", { class: "panel" }, h("h2", {}, "Meraki"),
      h("div", { class: "sevs" },
        h("div", { class: `sev ${mc.offline ? "s0" : "zero"}` }, h("div", { class: "num" }, mc.offline), h("div", { class: "sub" }, "offline")),
        h("div", { class: `sev ${mc.alerting ? "s3" : "zero"}` }, h("div", { class: "num" }, mc.alerting), h("div", { class: "sub" }, "alerting")),
        h("div", { class: "sev ok" }, h("div", { class: "num" }, mc.online), h("div", { class: "sub" }, "online"))),
      m.meraki.problems.length ? h("ul", { class: "list" }, m.meraki.problems.map((x) => h("li", {},
        h("span", {}, h("span", { class: "what" }, x.device), h("span", { class: "dim" }, ` · ${x.network}`)),
        h("span", { class: x.status === "offline" ? "why" : "warn-text" }, `${x.status}${x.since ? ` · ${ago(x.since)}` : ""}`))))
        : h("div", { class: "empty" }, "Every Meraki device online")));
  }
  if (m.hardware && m.hardware.length) {
    panels.push(h("div", { class: "panel" }, h("h2", {}, `Hardware (${m.counts.hardware})`),
      h("ul", { class: "list" }, m.hardware.map((x) => h("li", {},
        h("span", {}, h("span", { class: "what" }, x.device), x.site ? h("span", { class: "dim" }, ` · ${x.site}`) : ""),
        h("span", { class: x.critical ? "why" : "warn-text" }, x.problems.join("; ")))))));
  }
  if (m.busiest.length || m.port_errors.length) {
    panels.push(h("div", { class: "panel" }, h("h2", {}, "Busiest ports"),
      h("ul", { class: "list" }, m.busiest.map((p) => h("li", {},
        h("span", {}, h("span", { class: "what" }, p.device), h("span", { class: "dim" }, ` · ${p.port}`)),
        h("span", { class: p.util >= 0.8 ? "why" : p.util >= 0.5 ? "warn-text" : "dim" }, `${Math.round(p.util * 100)}%`)))),
      m.port_errors.length ? h("h2", { class: "sub-head" }, "Errors and discards") : "",
      m.port_errors.length ? h("ul", { class: "list" }, m.port_errors.map((p) => h("li", {},
        h("span", {}, h("span", { class: "what" }, p.device), h("span", { class: "dim" }, ` · ${p.port}`)),
        h("span", { class: p.errors ? "why" : "warn-text" }, [p.errors ? `${Math.round(p.errors)} errors` : "", p.discards ? `${Math.round(p.discards)} discards` : ""].filter(Boolean).join(" · ") + "/min")))) : ""));
  }
  out.push(h("div", { class: "network" }, panels));
  return out;
}

// ---------- page 3: sites ----------

function sitesPage(d) {
  return [h("div", { class: "sites big-grid" }, d.sites.map((x) => siteTile(x, true)))];
}

// ---------- page 4: network (syslog, config changes, circuits) ----------

const SEV = ["Emergency", "Alert", "Critical", "Error"];

function networkPage(d) {
  const panels = [];
  if (d.syslog) {
    const sl = d.syslog;
    panels.push(h("div", { class: "panel" }, h("h2", {}, "Syslog: errors and worse, last 24 h"),
      h("div", { class: "sevs" }, sl.counts.map((n, i) => h("div", { class: `sev s${i}${n ? "" : " zero"}` }, h("div", { class: "num" }, n), h("div", { class: "sub" }, SEV[i])))),
      sl.latest.length ? h("ul", { class: "list" }, sl.latest.map((m) => h("li", {},
        h("span", {}, h("span", { class: "what" }, m.device), h("span", { class: "dim" }, ` · ${m.type || m.severity}`)),
        h("span", { class: m.sev <= 2 ? "why" : "dim" }, `${m.severity} · ${hhmm(when(m.at))}`))))
        : h("div", { class: "empty" }, "No errors")));
  }
  if (d.changes) {
    panels.push(h("div", { class: "panel" }, h("h2", {}, `Config changes, last 24 h (${d.changes.count})`),
      d.changes.rows.length ? h("ul", { class: "list" }, d.changes.rows.map((r) => h("li", {},
        h("span", {}, h("span", { class: "what" }, r.device), r.site ? h("span", { class: "dim" }, ` · ${r.site}`) : ""),
        h("span", { class: "dim" }, hhmm(when(r.at))))))
        : h("div", { class: "empty" }, "No changes")));
  }
  if (d.circuits) {
    const c = d.circuits;
    panels.push(h("div", { class: "panel" }, h("h2", {}, `Circuits (${c.total})`),
      h("div", { class: "sevs" },
        h("div", { class: "sev ok" }, h("div", { class: "num" }, c.matches), h("div", { class: "sub" }, "where listed")),
        h("div", { class: `sev ${c.moved ? "s3" : "zero"}` }, h("div", { class: "num" }, c.moved), h("div", { class: "sub" }, "moved")),
        h("div", { class: `sev ${c.not_seen ? "s2" : "zero"}` }, h("div", { class: "num" }, c.not_seen), h("div", { class: "sub" }, "not seen"))),
      c.problems.length ? h("ul", { class: "list" }, c.problems.map((p) => h("li", {},
        h("span", {}, h("span", { class: "what" }, p.name), h("span", { class: "dim" }, [p.service, p.site].filter(Boolean).map((x) => ` · ${x}`).join(""))),
        h("span", { class: "why" }, p.status))))
        : h("div", { class: "empty" }, "Every circuit where it should be"),
      c.problems_more ? h("div", { class: "more" }, `and ${c.problems_more} more`) : ""));
  }
  return [h("div", { class: "network" }, panels)];
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

const PAGES = [["overview", "Overview", "#page-overview", overview], ["monitoring", "Monitoring", "#page-monitoring", monitoringPage],
  ["upgrades", "Upgrades", "#page-upgrades", upgrades],
  ["sites", "Sites", "#page-sites", sitesPage], ["network", "Network", "#page-network", networkPage]];

function pagesToShow(d) {
  if (!d) return [0];
  const chosen = d.pages && d.pages.length ? d.pages : PAGES.map((p) => p[0]);
  const show = PAGES.map((p, i) => [p[0], i]).filter(([key]) => {
    if (!chosen.includes(key)) return false;
    if (key === "upgrades") return d.upgrades.under_way.length || d.upgrades.coming_up.length; // nothing on it
    if (key === "network") return d.syslog || d.changes || d.circuits;
    if (key === "monitoring") return d.monitoring && (d.monitoring.monitored || d.monitoring.meraki);
    return true;
  }).map(([, i]) => i);
  return show.length ? show : [0];
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
  PAGES.forEach(([, name, sel, render], i) => {
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
