"""Official stop register (service points) for the canton of Vaud: number -> coordinates.

The national file (≈ 25 MB) is refreshed weekly by the daily job and reduced to
the stops of the canton of Vaud, ready for the Vaud version of the map.

    python -m pulse.stops            # refresh if older than 7 days
    python -m pulse.stops --force
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from datetime import datetime, timedelta

import requests

from . import config, util

PAGE = "https://data.opentransportdata.swiss/en/dataset/service-point-v2"
LINK_RE = re.compile(r"https?://[^\"'\s<>]*actual-date-swiss-service-point\.csv")
STOPS_FILE = config.DATA / "stops" / "vd.json"
MAX_AGE = timedelta(days=7)


def reduce(lines, canton: str = "VD") -> dict:
    """CSV lines -> {number: [lon, lat, name, municipality]} for the stops of one canton."""
    reader = csv.DictReader(lines, delimiter=";")
    out = {}
    for r in reader:
        if r.get("cantonAbbreviation") != canton or r.get("stopPoint") != "true":
            continue
        try:
            lon, lat = round(float(r["wgs84East"]), 6), round(float(r["wgs84North"]), 6)
        except (TypeError, ValueError, KeyError):
            continue
        number = (r.get("number") or "").strip()
        if number:
            out[number] = [lon, lat, r.get("designationOfficial", ""), r.get("municipalityName", "")]
    return out


def refresh(force: bool = False) -> bool:
    current = util.read_json(STOPS_FILE, {}) or {}
    if not force and current.get("maj"):
        if util.now_utc() - datetime.fromisoformat(current["maj"]) < MAX_AGE:
            return False
    headers = {"User-Agent": config.USER_AGENT}
    page = requests.get(PAGE, timeout=60, headers=headers)
    page.raise_for_status()
    m = LINK_RE.search(page.text)
    if not m:
        raise RuntimeError("No service point file linked on the dataset page.")
    r = requests.get(m.group(0), timeout=(30, 300), headers=headers)
    r.raise_for_status()
    stops = reduce(io.StringIO(r.content.decode("utf-8-sig")))
    if len(stops) < 500:
        raise RuntimeError(f"Only {len(stops)} stops for Vaud: refusing to overwrite the register.")
    util.write_json(STOPS_FILE, {"maj": util.iso(util.now_utc()), "source": m.group(0).rsplit("/", 1)[-1],
                                 "canton": "VD", "arrets": stops})
    util.append_run({"job": "daily", "agent": "stops", "status": "ok", "count": len(stops)})
    print(f"Stop register refreshed: {len(stops)} stops in Vaud.")
    return True


def load() -> dict:
    return (util.read_json(STOPS_FILE, {}) or {}).get("arrets", {})


def numbers_in(municipalities) -> set[str]:
    """Stop numbers located in the given municipalities."""
    wanted = set(municipalities)
    return {num for num, (_lon, _lat, _name, muni) in load().items() if muni in wanted}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    try:
        refresh(a.force)
    except Exception as exc:  # noqa: BLE001 - the map keeps the last register
        util.append_run({"job": "daily", "agent": "stops", "status": "error", "detail": str(exc)[:300]})
        print(f"Stop register refresh failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
