"""Small helpers shared by the jobs: time, JSON files and the run log."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return datetime.now(config.TZ)


def yesterday_local() -> date:
    return (now_local() - timedelta(days=1)).date()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


# --- Run log ---------------------------------------------------------------
# Every job and every agent call appends one JSON line to data/runs.jsonl.
# The "Journal des agents", evaluation and cost pages are built from it.

def append_run(record: dict) -> None:
    config.RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("id", uuid.uuid4().hex[:12])
    record.setdefault("at", iso(now_utc()))
    record.setdefault("trigger", os.environ.get("GITHUB_EVENT_NAME", "local"))
    record.setdefault("github_run", os.environ.get("GITHUB_RUN_ID"))
    with config.RUN_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_runs(limit_days: int | None = None) -> list[dict]:
    runs = []
    try:
        lines = config.RUN_LOG.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return runs
    cutoff = None
    if limit_days:
        cutoff = now_utc() - timedelta(days=limit_days)
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff and datetime.fromisoformat(rec["at"]) < cutoff:
            continue
        runs.append(rec)
    return runs


def prune_run_log(keep_days: int = 400) -> None:
    """Keep the log file bounded (same retention as Imago Biblia's stats)."""
    runs = read_runs(limit_days=keep_days)
    config.RUN_LOG.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs), encoding="utf-8"
    )


@contextmanager
def timed():
    box = {"seconds": 0.0}
    start = time.monotonic()
    try:
        yield box
    finally:
        box["seconds"] = round(time.monotonic() - start, 2)
