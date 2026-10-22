"""Daily job: yesterday's punctuality -> bulletin -> check -> translations.

Usage:
    python -m pulse.daily                  # yesterday (Europe/Zurich)
    python -m pulse.daily --date 2026-10-21
    python -m pulse.daily --final          # last attempt of the day: fail loudly if data is missing
    python -m pulse.daily --sample tests/fixtures/sample_istdaten.csv   # offline test
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import agents, config, istdaten, util

# First draft + up to two corrections guided by the checker's remarks.
MAX_ATTEMPTS = 3


def update_history(agg: dict) -> list[dict]:
    path = config.DATA / "history.json"
    history = [h for h in util.read_json(path, []) if h["date"] != agg["date"]]
    t = agg["total"]
    history.append({
        "date": agg["date"], "ponctualite_pct": t["ponctualite_pct"],
        "retard_moyen_min": t["retard_moyen_min"], "suppressions": t["suppressions"],
        "passages": t["passages"], "mesures": t["mesures"],
    })
    history.sort(key=lambda h: h["date"])
    history = history[-400:]
    util.write_json(path, history)
    return history


def run(day: date, final: bool = False, sample: Path | None = None, force: bool = False) -> int:
    bulletin_path = config.BULLETIN_DIR / f"{day.isoformat()}.json"
    existing = util.read_json(bulletin_path)
    if existing and existing.get("statut") == "publie" and not force:
        print(f"{day}: bulletin already published, nothing to do.")
        return 0

    # 1. Collect -----------------------------------------------------------
    with util.timed() as t:
        try:
            if sample:
                source = str(sample)
                with sample.open(encoding="utf-8-sig") as fh:
                    agg = istdaten.aggregate(istdaten.parse_lines(fh, istdaten.lausanne_line_filter), day)
            else:
                source = istdaten.find_daily_url(day)
                agg = istdaten.aggregate(istdaten.stream_rows(source, istdaten.lausanne_line_filter), day)
        except istdaten.NotPublishedYet as exc:
            print(exc)
            if final:
                util.append_run({"job": "daily", "agent": "collector", "date": day.isoformat(),
                                 "status": "error", "detail": "Fichier du jour non publié à la dernière tentative."})
                return 1
            return 0  # a later scheduled attempt will try again
        except Exception as exc:  # noqa: BLE001
            util.append_run({"job": "daily", "agent": "collector", "date": day.isoformat(),
                             "status": "error", "detail": str(exc)[:300]})
            print(f"Collector failed: {exc}", file=sys.stderr)
            return 1

    measured = agg["total"]["mesures"]
    util.append_run({"job": "daily", "agent": "collector", "date": day.isoformat(),
                     "status": "ok" if measured else "error", "seconds": t["seconds"],
                     "rows": agg["lignes_source_lues"], "measured": measured,
                     "source": source.rsplit("/", 1)[-1]})
    if not measured:
        print("No measured passage for Lausanne: refusing to publish.", file=sys.stderr)
        return 1
    util.write_json(config.DAILY_DIR / f"{day.isoformat()}.json", agg)
    history = update_history(agg)

    # 2. Write, check, retry once with the checker's feedback -------------
    disruptions = (util.read_json(config.DISRUPTION_FILE, {}) or {}).get("lausanne", [])
    facts = agents.writer_input(agg, history, disruptions)
    try:
        bulletin = agents.write(day, facts)
        verdict = agents.check(day, facts, bulletin)
        attempts = 1
        while not verdict["passed"] and attempts < MAX_ATTEMPTS:
            feedback = [f"{p.get('phrase') or ''} → {p.get('raison')}" for p in verdict["problems"]]
            bulletin = agents.write(day, facts, feedback)
            verdict = agents.check(day, facts, bulletin)
            attempts += 1
    except Exception as exc:  # noqa: BLE001
        print(f"Agent step failed: {exc}", file=sys.stderr)
        return 1

    record = {
        "date": day.isoformat(), "genere_a": util.iso(util.now_utc()),
        "modele": config.MODEL_DAILY, "modele_controle": config.MODEL_CHECKER, "prompt_version": config.PROMPT_VERSION,
        "tentatives": attempts, "controle": verdict, "fr": bulletin,
    }
    if not verdict["passed"]:
        record["statut"] = "bloque"
        util.write_json(bulletin_path, record)
        print("Bulletin blocked by the fact check; nothing published.", file=sys.stderr)
        return 1

    # 3. Translate ---------------------------------------------------------
    try:
        record.update(agents.translate(day, bulletin))
    except Exception as exc:  # noqa: BLE001 - French bulletin still goes out
        print(f"Translation failed: {exc}", file=sys.stderr)
    record["statut"] = "publie"
    util.write_json(bulletin_path, record)
    print(f"{day}: bulletin published ({attempts} attempt(s)).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat)
    p.add_argument("--final", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--sample", type=Path)
    a = p.parse_args()
    code = run(a.date or util.yesterday_local(), final=a.final, sample=a.sample, force=a.force)
    util.prune_run_log()
    return code


if __name__ == "__main__":
    sys.exit(main())
