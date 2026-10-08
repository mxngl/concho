"""Screenshots of the demo site (invented data) for the pull request: needs Playwright and the
preinstalled Chromium.  python tests/site/make_screenshots.py OUT_DIR"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "scripts")]

from site_builder import SNAPSHOTS, build_demo_site, serve  # noqa: E402


def main(out: Path) -> None:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        repo, site = build_demo_site(Path(tmp))
        server = serve(site)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            for name, url, width, full in (
                ("index", "/index.html", 1100, True),
                ("tvd", "/tvd/index.html", 1100, True),
                ("stv", "/stv/index.html", 1100, True),
                ("tvd-phone", "/tvd/index.html", 390, False),
            ):
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(base + url)
                page.wait_for_selector("section")
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / f"{name}.png"), full_page=full)
                page.close()
            browser.close()
        server.shutdown()
    print("labels:", [s[0] for s in SNAPSHOTS], "->", sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))
