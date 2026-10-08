// TVD dashboard (P7.1): everything comes from tvd_results.json of the selected snapshot and
// results/index.json. The paths read at top level are listed in paths.js.
import {
  ROOT, badge, barChart, card, details, el, fetchJson, footerLinks, frac, get, kv, lineChart,
  loadIndex, namesOf, note, num, pct, pickSnapshot, renderHeader, section, showError,
  signedUsd, snapshotsNewestFirst, stack, table, usd, when,
} from "./common.js";

const entries = (o) => Object.entries(o || {});
const sum = (a) => a.reduce((x, y) => x + (Number.isFinite(y) ? y : 0), 0);

// ------------------------------------------------------------------ summary and warnings

function warnings(res) {
  const out = [];
  const cons = get(res, "target_consistency.status");
  if (cons && cons !== "ok") {
    const gap = get(res, "target_consistency.gap");
    out.push(note(cons === "failed" ? "bad" : "", "Cluster targets do not add up to the total target.",
      `Status “${cons.replace("_", " ")}”: gap ${usd(gap, 2)} (${pct(get(res, "target_consistency.gap_pct"), 4)}). `,
      get(res, "target_consistency.override_reason") ? `Accepted because: ${get(res, "target_consistency.override_reason")}. ` : "",
      el("a", { href: "#consistency", text: "Details" })));
  }
  if (get(res, "target_derivation.target_above_budget") === true) {
    out.push(note("", "Target above budget.", "The total target is higher than the budget derived from the grant. ",
      el("a", { href: "#derivation", text: "Details" })));
  }
  for (const w of get(res, "target_derivation.warnings") || []) out.push(note("", "Target derivation:", w));
  return out;
}

function summary(res) {
  const total = get(res, "financials.grand_total");
  const target = get(res, "financials.tvd_target");
  const delta = get(res, "financials.delta");
  const status = get(res, "financials.status");
  const cls = status === "over_target" ? "over" : status === "under_target" ? "under" : "";
  return el("div", {}, ...warnings(res), el("div", { class: "cards" },
    card("Grand total (estimate)", usd(total), `target ${usd(target)}`, cls),
    card(status === "over_target" ? "Over target by" : "Under target by", usd(Math.abs(delta)),
      `${pct(get(res, "financials.delta_pct"), 2)} vs target`, cls),
    card("Cost per SF", usd(get(res, "financials.cost_per_sf"), 2), `${num(get(res, "meta.gross_sf"))} gross SF`),
    card("Elements", num(get(res, "meta.total_elements") ?? NaN), `${num(get(res, "meta.unmapped_count"))} without code · ${num(get(res, "meta.dnc_count"))} DNC`)));
}

// ------------------------------------------------------------------ clusters, line items

function clusters(res) {
  const rows = get(res, "cluster_summary") || [];
  const total = { cluster: "Total", estimate: get(res, "financials.grand_total"),
    target: get(res, "financials.tvd_target"), delta: get(res, "financials.delta"),
    delta_pct: get(res, "financials.delta_pct"), per_sf: get(res, "financials.cost_per_sf") };
  return section("Clusters: estimate vs target", "clusters",
    barChart(rows.map((r) => ({ label: r.cluster, text: `${usd(r.estimate)} of ${usd(r.target)}`, est: r.estimate, tgt: r.target }))),
    table([
      { label: "Cluster", value: (r) => r.cluster },
      { label: "Estimate", num: true, value: (r) => usd(r.estimate) },
      { label: "Target", num: true, value: (r) => usd(r.target) },
      { label: "Δ (estimate − target)", num: true, value: (r) => el("span", { class: r.delta > 0 ? "over" : "under", text: signedUsd(r.delta) }) },
      { label: "Δ %", num: true, value: (r) => pct(r.delta_pct, 1) },
      { label: "$ / SF", num: true, value: (r) => usd(r.per_sf, 2) },
    ], rows, { total }),
    el("p", { class: "muted", text: "Negative Δ = under target. Targets of clusters without line items are listed with an estimate of $0." }));
}

function lineItems(res) {
  const items = get(res, "line_items") || {};
  const order = [...(get(res, "cluster_summary") || []).map((r) => r.cluster)];
  for (const k of Object.keys(items)) if (!order.includes(k)) order.push(k);
  const blocks = order.filter((k) => items[k]).map((k) => {
    const rows = items[k];
    return details(`${k} · ${rows.length} line item(s) · ${usd(sum(rows.map((r) => r.total)))}`, false, table([
      { label: "Code", value: (r) => r.ac },
      { label: "Group", wrap: true, value: (r) => r.group },
      { label: "Description", wrap: true, value: (r) => r.desc },
      { label: "Unit", value: (r) => r.unit },
      { label: "Unit cost", num: true, value: (r) => usd(r.unit_cost, 2) },
      { label: "Quantity", num: true, value: (r) => num(r.qty, 2) },
      { label: "Quantity from", value: (r) => r.qty_src },
      { label: "Total", num: true, value: (r) => usd(r.total, 2) },
      { label: "Notes", wrap: true, value: (r) => r.notes },
    ], rows, { total: { ac: "", group: "", desc: `${k} total`, unit: "", unit_cost: NaN, qty: NaN, qty_src: "", total: sum(rows.map((r) => r.total)), notes: "" } }));
  });
  return section("Line items per cluster", "line-items", ...blocks);
}

// ------------------------------------------------------------------ targets

function derivation(res) {
  const d = get(res, "target_derivation");
  if (!d) return null;
  const derived = d.method === "derive_from_references";
  const cl = entries(d.clusters).map(([letter, c]) => ({ letter, ...c }));
  const cols = [{ label: "", value: (c) => c.letter }, { label: "Cluster", value: (c) => c.name }];
  if (derived) {
    cols.push({ label: "Reference average", num: true, value: (c) => frac(c.reference_average, 2) },
      { label: "Owner share", num: true, value: (c) => frac(c.owner_share, 2) },
      { label: "Owner-adjusted", num: true, value: (c) => frac(c.owner_adjusted, 2) },
      { label: "Team adjustment", num: true, value: (c) => frac(c.team_adjustment, 2) });
  }
  cols.push({ label: "Final share", num: true, value: (c) => frac(c.final_share, 2) },
    { label: "Target", num: true, value: (c) => usd(c.target) });
  const b = d.budget;
  return section("How the targets were derived", "derivation",
    el("p", { class: "lead", text: derived ? "Cluster split derived from reference projects and owner ratings (course method)."
      : "Cluster targets entered explicitly in the project config." }),
    b ? kv([["Grant", usd(b.grant)], ["Grant year → construction year", `${b.grant_year} → ${b.construction_year}`],
      ["Expected inflation / ROI", `${frac(b.inflation, 2)} / ${frac(b.roi, 2)}`], ["Budget", usd(b.amount)],
      ["Total target", usd(d.total_target)],
      ["Target above budget", d.target_above_budget ? "yes" : "no"]]) : kv([["Total target", usd(d.total_target)]]),
    table(cols, cl, { total: { letter: "", name: "Sum A–H", reference_average: get(d, "sums.reference_average"),
      owner_share: get(d, "sums.owner_share"), owner_adjusted: get(d, "sums.owner_adjusted"),
      team_adjustment: get(d, "sums.team_adjustment"), final_share: get(d, "sums.final_share"), target: get(d, "sums.target") } }));
}

function consistency(res) {
  const c = get(res, "target_consistency");
  if (!c) return null;
  const ok = c.status === "ok";
  const carved = entries(c.carved_out_clusters), onTop = entries(c.on_top_clusters);
  return section("Target consistency", "consistency",
    note(ok ? "info" : (c.status === "failed" ? "bad" : ""), ok ? "OK." : `${c.status.replace("_", " ")}.`,
      ok ? " Clusters A–H plus carved-out clusters add up to the total target." :
        ` Gap ${usd(c.gap, 2)} (${pct(c.gap_pct, 4)}); tolerance ${usd(c.tolerance_amount)}.` +
        (c.override_reason ? ` Accepted: ${c.override_reason}.` : "")),
    kv([["Total target", usd(c.total_target, 2)], ["Clusters A–H", usd(c.sum_a_to_h, 2)],
      ["Carved-out custom clusters", usd(c.sum_carved_out, 2)], ["Gap (A–H + carved out − total)", usd(c.gap, 2)],
      ["On-top custom clusters (outside the total)", usd(c.sum_on_top, 2)],
      ...carved.map(([n, v]) => [`  carved out: ${n}`, usd(v, 2)]), ...onTop.map(([n, v]) => [`  on top: ${n}`, usd(v, 2)])]));
}

// ------------------------------------------------------------------ reliability

const REL = [["high", "High", "var(--high)"], ["medium", "Medium", "var(--medium)"],
  ["low", "Low", "var(--low)"], ["not_rated", "Not rated", "var(--none)"]];
const relParts = (b) => REL.map(([k, label, color]) => ({ label, value: b[k], color }));

function reliability(res) {
  const t = get(res, "reliability.totals");
  if (!t) return null;
  const per = entries(get(res, "reliability.clusters")).map(([name, v]) => ({ name, ...v }));
  return section("Reliability of the estimate", "reliability",
    el("p", { class: "lead", text: "Dollars of the estimate by data reliability (1 High, 2 Medium, 3 Low). “Overall” is the worse of quantity and cost reliability." }),
    el("div", { class: "cols" },
      el("div", {}, el("h3", { text: "Overall" }), stack(relParts(t.overall), usd)),
      el("div", {}, el("h3", { text: "Quantity" }), stack(relParts(t.quantity), usd)),
      el("div", {}, el("h3", { text: "Cost data" }), stack(relParts(t.cost), usd))),
    table([{ label: "Cluster (overall)", value: (r) => r.name },
      ...REL.map(([k, label]) => ({ label, num: true, value: (r) => usd(r.overall[k]) })),
      { label: "Estimate", num: true, value: (r) => usd(r.estimate) }], per,
    { total: { name: "All clusters", overall: t.overall, estimate: t.estimate } }));
}

// ------------------------------------------------------------------ tracking, history, compare

function tracking(res) {
  const rows = get(res, "tracking.rows");
  if (!rows || !rows.length) return null;
  const target = get(res, "tracking.target");
  return section("Tracking", "tracking",
    lineChart(rows.map((r) => ({ label: r.label || r.date, est: r.estimate, tgt: target }))),
    table([{ label: "Date", value: (r) => r.date }, { label: "Snapshot", wrap: true, value: (r) => [r.label, r.current ? badge("this run", "info") : null] },
      { label: "Event", wrap: true, value: (r) => r.event || "" }, { label: "Note", wrap: true, value: (r) => r.note || "" },
      { label: "Estimate", num: true, value: (r) => usd(r.estimate) },
      { label: "Target − estimate", num: true, value: (r) => usd(r.delta) }], rows),
    el("p", { class: "muted", text: "Positive = under target. Older rows use the current target (course sheet “TVD Tracking”)." }));
}

function history(idx) {
  const snaps = idx.snapshots.filter((s) => get(s, "tvd.grand_total") !== undefined);
  if (snaps.length < 2) return null;
  return section("History: all snapshots", "history",
    lineChart(snaps.map((s) => ({ label: s.label, est: s.tvd.grand_total, tgt: s.tvd.tvd_target }))),
    el("p", { class: "muted", text: `${snaps.length} snapshots from results/index.json, oldest left.` }));
}

function compare(idx, snap) {
  if (idx.snapshots.length < 2) return null;
  const list = snapshotsNewestFirst(idx);
  const opts = (sel) => list.map((s) => el("option", { value: s.id, selected: s.id === sel }, `${s.label} (${when(s.timestamp).slice(0, 10)})`));
  const pos = idx.snapshots.findIndex((s) => s.id === snap.id);
  const base = idx.snapshots[Math.max(0, pos - 1)] === snap ? idx.snapshots[Math.min(idx.snapshots.length - 1, pos + 1)] : idx.snapshots[Math.max(0, pos - 1)];
  const a = el("select", { "aria-label": "Compare from" }, opts(base.id));
  const b = el("select", { "aria-label": "Compare to" }, opts(snap.id));
  const out = el("div", {});
  const load = async (id) => fetchJson(idx.snapshots.find((s) => s.id === id).paths.tvd_results);
  const run = async () => {
    out.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      const [ra, rb] = await Promise.all([load(a.value), load(b.value)]);
      const names = [...new Set([...get(ra, "cluster_summary").map((r) => r.cluster), ...get(rb, "cluster_summary").map((r) => r.cluster)])];
      const find = (r, n) => get(r, "cluster_summary").find((x) => x.cluster === n);
      const rows = names.map((n) => {
        const x = find(ra, n), y = find(rb, n);
        return { n, ea: x && x.estimate, eb: y && y.estimate, ta: x && x.target, tb: y && y.target };
      });
      const total = { n: "Total", ea: get(ra, "financials.grand_total"), eb: get(rb, "financials.grand_total"),
        ta: get(ra, "financials.tvd_target"), tb: get(rb, "financials.tvd_target") };
      const d = (r) => (r.ea === undefined || r.eb === undefined ? NaN : r.eb - r.ea);
      out.replaceChildren(table([
        { label: "Cluster", value: (r) => r.n },
        { label: "From: estimate", num: true, value: (r) => usd(r.ea ?? NaN) },
        { label: "To: estimate", num: true, value: (r) => usd(r.eb ?? NaN) },
        { label: "Δ estimate", num: true, value: (r) => el("span", { class: d(r) > 0 ? "over" : d(r) < 0 ? "under" : "", text: signedUsd(d(r)) }) },
        { label: "Δ %", num: true, value: (r) => (r.ea ? pct((d(r) / r.ea) * 100, 1) : "–") },
        { label: "Δ target", num: true, value: (r) => signedUsd((r.tb ?? NaN) - (r.ta ?? NaN)) },
      ], rows, { total }), el("p", { class: "muted", text: "A cluster that exists in only one snapshot (renamed or added) shows “–” on the other side." }));
    } catch (err) {
      out.replaceChildren(note("bad", "Could not compare.", err.message));
    }
  };
  a.addEventListener("change", run); b.addEventListener("change", run);
  run();
  return section("Compare two snapshots", "compare",
    el("div", { class: "tools noprint", style: "margin:0 0 8px" }, "From ", a, " to ", b), out);
}

// ------------------------------------------------------------------ data quality (secondary)

function dataQuality(res) {
  const unmapped = get(res, "meta.unmapped_count"), dnc = get(res, "meta.dnc_count");
  const dups = get(res, "meta.duplicates_removed");
  const parts = [
    kv([["Elements without Assembly Code (not priced)", num(unmapped)], ["Rows marked DNC (skipped)", num(dnc)],
      ["Duplicate rows dropped (D15)", num(dups)]]),
    el("p", { class: "muted", text: unmapped ? "The list of unmapped rows is not part of the results JSON (the legacy dashboard offers it as a CSV download)." : "" }),
  ];
  const dd = get(res, "deduplication");
  if (dd) {
    parts.push(details(`Duplicates and Parts: ${dd.dropped} of ${dd.rows_in} rows dropped`, false,
      kv(entries(dd.by_reason).map(([k, v]) => [k.replaceAll("_", " "), num(v)])),
      dd.dropped_rows && dd.dropped_rows.length ? table([
        { label: "ElementId", value: (r) => r.element_id }, { label: "Category", value: (r) => r.category },
        { label: "Kept from", wrap: true, value: (r) => r.kept_export }, { label: "Dropped from", wrap: true, value: (r) => r.dropped_export },
        { label: "Reason", value: (r) => r.reason.replaceAll("_", " ") }], dd.dropped_rows) : null));
  }
  const cv = get(res, "cost_db_validation");
  if (cv) {
    parts.push(details(`Cost DB: ${cv.rows} rows, ${cv.warning_count} warning(s)`, cv.warning_count > 0,
      cv.warnings.length ? el("ul", {}, cv.warnings.map((w) => el("li", { text: w }))) : el("p", { class: "muted", text: "No warnings." }),
      cv.unpriced.length ? [el("h3", { text: "Rows without unit cost" }), table([
        { label: "Row", num: true, value: (r) => r.row }, { label: "Cluster", value: (r) => r.cluster },
        { label: "Code", value: (r) => r.assembly_code }], cv.unpriced)] : null,
      entries(cv.not_rated).length ? kv(entries(cv.not_rated).map(([k, v]) => [`Rows without ${k}`, num(v)])) : null));
  }
  const qp = get(res, "quantity_parse_warnings");
  if (qp) {
    parts.push(details(`Quantity parsing: ${qp.total} cell(s) with issues`, qp.total > 0,
      ...(entries(qp.columns).length ? entries(qp.columns).map(([col, v]) => el("div", {},
        el("h3", { text: `${col}: ${v.count}` }),
        kv(entries(v.by_issue).map(([k, n]) => [k.replaceAll("_", " "), num(n)])),
        el("p", { class: "muted", text: "Examples: " + (v.examples || []).map((e) => `“${e.value}” (${e.issue.replaceAll("_", " ")})`).join(", ") })))
        : [el("p", { class: "muted", text: `Parser “${qp.parser}”: no cell was dropped or converted.` })])));
  }
  return el("div", { class: "quiet" }, section("Data quality", "data-quality", ...parts));
}

// ------------------------------------------------------------------ main

async function main() {
  const idx = await loadIndex();
  const snap = pickSnapshot(idx);
  const content = document.getElementById("content");
  if (!snap) {
    renderHeader({ page: "tvd", idx, snap: null, projectName: "", teamName: "" });
    content.replaceChildren(note("info", "No snapshots yet.", "Run the pipeline to create the first one."));
    return;
  }
  const res = await fetchJson(get(snap, "paths.tvd_results"));
  renderHeader({ page: "tvd", idx, snap, ...namesOf(res, null) });
  content.replaceChildren(summary(res), clusters(res), lineItems(res), derivation(res), consistency(res),
    reliability(res), tracking(res), history(idx), compare(idx, snap), dataQuality(res),
    footerLinks(el("a", { href: "legacy.html", text: "Legacy TVD dashboard (latest run)" }), ". ",
      "Snapshot data: ", el("a", { href: `${ROOT}/${get(snap, "paths.tvd_results")}`, text: "tvd_results.json" }), "."));
}

main().catch(showError);
