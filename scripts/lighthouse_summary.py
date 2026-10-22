"""Summarise Lighthouse JSON reports into data/lighthouse.json and enforce targets.

    python scripts/lighthouse_summary.py <reports dir> <output json>

Targets (mobile): performance ≥ 95, accessibility 100, best practices ≥ 95, SEO 100.
During the pilot the "is-crawlable" audit is skipped, because pages are noindex on purpose.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGETS = {"performance": 0.95, "accessibility": 1.0, "best-practices": 0.95, "seo": 1.0}


def main(src: str, dest: str) -> int:
    pages, failures = [], []
    for f in sorted(Path(src).glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except json.JSONDecodeError:
            failures.append(f"{f.name}: unreadable report")
            continue
        url = r.get("finalDisplayedUrl") or r.get("requestedUrl", "")
        path = "/" + url.split("/", 3)[-1] if url.count("/") >= 3 else url
        scores = {k: (r["categories"].get(k) or {}).get("score") or 0 for k in TARGETS}
        audits = r.get("audits", {})
        pages.append({
            "path": path, "scores": scores,
            "lcp": audits.get("largest-contentful-paint", {}).get("displayValue", "–"),
            "cls": audits.get("cumulative-layout-shift", {}).get("displayValue", "–"),
            "tbt": audits.get("total-blocking-time", {}).get("displayValue", "–"),
        })
        for k, target in TARGETS.items():
            if scores[k] < target:
                failed = [a["title"] for a in audits.values()
                          if a.get("score") is not None and a["score"] < 1 and a.get("scoreDisplayMode") == "binary"][:5]
                failures.append(f"{path} {k} {round(scores[k] * 100)} < {round(target * 100)} ({'; '.join(failed)})")
    if not pages:
        failures.append("no Lighthouse report produced")
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pages": pages, "failures": failures,
           "note": "Objectifs : performance ≥ 95, accessibilité 100, bonnes pratiques ≥ 95, SEO 100 (mobile)."}
    Path(dest).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for line in failures:
        print("BELOW TARGET:", line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
