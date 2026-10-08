# dashboards

Static TVD / STV / schedule pages that read the results JSON. No HTML is generated in Python.

## `site/` (P7.1, P7.2, P7.4: Tier 1)

Plain HTML + CSS + vanilla JS (ES modules), no build step, no CDN, no chart library (bars are
CSS, the trend lines inline SVG).

```
site/
  index.html          overview: snapshot list (results/index.json), newest first
  tvd/index.html      TVD dashboard (tvd_results.json of the selected snapshot)
  stv/index.html      STV dashboard (stv_results.json of the selected snapshot)
  assets/concho.css   the one stylesheet (light / dark, print, phone)
  assets/common.js    header (project, team, snapshot label + date), formatting, builders
  assets/paths.js     every JSON path the pages read (checked by a test against the results)
  assets/{index,tvd,stv}.js
```

`run_pipeline.py site` copies this folder and `results/` into the team's `site/` (plus the
legacy TVD page as `tvd/legacy.html`). The pages fetch the JSON by relative path, so the folder
works on GitHub Pages and from the downloaded `dashboard` artifact, but **not** from `file://`
(browsers block `fetch` there). Open it through a local server:

```sh
cd site
python -m http.server 8000      # then http://localhost:8000/
```

- **Snapshot:** `?snapshot=<id>` (the id from `results/index.json`); the selector in the header
  sets it. Default: the latest.
- **Project and team name:** from `meta.project_name` / `meta.team_name` of the snapshot's
  `tvd_results.json` (STV falls back to its `team`). Nothing project-specific is in the code.
- **PDF:** the "Print / PDF" button opens the print dialog (white page, controls hidden, all
  line items open); choose "Save as PDF". The JPG chart export of the legacy page is dropped.
- **Data quality** (unmapped count, parse warnings, proxies, dropped duplicates, DNC rows) is
  shown, but below the main results and mostly collapsed.
- **Adding a JSON field to a page:** add its path to `assets/paths.js`;
  `tests/site/test_site.py` then checks it against the real results.

Tests: `pytest tests/site` (files, JSON paths, package data; the browser smoke test runs
when Playwright and Chromium are installed). Screenshots of the invented demo data:
`python tests/site/make_screenshots.py OUT_DIR`.

## `tvd/legacy_render.py`

The AutoTVD HTML/PDF dashboard (P1.3), called by `concho-tvd`. Kept for one release as
`tvd/legacy.html` of the site (linked from the footer of the TVD page), then removed.

Schedule dashboard: P7.3 (Tier 2).
