// Overview page (P7.4): the snapshot list from results/index.json, newest first.
import {
  ROOT, badge, card, el, fetchJson, frac, get, loadIndex, namesOf, num, pickSnapshot,
  renderHeader, section, showError, signedUsd, snapshotsNewestFirst, table, usd, when,
} from "./common.js";

async function main() {
  const idx = await loadIndex();
  const latest = pickSnapshot(idx, get(idx, "latest"));
  const content = document.getElementById("content");
  if (!latest) {
    renderHeader({ page: "index", idx, snap: null, projectName: "", teamName: "" });
    content.replaceChildren(el("p", { class: "note info", text: "No snapshots yet. Run the pipeline to create the first one." }));
    return;
  }
  const tvd = await fetchJson(get(latest, "paths.tvd_results")).catch(() => null);
  renderHeader({ page: "index", idx, snap: latest, ...namesOf(tvd, null) });

  const link = (path, text, snap) => {
    const q = snap.id === get(idx, "latest") ? "" : `?snapshot=${encodeURIComponent(snap.id)}`;
    return el("a", { href: `${ROOT}/${path}${q}`, text });
  };
  const jsonLink = (path, text) => path ? el("a", { href: `${ROOT}/${path}`, text }) : el("span", { class: "muted", text: "–" });

  const t = latest.tvd || {};
  const s = latest.stv;
  const over = t.status === "over_target";
  content.replaceChildren(
    el("div", { class: "cards" },
      card("TVD estimate (latest)", usd(t.grand_total), `target ${usd(t.tvd_target)} · ${(t.status || "").replace("_", " ")}`, over ? "over" : "under"),
      s ? card("STV life-cycle carbon (latest)", `${num(s.life_cycle_kgco2e)} kgCO₂e`,
        `target ${num(s.target_kgco2e)} · ${frac(s.target_kgco2e ? s.life_cycle_kgco2e / s.target_kgco2e : null)} of target`)
        : card("STV life-cycle carbon", "–", latest.stv_note || "not available")),
    section("Snapshots", "snapshots",
      el("p", { class: "lead", text: `${idx.snapshots.length} snapshot(s), newest first. Open a snapshot in the TVD or STV dashboard.` }),
      table([
        { label: "Time", value: (r) => when(r.timestamp) },
        { label: "Label", wrap: true, value: (r) => r.label },
        { label: "Commit", value: (r) => el("code", { text: (r.commit || "").slice(0, 7) }) },
        { label: "TVD estimate", num: true, value: (r) => usd(get(r, "tvd.grand_total")) },
        { label: "TVD target", num: true, value: (r) => usd(get(r, "tvd.tvd_target")) },
        { label: "Δ vs target", num: true, value: (r) => signedUsd((get(r, "tvd.grand_total") ?? NaN) - (get(r, "tvd.tvd_target") ?? NaN)) },
        { label: "STV kgCO₂e", num: true, value: (r) => r.stv ? num(r.stv.life_cycle_kgco2e) : el("span", { class: "muted", title: r.stv_note || "", text: "not run" }) },
        { label: "Open", wrap: true, value: (r) => [link("tvd/index.html", "TVD", r), " · ",
          r.stv ? link("stv/index.html", "STV", r) : badge("no STV"), " · ",
          jsonLink(get(r, "paths.tvd_results"), "TVD JSON"), " · ", jsonLink(get(r, "paths.stv_results"), "STV JSON")] },
      ], snapshotsNewestFirst(idx))),
    el("footer", {}, "Snapshot index: ", jsonLink("results/index.json", "results/index.json"),
      ". Dashboards read the JSON files in this site; nothing is generated on a server."));
}

main().catch(showError);
