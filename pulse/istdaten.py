"""Daily punctuality from the Swiss "actual data" (Ist-Daten) file.

The national file is 400-600 MB per day. It is streamed line by line and only
rows for Lausanne stops are kept in memory, so nothing large is ever stored.
"""
from __future__ import annotations

import csv
import io
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Iterable, Iterator

import requests

from . import config

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
LINK_RE = re.compile(r"(https?://[^\"'\s<>]*/download/(\d{4}-\d{2}-\d{2})_istdaten\.csv)", re.IGNORECASE)

MODE_FR = {
    "zug": "Train", "train": "Train", "bus": "Bus", "metro": "Métro", "tram": "Tram",
    "schiff": "Bateau", "zahnradbahn": "Crémaillère", "standseilbahn": "Funiculaire",
}


class NotPublishedYet(Exception):
    """The file for the requested day is not on the platform yet."""


# ---------------------------------------------------------------------------
# Finding the file for a given day
# ---------------------------------------------------------------------------

def find_daily_url(day: date, session: requests.Session | None = None) -> str:
    """Read the download link for `day` from the dataset's web page.

    The catalogue API refuses automated calls (HTTP 403), but the public
    dataset page lists the recent daily files with direct download links.
    """
    override = os.environ.get("IST_DATEN_URL")
    if override:
        return override
    s = session or requests.Session()
    r = s.get(config.IST_DATEN_PAGE, timeout=60, headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    links = find_links(r.text)
    if day.isoformat() in links:
        return links[day.isoformat()]
    if not links:
        raise RuntimeError("The dataset page lists no daily file: its layout may have changed.")
    raise NotPublishedYet(f"No actual-data file for {day} yet (latest listed: {max(links)}).")


def find_links(html: str) -> dict[str, str]:
    """Map 'YYYY-MM-DD' -> download URL for every daily file linked in the page."""
    links = {}
    for m in LINK_RE.finditer(html):
        links.setdefault(m.group(2), m.group(1))
    return links


def stream_rows(url: str, keep=None) -> Iterator[dict]:
    """Stream the CSV and yield rows (as dicts) whose raw line passes `keep`."""
    headers = {"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    with requests.get(url, stream=True, timeout=(30, 300), headers=headers) as r:
        r.raise_for_status()
        yield from parse_lines(decode_lines(r.iter_lines(chunk_size=1 << 20)), keep)


def decode_lines(raw_lines: Iterable[bytes]) -> Iterator[str]:
    """Bytes lines -> text lines (UTF-8, first-line BOM removed, stray CR dropped)."""
    first = True
    for raw in raw_lines:
        line = raw.decode("utf-8", errors="replace").rstrip("\r")
        if first:
            line, first = line.lstrip("﻿"), False
        yield line


def parse_lines(lines: Iterable[str], keep=None) -> Iterator[dict]:
    it = iter(lines)
    header_line = next(it)
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    header = next(csv.reader([header_line], delimiter=delimiter))
    header = [h.strip().upper() for h in header]
    for line in it:
        if keep and not keep(line):
            continue
        values = next(csv.reader([line], delimiter=delimiter), None)
        if not values:
            continue
        yield dict(zip(header, values))


def lausanne_line_filter(line: str) -> bool:
    return any(p in line for p in config.STOP_PREFIXES)


# ---------------------------------------------------------------------------
# Aggregation (pure functions, unit-tested)
# ---------------------------------------------------------------------------

_TIME_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
                 "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1", "t", "yes")


def mode_label(row: dict) -> str:
    raw = (row.get("PRODUKT_ID") or "").strip()
    return MODE_FR.get(raw.lower(), raw or "Autre")


def measure(row: dict) -> tuple[str, float | None, int | None]:
    """Return (kind, delay_minutes, scheduled_hour) for one stop row.

    kind: 'cancelled', 'measured', 'unmeasured' or 'skip'.
    Departure is used when it was really measured, otherwise arrival
    (the last stop of a journey only has an arrival).
    """
    if is_true(row.get("DURCHFAHRT_TF")):
        return "skip", None, None
    if is_true(row.get("FAELLT_AUS_TF")):
        sched = parse_time(row.get("ABFAHRTSZEIT")) or parse_time(row.get("ANKUNFTSZEIT"))
        return "cancelled", None, sched.hour if sched else None
    for planned_col, actual_col, status_col in (
        ("ABFAHRTSZEIT", "AB_PROGNOSE", "AB_PROGNOSE_STATUS"),
        ("ANKUNFTSZEIT", "AN_PROGNOSE", "AN_PROGNOSE_STATUS"),
    ):
        planned = parse_time(row.get(planned_col))
        if not planned:
            continue
        status = (row.get(status_col) or "").strip().upper()
        actual = parse_time(row.get(actual_col))
        if status in ("REAL", "IST") and actual:
            delay = (actual - planned).total_seconds() / 60.0
            if abs(delay) > config.MAX_PLAUSIBLE_DELAY_MIN:
                return "unmeasured", None, planned.hour
            return "measured", delay, planned.hour
        return "unmeasured", None, planned.hour
    return "skip", None, None


class _Bucket:
    __slots__ = ("planned", "measured", "punctual", "cancelled", "delays")

    def __init__(self):
        self.planned = self.measured = self.punctual = self.cancelled = 0
        self.delays: list[float] = []

    def add(self, kind: str, delay: float | None):
        if kind == "skip":
            return
        self.planned += 1
        if kind == "cancelled":
            self.cancelled += 1
        elif kind == "measured":
            self.measured += 1
            self.delays.append(max(delay, 0.0))
            if delay < config.PUNCTUAL_LIMIT_MIN:
                self.punctual += 1

    def summary(self) -> dict:
        out = {
            "passages": self.planned,
            "mesures": self.measured,
            "suppressions": self.cancelled,
            "ponctualite_pct": round(100 * self.punctual / self.measured, 1) if self.measured else None,
            "retard_moyen_min": round(statistics.fmean(self.delays), 1) if self.delays else None,
            "suppressions_pct": round(100 * self.cancelled / self.planned, 1) if self.planned else None,
        }
        if len(self.delays) >= 10:
            out["retard_p90_min"] = round(statistics.quantiles(self.delays, n=10)[-1], 1)
        return out


def aggregate(rows: Iterable[dict], day: date) -> dict:
    total = _Bucket()
    by_mode: dict[str, _Bucket] = defaultdict(_Bucket)
    by_line: dict[tuple, _Bucket] = defaultdict(_Bucket)
    by_stop: dict[str, _Bucket] = defaultdict(_Bucket)
    by_hour: dict[int, _Bucket] = defaultdict(_Bucket)
    worst: list[dict] = []
    stop_ids: dict[str, Counter] = defaultdict(Counter)   # stop name -> stop numbers seen
    stop_lines: dict[str, Counter] = defaultdict(Counter)  # stop name -> lines serving it
    rows_seen = 0

    for row in rows:
        stop = (row.get("HALTESTELLEN_NAME") or "").strip()
        if not stop.startswith(config.STOP_PREFIXES):
            continue
        rows_seen += 1
        kind, delay, hour = measure(row)
        if kind == "skip":
            continue
        mode = mode_label(row)
        line_key = (mode, (row.get("BETREIBER_ABK") or "").strip(), (row.get("LINIEN_TEXT") or "").strip() or "?")
        total.add(kind, delay)
        by_mode[mode].add(kind, delay)
        by_line[line_key].add(kind, delay)
        by_stop[stop].add(kind, delay)
        bpuic = (row.get("BPUIC") or "").strip()
        if bpuic.isdigit():
            stop_ids[stop][bpuic] += 1
        stop_lines[stop][line_key[2]] += 1
        if hour is not None:
            by_hour[hour].add(kind, delay)
        if kind == "measured" and delay >= 10:
            worst.append({
                "retard_min": round(delay, 1), "ligne": line_key[2], "mode": mode,
                "exploitant": line_key[1], "arret": stop,
                "heure_prevue": (row.get("ABFAHRTSZEIT") or row.get("ANKUNFTSZEIT") or "")[-5:],
            })

    def ranked(items, key_fn, reverse=False, n=10):
        eligible = [i for i in items if i["mesures"] >= config.MIN_EVENTS_FOR_RANKING]
        return sorted(eligible, key=key_fn, reverse=reverse)[:n]

    lines = [{"mode": k[0], "exploitant": k[1], "ligne": k[2], **b.summary()} for k, b in by_line.items()]
    stops = [{"arret": k, **b.summary()} for k, b in by_stop.items()]
    # Every stop with its official number (for the map) and the lines that serve it.
    all_stops = sorted(({
        "arret": k, "numero": stop_ids[k].most_common(1)[0][0] if stop_ids[k] else None,
        "lignes": [l for l, _ in stop_lines[k].most_common(8)], **b.summary()} for k, b in by_stop.items()),
        key=lambda x: x["arret"])
    worst.sort(key=lambda w: -w["retard_min"])

    return {
        "date": day.isoformat(),
        "zone": config.AREA_NAME,
        "regle_ponctualite": f"à l'heure = moins de {config.PUNCTUAL_LIMIT_MIN:g} minutes de retard",
        "lignes_source_lues": rows_seen,
        "total": total.summary(),
        "par_mode": [{"mode": m, **b.summary()} for m, b in sorted(by_mode.items(), key=lambda kv: -kv[1].planned)],
        "par_heure": [{"heure": h, **by_hour[h].summary()} for h in sorted(by_hour)],
        "lignes_moins_ponctuelles": ranked(lines, lambda x: (x["ponctualite_pct"], -x["mesures"])),
        "lignes_plus_ponctuelles": ranked(lines, lambda x: (-x["ponctualite_pct"], -x["mesures"]), n=5),
        "arrets_moins_ponctuels": ranked(stops, lambda x: (x["ponctualite_pct"], -x["mesures"])),
        "plus_gros_retards": worst[:5],
        "arrets": all_stops,
        "nb_lignes": len(lines),
        "nb_arrets": len(stops),
    }
