// Shared helpers of all dashboard pages (P7.4): data loading, header, formatting, small
// DOM/chart builders. No framework, no CDN, no HTML strings: every value from the results goes
// through textContent, so a label such as "<b>" in a snapshot name stays text.

export const ROOT = document.body.dataset.root || ".";
export const THEME_KEY = "concho-theme";

// ------------------------------------------------------------------ data access

/** Value at a dotted path, or undefined when a part of it is missing (see paths.js). */
export function get(obj, path) {
  let cur = obj;
  for (const key of path.split(".")) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[key];
  }
  return cur;
}

export async function fetchJson(relPath) {
  const url = `${ROOT}/${relPath}`;
  let resp;
  try {
    resp = await fetch(url, { cache: "no-cache" });
  } catch (err) {
    throw new Error(`Could not load ${relPath}. Open the site through a web server ` +
      `(python -m http.server in the site folder), not as a local file. (${err.message})`);
  }
  if (!resp.ok) throw new Error(`Could not load ${relPath}: HTTP ${resp.status}`);
  return resp.json();
}

export async function loadIndex() {
  const idx = await fetchJson("results/index.json");
  idx.snapshots = idx.snapshots || [];
  return idx;
}

/** The selected snapshot: ?snapshot=<id>, else the latest one. */
export function pickSnapshot(idx, wanted = new URLSearchParams(location.search).get("snapshot")) {
  const byId = idx.snapshots.find((s) => s.id === wanted);
  return byId || idx.snapshots.find((s) => s.id === get(idx, "latest")) ||
    idx.snapshots[idx.snapshots.length - 1] || null;
}

export function snapshotsNewestFirst(idx) {
  return [...idx.snapshots].reverse();
}

// ------------------------------------------------------------------ formatting

const nf = (d) => new Intl.NumberFormat("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const nf0 = nf(0);
const isNum = (v) => typeof v === "number" && Number.isFinite(v);

export function usd(v, d = 0) {
  if (!isNum(v)) return "–";
  return (v < 0 ? "−$" : "$") + nf(d).format(Math.abs(v));
}
/** $1.2M / $340k, for chart axes. */
export function usdShort(v) {
  if (!isNum(v)) return "–";
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e6) return `${s}$${Number((a / 1e6).toPrecision(3))}M`;
  if (a >= 1e3) return `${s}$${Number((a / 1e3).toPrecision(3))}k`;
  return `${s}$${Math.round(a)}`;
}
export function num(v, d = 0) {
  if (!isNum(v)) return "–";
  return (v < 0 ? "−" : "") + nf(d).format(Math.abs(v));
}
/** Percent from a value that is already in percent (TVD delta_pct). */
export function pct(v, d = 1) {
  return isNum(v) ? `${v < 0 ? "−" : ""}${nf(d).format(Math.abs(v))} %` : "–";
}
/** Percent from a fraction (STV percent_of_target = project / target). */
export function frac(v, d = 1) {
  return isNum(v) ? pct(v * 100, d) : "–";
}
export function signedUsd(v) {
  return isNum(v) ? (v > 0 ? "+" : v < 0 ? "" : "") + usd(v) : "–";
}
/** Small values such as ozone depletion (kg CFC-11e): 3 significant digits. */
export function sig(v) {
  if (!isNum(v)) return "–";
  if (v === 0) return "0";
  return Math.abs(v) >= 1000 ? nf0.format(v) : Number(v.toPrecision(3)).toString();
}
export function when(ts) {
  return typeof ts === "string" && ts.length >= 16 ? ts.slice(0, 16).replace("T", " ") + " UTC" : (ts || "");
}

// ------------------------------------------------------------------ DOM builders

export function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

/** Replaces the children of `host`; null, undefined and false (absent blocks) are skipped, so
 * they never show up as the text "null". */
export function setContent(host, ...kids) {
  host.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
}

export function section(title, id, ...kids) {
  return el("section", { id }, el("h2", { text: title }), ...kids);
}

export function card(label, value, sub, valueClass) {
  return el("div", { class: "card" },
    el("span", { class: "k", text: label }),
    el("span", { class: `v ${valueClass || ""}`, text: value }),
    sub ? el("span", { class: "s", text: sub }) : null);
}

export function note(kind, title, ...kids) {
  return el("div", { class: `note ${kind}` }, el("b", { text: title }), ...kids);
}

export function details(title, open, ...kids) {
  return el("details", open ? { open: true } : {}, el("summary", { text: title }),
    el("div", { class: "body" }, ...kids));
}

export function badge(text, kind = "") {
  return el("span", { class: `badge ${kind}`, text });
}

/**
 * columns: [{label, num?, wrap?, value: row => string | Node}], rows: array,
 * options: {total: row-like object rendered as last bold row}
 */
export function table(columns, rows, options = {}) {
  const head = el("tr", {}, columns.map((c) => el("th", { class: c.num ? "num" : "", text: c.label })));
  const line = (row, cls) => el("tr", { class: cls || "" }, columns.map((c) =>
    el("td", { class: [c.num ? "num" : "", c.wrap ? "wrap" : ""].join(" ").trim() }, c.value(row))));
  const body = rows.map((r) => line(r));
  if (options.total) body.push(line(options.total, "total"));
  return el("div", { class: "scroll" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
}

export function kv(pairs) {
  return table([{ label: "", value: (p) => p[0] }, { label: "", num: true, value: (p) => p[1] }],
    pairs.filter((p) => p !== null));
}

/** Div bars. rows: [{label, text, est, tgt}], values in one unit; over target is red. */
export function barChart(rows, { estLabel = "Estimate", tgtLabel = "Target" } = {}) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.max(r.est || 0, r.tgt || 0)));
  const w = (v) => `${Math.min(100, Math.max(0, ((v || 0) / max) * 100)).toFixed(2)}%`;
  const list = rows.map((r) => el("div", { class: "bar-row" },
    el("div", { class: "lbl" }, el("span", { text: r.label }), el("span", { class: "muted", text: r.text })),
    el("div", { class: "track", role: "img", "aria-label": `${r.label}: ${estLabel} ${r.text}` },
      el("div", { class: `fill ${r.est > r.tgt ? "over" : ""}`, style: `width:${w(r.est)}` })),
    r.tgt === undefined ? null : el("div", { class: "track" },
      el("div", { class: "fill tgt", style: `width:${w(r.tgt)}` }))));
  const hasTarget = rows.some((r) => r.tgt !== undefined);
  return el("div", {}, el("div", { class: "legend" },
    el("span", {}, el("i"), estLabel),
    hasTarget ? [el("span", {}, el("i", { class: "tgt" }), tgtLabel),
      el("span", {}, el("i", { class: "over" }), `${estLabel} above ${tgtLabel.toLowerCase()}`)] : null),
  el("div", { class: "bars" }, list));
}

/** One stacked bar with a legend. parts: [{label, value, color}] */
export function stack(parts, fmt = (v) => num(v)) {
  const total = parts.reduce((a, p) => a + Math.max(0, p.value || 0), 0);
  const segs = parts.map((p) => el("span", {
    title: `${p.label}: ${fmt(p.value)}`,
    style: `width:${total ? (Math.max(0, p.value || 0) / total * 100).toFixed(2) : 0}%;background:${p.color}`,
  }));
  const legend = el("div", { class: "legend" }, parts.map((p) =>
    el("span", {}, el("i", { style: `background:${p.color}` }), `${p.label} ${fmt(p.value)}` +
      (total ? ` (${(Math.max(0, p.value || 0) / total * 100).toFixed(1)} %)` : ""))));
  return el("div", {}, el("div", { class: "stack", role: "img",
    "aria-label": parts.map((p) => `${p.label} ${fmt(p.value)}`).join(", ") }, segs), legend);
}

/**
 * Line chart as inline SVG sized to its container (redrawn on resize).
 * points: [{label, est, tgt}]; tgt optional (dashed line).
 */
export function lineChart(points, { fmt = usd, tick = usdShort } = {}) {
  const box = el("div", { class: "chart" });
  const draw = () => {
    const width = Math.max(260, box.clientWidth || 600);
    const height = 190, padL = 52, padR = 12, padT = 10, padB = 34;
    const ys = points.flatMap((p) => [p.est, p.tgt]).filter(isNum);
    const top = Math.max(1, ...ys) * 1.08;
    const x = (i) => padL + (points.length < 2 ? (width - padL - padR) / 2
      : (i * (width - padL - padR)) / (points.length - 1));
    const y = (v) => padT + (1 - v / top) * (height - padT - padB);
    const ns = "http://www.w3.org/2000/svg";
    const s = (tag, a, txt) => {
      const n = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(a)) n.setAttribute(k, v);
      if (txt !== undefined) n.textContent = txt;
      return n;
    };
    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": "Trend: " + points.map((p) => `${p.label} ${fmt(p.est)}`).join(", ") });
    for (let i = 0; i <= 4; i++) {
      const v = (top * i) / 4;
      svg.append(s("line", { class: "grid", x1: padL, x2: width - padR, y1: y(v), y2: y(v) }),
        s("text", { x: padL - 6, y: y(v) + 4, "text-anchor": "end" }, tick(v)));
    }
    const path = (key) => points.map((p, i) => (isNum(p[key]) ? [x(i), y(p[key])] : null))
      .filter(Boolean).map((c, i) => `${i ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join("");
    if (points.some((p) => isNum(p.tgt))) svg.append(s("path", { class: "l-tgt", d: path("tgt") }));
    svg.append(s("path", { class: "l-est", d: path("est") }));
    const step = Math.ceil(points.length / Math.max(1, Math.floor((width - padL) / 90)));
    points.forEach((p, i) => {
      if (isNum(p.est)) svg.append(s("circle", { class: "dot", cx: x(i), cy: y(p.est), r: 3.5 }, undefined));
      if (i % step === 0 || i === points.length - 1) {
        const lab = p.label.length > 14 ? p.label.slice(0, 13) + "…" : p.label;
        svg.append(s("text", { x: x(i), y: height - 12, "text-anchor": "middle" }, lab));
      }
    });
    box.replaceChildren(svg);
  };
  let last = 0;
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => { const w = box.clientWidth; if (w && w !== last) { last = w; draw(); } }).observe(box);
  }
  queueMicrotask(draw);
  return box;
}

// ------------------------------------------------------------------ theme, header, print

function storedTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch { return null; }
}
export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode: not remembered */ }
}
function initialTheme() {
  return storedTheme() ||
    (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
document.documentElement.dataset.theme = initialTheme();

// Print: open every <details> so the PDF has the line items, restore afterwards.
let reopened = [];
window.addEventListener("beforeprint", () => {
  reopened = [...document.querySelectorAll("details:not([open])")];
  reopened.forEach((d) => { d.open = true; });
});
window.addEventListener("afterprint", () => { reopened.forEach((d) => { d.open = false; }); reopened = []; });

const PAGES = [["Overview", "index.html", "index"], ["TVD (cost)", "tvd/index.html", "tvd"],
  ["STV (carbon)", "stv/index.html", "stv"]];

function pageUrl(path, snapshotId, latestId) {
  const q = snapshotId && snapshotId !== latestId ? `?snapshot=${encodeURIComponent(snapshotId)}` : "";
  return `${ROOT}/${path}${q}`;
}

/** Fills <header id="site-header">: project, team, snapshot label + date, nav, tools. */
export function renderHeader({ page, idx, snap, projectName, teamName }) {
  const host = document.getElementById("site-header");
  const latest = get(idx, "latest");
  const select = el("select", { "aria-label": "Snapshot",
    onchange: (e) => { location.search = e.target.value === latest ? "" : `?snapshot=${encodeURIComponent(e.target.value)}`; } },
  snapshotsNewestFirst(idx).map((s) =>
    el("option", { value: s.id, selected: snap && s.id === snap.id }, `${s.label} (${when(s.timestamp).slice(0, 10)})`)));
  const themeBtn = el("button", { type: "button", "aria-label": "Switch between dark and light mode",
    onclick: () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark") }, "Dark / light");
  const printBtn = el("button", { type: "button", onclick: () => window.print(),
    title: "Opens the print dialog; choose “Save as PDF”" }, "Print / PDF");
  const sub = [teamName, snap ? snap.label : "no snapshot yet", snap ? when(snap.timestamp) : null]
    .filter(Boolean).join(" · ");
  host.replaceChildren(el("div", { class: "inner" },
    el("h1", { text: projectName || "Concho project" }),
    el("p", { class: "sub", text: sub }),
    el("div", { class: "bar" },
      el("nav", { class: "tabs", "aria-label": "Dashboards" }, PAGES.map(([label, path, key]) =>
        el("a", { href: pageUrl(path, snap && snap.id, latest), "aria-current": key === page ? "page" : null }, label))),
      el("div", { class: "tools" }, idx.snapshots.length ? select : null, printBtn, themeBtn))));
  document.title = `${projectName || "Concho"} – ${PAGES.find((p) => p[2] === page)[0]}`;
}

export function showError(err) {
  const main = document.getElementById("content");
  setContent(main, note("bad", "Could not show this page.", err.message || String(err)));
  console.error(err);
}

/** Names for the header: from the TVD results of the snapshot, else from the STV team. */
export function namesOf(tvd, stv) {
  return {
    projectName: get(tvd || {}, "meta.project_name") || "",
    teamName: get(tvd || {}, "meta.team_name") || get(stv || {}, "team") || "",
  };
}

export function footerLinks(...links) {
  return el("footer", {}, "Built by the Concho pipeline from the results JSON in this site. ", ...links);
}
