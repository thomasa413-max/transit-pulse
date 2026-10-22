"""Screenshots of live pages in Chromium with software WebGL. Used by the preview workflow.

    python scripts/screenshots.py OUT_DIR /fr/carte/ /de/karte/
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pulse import config  # noqa: E402

out, paths = Path(sys.argv[1]), sys.argv[2:]
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    for w, h, tag in ((1440, 900, "desktop"), (390, 844, "mobile")):
        ctx = b.new_context(viewport={"width": w, "height": h})
        for path in paths:
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m, e=errs: e.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            pg.on("pageerror", lambda x, e=errs: e.append(f"pageerror: {x}"))
            try:
                pg.goto(config.SITE_URL + path, wait_until="load", timeout=60000)
                pg.wait_for_timeout(25000)
            except Exception as exc:  # noqa: BLE001
                errs.append(f"navigation: {exc}")
            name = path.strip("/").replace("/", "_") + "-" + tag
            pg.screenshot(path=str(out / f"{name}.png"), full_page=False)
            # Map pages: also the fixed daylight view, and the map frame alone.
            if pg.locator('[data-light="day"]').count():
                try:
                    pg.click('[data-light="day"]')
                    pg.wait_for_timeout(15000)
                    pg.locator("#carte").screenshot(path=str(out / f"{name}-day.png"))
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"day view: {exc}")
            (out / f"{name}.txt").write_text("\n".join(errs) or "no console errors")
            pg.close()
    b.close()
