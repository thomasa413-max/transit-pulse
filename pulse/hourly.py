"""Disruption job (every 3 hours) and health check.

    python -m pulse.hourly            # fetch SIRI-SX, keep Lausanne situations
    python -m pulse.hourly --health   # fail if the daily pipeline has gone stale
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from . import config, disruptions, util


def calls_today() -> int:
    today = util.now_local().date().isoformat()
    return sum(1 for r in util.read_runs(limit_days=2)
               if r.get("agent") == "siri-sx" and r.get("status") in ("ok", "error")
               and datetime.fromisoformat(r["at"]).astimezone(config.TZ).date().isoformat() == today)


def fetch_disruptions() -> int:
    if calls_today() >= config.SIRI_MAX_CALLS_PER_DAY:
        util.append_run({"job": "disruptions", "agent": "siri-sx", "status": "skipped",
                         "detail": "Quota journalier de sécurité atteint."})
        return 0
    with util.timed() as t:
        try:
            result = disruptions.fetch()
        except Exception as exc:  # noqa: BLE001 - keep the last good snapshot online
            util.append_run({"job": "disruptions", "agent": "siri-sx", "status": "error",
                             "seconds": t["seconds"], "detail": str(exc)[:300]})
            print(f"SIRI-SX failed: {exc}", file=sys.stderr)
            return 1
    result["mis_a_jour"] = util.iso(util.now_utc())
    util.write_json(config.DISRUPTION_FILE, result)
    util.append_run({"job": "disruptions", "agent": "siri-sx", "status": "ok", "seconds": t["seconds"],
                     "situations": result["actives_suisse"], "lausanne": len(result["lausanne"]),
                     "bytes": result.get("octets")})
    print(f"{len(result['lausanne'])} Lausanne situation(s) out of {result['actives_suisse']} active in Switzerland.")
    return 0


def health() -> int:
    published = []
    for path in config.BULLETIN_DIR.glob("*.json"):
        b = util.read_json(path, {})
        if b.get("statut") == "publie" and b.get("genere_a"):
            published.append(datetime.fromisoformat(b["genere_a"]))
    if not published:
        # Nothing published yet: only alert once the project has been live a few days.
        first = util.read_runs()
        if first and util.now_utc() - datetime.fromisoformat(first[0]["at"]) > timedelta(days=3):
            print("ALERT: no bulletin has been published yet.", file=sys.stderr)
            return 1
        return 0
    last = max(published)
    age = util.now_utc() - last
    if age > timedelta(hours=config.DAILY_STALE_HOURS):
        print(f"ALERT: last bulletin published {age} ago.", file=sys.stderr)
        return 1
    print(f"Health OK: last bulletin published {age} ago.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--health", action="store_true")
    a = p.parse_args()
    return health() if a.health else fetch_disruptions()


if __name__ == "__main__":
    sys.exit(main())
