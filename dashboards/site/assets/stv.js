// STV dashboard (P7.2): everything comes from stv_results.json of the selected snapshot.
// Units are the ones the engine reports (kgCO2e, MJ, kg water, kg CFC-11e).
import {
  badge, barChart, card, details, el, fetchJson, footerLinks, frac, get, kv, loadIndex,
  namesOf, note, num, pct, pickSnapshot, renderHeader, section, setContent, showError, sig, stack, table,
} from "./common.js";

const UNITS = { carbon: "kgCO₂e", energy: "MJ", water: "kg", ozone: "kg CFC-11e" };
const METRICS = [["carbon", "Carbon"], ["energy", "Energy"], ["water", "Water"], ["ozone", "Ozone depletion"]];
const entries = (o) => Object.entries(o || {});
const fmt = (key, v) => (key === "ozone" ? sig(v) : num(v));
const ratio = (part, whole) => (whole ? part / whole : null);

// ------------------------------------------------------------------ warnings

function warnings(res) {
  const out = [];
  const up = get(res, "use_phase_status");
  if (up && up.modeled === false) {
    out.push(note("", "Use phase not modeled.", `${up.not_modeled_reason || "No reason given."} The totals below are embodied impacts only and are not comparable with the life-cycle targets. `,
      `(source: ${up.source || "?"})`));
  } else if (up && up.all_zero) {
    out.push(note("", "Use phase is all zero.", "The use phase is stated as modeled, but every input is 0."));
  } else if (!up) {
    out.push(note("", "Use phase status unknown.", "This result has no use_phase_status (produced before P3.8)."));
  }
  const px = get(res, "data_flags.proxy");
  if (px) {
    out.push(note("", "Proxy materials.", `${frac(get(res, "data_flags.proxies.share_of_embodied.carbon"))} of embodied carbon (${num(get(res, "data_flags.proxies.embodied.carbon"))} ${UNITS.carbon}) rests on a catalog material standing in for the real one. `,
      el("a", { href: "#flags", text: "Which ones" })));
  }
  if (get(res, "data_flags.custom_material")) {
    out.push(note("info", "Custom materials.", `${frac(get(res, "data_flags.custom_materials.share_of_embodied.carbon"))} of embodied carbon uses custom material values (EPD data of the team, not course data). `,
      el("a", { href: "#flags", text: "Which ones" })));
  }
  return out;
}

// ------------------------------------------------------------------ totals

function totals(res) {
  const c = get(res, "metric_summary.carbon");
  const emb = get(res, "breakdown.embodied.carbon"), use = get(res, "breakdown.use_phase.carbon");
  const life = get(res, "breakdown.life_cycle.carbon");
  const modeled = get(res, "use_phase_status.modeled") !== false;
  return el("div", {}, ...warnings(res), el("div", { class: "cards" },
    card("Life-cycle carbon", `${num(c.project)} ${UNITS.carbon}`, `target ${num(c.target)} · ${frac(c.percent_of_target)} of target`,
      c.percent_of_target > 1 ? "over" : "under"),
    card("Construction (embodied)", `${num(emb)} ${UNITS.carbon}`, `${frac(ratio(emb, life))} of life-cycle carbon`),
    card(`Use phase (${get(res, "lifetime_years")} years)`, modeled ? `${num(use)} ${UNITS.carbon}` : "not modeled",
      modeled ? `${frac(ratio(use, life))} of life-cycle carbon` : "embodied only"),
    card("Proxy share of embodied", get(res, "data_flags.proxy") ? frac(get(res, "data_flags.proxies.share_of_embodied.carbon")) : "none",
      get(res, "data_flags.proxy") ? "catalog material stands in" : "no proxy mappings")));
}

function metrics(res) {
  const rows = METRICS.map(([key, label]) => ({ key, label, unit: UNITS[key], ...get(res, `metric_summary.${key}`),
    emb: get(res, "breakdown.embodied")[key], use: get(res, "breakdown.use_phase")[key] }));
  return section("Life cycle vs target", "metrics",
    // one scale for all metrics: percent of each target (the target is 100 %)
    barChart(rows.filter((r) => r.target).map((r) => ({ label: `${r.label} (${r.unit})`,
      text: `${fmt(r.key, r.project)} of ${fmt(r.key, r.target)} · ${frac(r.percent_of_target)}`,
      est: r.percent_of_target * 100, tgt: 100 })), { estLabel: "Life cycle", tgtLabel: "Target (100 %)" }),
    table([
      { label: "Metric", value: (r) => r.label }, { label: "Unit", value: (r) => r.unit },
      { label: "Target", num: true, value: (r) => fmt(r.key, r.target) },
      { label: "Life cycle", num: true, value: (r) => fmt(r.key, r.project) },
      { label: "% of target", num: true, value: (r) => el("span", { class: r.percent_of_target > 1 ? "over" : "under", text: frac(r.percent_of_target) }) },
      { label: "Construction", num: true, value: (r) => fmt(r.key, r.emb) },
      { label: "Use phase", num: true, value: (r) => fmt(r.key, r.use) },
    ], rows),
    el("p", { class: "muted", text: "Energy is in MJ and water in kg, as the engine reports them. Ozone has no course target." }));
}

const C_EMB = "var(--est)", C_USE = "var(--medium)";
function split(res) {
  const b = (k) => get(res, `breakdown.${k}`);
  const modeled = get(res, "use_phase_status.modeled") !== false;
  const parts = [["embodied_materials", "Materials"], ["embodied_transport", "Transport"],
    ["embodied_construction", "Construction process"], ["use_electricity", "Use: electricity"],
    ["use_heating", "Use: heating"], ["use_water", "Use: water"]];
  return section("Construction vs use phase", "split",
    el("div", { class: "cols" }, METRICS.slice(0, 3).map(([key, label]) => el("div", {},
      el("h3", { text: `${label} (${UNITS[key]})` }),
      stack([{ label: "Construction", value: b("embodied")[key], color: C_EMB },
        { label: "Use phase", value: b("use_phase")[key], color: C_USE }], (v) => fmt(key, v))))),
    modeled ? null : el("p", { class: "muted", text: "Use phase not modeled: the use-phase share is 0 by omission." }),
    table([{ label: "Component", value: (p) => p[1] },
      ...METRICS.map(([key, label]) => ({ label: `${label} (${UNITS[key]})`, num: true, value: (p) => fmt(key, b(p[0])[key]) }))],
    parts, { total: null }));
}

// ------------------------------------------------------------------ assemblies and materials

function assemblies(res) {
  const items = get(res, "construction_items") || [];
  const by = new Map();
  for (const it of items) {
    const a = by.get(it.assembly) || { name: it.assembly, carbon: 0, energy: 0, water: 0, proxy: false, custom: false };
    a.carbon += it.embodied_total.carbon; a.energy += it.embodied_total.energy; a.water += it.embodied_total.water;
    a.proxy ||= it.proxy; a.custom ||= it.custom_material;
    by.set(it.assembly, a);
  }
  const rows = [...by.values()].sort((x, y) => y.carbon - x.carbon);
  const emb = get(res, "breakdown.embodied.carbon");
  const mats = [...items].sort((x, y) => y.embodied_total.carbon - x.embodied_total.carbon);
  return section("Embodied impact by assembly and material", "assemblies",
    barChart(rows.map((r) => ({ label: r.name, text: `${num(r.carbon)} ${UNITS.carbon} · ${frac(ratio(r.carbon, emb))}`, est: r.carbon })), { estLabel: "Embodied carbon" }),
    table([{ label: "STV assembly", value: (r) => [r.name, r.proxy ? badge("proxy") : null, r.custom ? badge("custom", "info") : null] },
      { label: `Carbon (${UNITS.carbon})`, num: true, value: (r) => num(r.carbon) },
      { label: "Share", num: true, value: (r) => frac(ratio(r.carbon, emb)) },
      { label: `Energy (${UNITS.energy})`, num: true, value: (r) => num(r.energy) },
      { label: `Water (${UNITS.water})`, num: true, value: (r) => num(r.water) }], rows),
    details(`By material (${mats.length})`, false, table([
      { label: "STV assembly", value: (r) => r.assembly }, { label: "Material (unit)", wrap: true, value: (r) => r.material_type },
      { label: "Amount", num: true, value: (r) => num(r.amount, 1) },
      { label: `Carbon (${UNITS.carbon})`, num: true, value: (r) => num(r.embodied_total.carbon) },
      { label: "Share of embodied", num: true, value: (r) => frac(ratio(r.embodied_total.carbon, emb)) },
      { label: "Flags", wrap: true, value: (r) => [
        r.proxy ? badge(`proxy ${frac(ratio(r.proxy_amount, r.amount), 0)}`) : null,
        r.custom_material ? badge(`custom: ${r.custom_material_source}`, "info") : null,
        r.estimated ? badge("estimated quantity", "info") : null] },
    ], mats)));
}

function flags(res) {
  const p = get(res, "data_flags.proxies.items") || [];
  const cm = get(res, "data_flags.custom_materials.materials") || [];
  const proxyRules = (get(res, "mapping_coverage.rules") || []).filter((r) => r.proxy);
  if (!p.length && !cm.length && !proxyRules.length) return null;
  return section("Custom materials and proxies", "flags",
    el("p", { class: "lead", text: "A proxy is a catalog material that stands in for a material the course catalog lacks (set by the mapping table). Custom materials come from the team’s own EPD data." }),
    proxyRules.length ? [el("h3", { text: "Proxy mapping rules" }), table([
      { label: "Discipline", value: (r) => r.discipline || "any" }, { label: "Category", value: (r) => r.category },
      { label: "Keyword", value: (r) => r.keyword || "" }, { label: "Counted as", wrap: true, value: (r) => `${r.stv_assembly} / ${r.stv_material_type}` },
      { label: "Elements", num: true, value: (r) => num(r.won) }], proxyRules)] : null,
    p.length ? [el("h3", { text: "Items with a proxy part" }), table([
      { label: "STV assembly", value: (r) => r.assembly }, { label: "Material", wrap: true, value: (r) => r.material_type },
      { label: "Proxy amount", num: true, value: (r) => `${num(r.proxy_amount, 1)} of ${num(r.amount, 1)}` },
      { label: `Carbon (${UNITS.carbon})`, num: true, value: (r) => num(r.embodied.carbon) }], p)] : null,
    cm.length ? [el("h3", { text: "Custom materials" }), table([
      { label: "STV assembly", value: (r) => r.assembly }, { label: "Material", wrap: true, value: (r) => r.material_type },
      { label: "Source", wrap: true, value: (r) => r.source }, { label: `Carbon (${UNITS.carbon})`, num: true, value: (r) => num(r.embodied.carbon) }], cm)] : null);
}

// ------------------------------------------------------------------ coverage, duplicates (secondary)

function coverage(res) {
  const cov = get(res, "mapping_coverage");
  if (!cov) return null;
  const rows = entries(cov.disciplines).map(([name, d]) => ({ name, ...d }));
  return section("Mapping coverage per discipline", "coverage",
    el("p", { class: "lead", text: `Share of the Revit export that the STV mapping table turns into quantities. Unmapped elements are not counted in the totals.` }),
    table([{ label: "Discipline", value: (d) => d.name },
      { label: "Elements", num: true, value: (d) => num(d.elements.total) },
      { label: "Mapped", num: true, value: (d) => `${num(d.elements.mapped)} (${pct(d.elements.mapped_pct, 1)})` },
      { label: "Zero qty", num: true, value: (d) => num(d.elements.zero_quantity) },
      { label: "Unmapped", num: true, value: (d) => num(d.elements.unmapped) },
      { label: "By area", num: true, value: (d) => pct(d.by_quantity.area_sf.mapped_pct, 1) },
      { label: "By volume", num: true, value: (d) => pct(d.by_quantity.volume_cf.mapped_pct, 1) },
      { label: "By length", num: true, value: (d) => pct(d.by_quantity.length_ft.mapped_pct, 1) },
      { label: `${UNITS.carbon}`, num: true, value: (d) => num(d.kgco2e) },
      { label: "On estimates", num: true, value: (d) => pct(d.estimated.kgco2e_pct, 1) }], rows),
    ...rows.filter((d) => d.unmapped_types && d.unmapped_types.length).map((d) =>
      details(`Unmapped types: ${d.name} (${d.unmapped_types.length})`, false, table([
        { label: "Category", value: (t) => t.category }, { label: "Family", wrap: true, value: (t) => t.family },
        { label: "Type", wrap: true, value: (t) => t.type }, { label: "Count", num: true, value: (t) => num(t.count) }],
      d.unmapped_types.slice(0, 25)))));
}

function quiet(res) {
  const parts = [];
  const dd = get(res, "deduplication");
  if (dd) {
    parts.push(details(`Duplicates and Parts: ${dd.dropped} of ${dd.rows_in} rows dropped (D15)`, false,
      kv(entries(dd.by_reason).map(([k, v]) => [k.replaceAll("_", " "), num(v)])),
      dd.dropped_rows && dd.dropped_rows.length ? table([
        { label: "ElementId", value: (r) => r.element_id }, { label: "Category", value: (r) => r.category },
        { label: "Kept from", wrap: true, value: (r) => r.kept_export }, { label: "Dropped from", wrap: true, value: (r) => r.dropped_export },
        { label: "Reason", value: (r) => r.reason.replaceAll("_", " ") }], dd.dropped_rows) : null));
  }
  const dnc = get(res, "dnc_rows");
  if (dnc && dnc.length) {
    parts.push(note("", `${dnc.length} counted row(s) carry the DNC (“do not count”) marker.`,
      " TVD skips these rows, STV counts them (decision still open)."));
    parts.push(details(`DNC rows (${dnc.length})`, false, table([
      { label: "ElementId", value: (r) => r.element_id }, { label: "Category", value: (r) => r.category },
      { label: "Type", wrap: true, value: (r) => r.type }, { label: "Discipline", value: (r) => r.discipline },
      { label: "Status", value: (r) => r.status }], dnc)));
  }
  return parts.length ? el("div", { class: "quiet" }, section("Data quality", "data-quality", ...parts)) : null;
}

// ------------------------------------------------------------------ main

async function main() {
  const idx = await loadIndex();
  const snap = pickSnapshot(idx);
  const content = document.getElementById("content");
  if (!snap) {
    renderHeader({ page: "stv", idx, snap: null, projectName: "", teamName: "" });
    setContent(content, note("info", "No snapshots yet.", "Run the pipeline to create the first one."));
    return;
  }
  const tvd = await fetchJson(get(snap, "paths.tvd_results")).catch(() => null);
  const path = get(snap, "paths.stv_results");
  if (!path) {
    renderHeader({ page: "stv", idx, snap, ...namesOf(tvd, null) });
    setContent(content, note("info", "No STV result in this snapshot.", get(snap, "stv_note") || "STV was not run.",
      " Pick another snapshot in the list above."));
    return;
  }
  const res = await fetchJson(path);
  renderHeader({ page: "stv", idx, snap, ...namesOf(tvd, res) });
  setContent(content, totals(res), metrics(res), split(res), assemblies(res), flags(res), coverage(res), quiet(res),
    footerLinks("Snapshot data: ", el("a", { href: `../${path}`, text: "stv_results.json" }), "."));
}

main().catch(showError);
