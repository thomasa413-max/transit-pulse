"""Service disruptions (SIRI-SX) affecting Lausanne.

The full Swiss feed is one large XML document. It is parsed incrementally and
only situations that mention Lausanne (stop, line or text) are kept.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone
from typing import IO
from xml.etree import ElementTree as ET

import requests

from . import config


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _lang(el) -> str:
    for k, v in el.attrib.items():
        if k.endswith("lang"):
            return v.lower()[:2]
    return ""


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pick(texts: dict[str, list[str]], lang_order=("fr", "en", "de", "it", "")) -> str:
    for lang in lang_order:
        for t in texts.get(lang, []):
            if t.strip():
                return re.sub(r"\s+", " ", t).strip()
    for vals in texts.values():
        for t in vals:
            if t.strip():
                return re.sub(r"\s+", " ", t).strip()
    return ""


def situation_to_dict(el) -> dict:
    """Flatten one PtSituationElement into the fields the site needs."""
    fields: dict[str, dict[str, list[str]]] = {}
    places: set[str] = set()
    lines: set[str] = set()
    periods = []
    simple = {}
    for node in el.iter():
        name = _local(node.tag)
        text = (node.text or "").strip()
        if name in ("SummaryText", "Summary", "DescriptionText", "Description",
                    "ConsequenceText", "ReasonText", "RecommendationText", "DurationText"):
            key = name.replace("Text", "")
            fields.setdefault(key, {}).setdefault(_lang(node), []).append(text)
        elif name in ("StopPlaceName", "StopPointName", "PlaceName") and text:
            places.add(text)
        elif name == "PublishedLineName" and text:
            lines.add(text)
        elif name == "ValidityPeriod":
            start = end = None
            for child in node:
                if _local(child.tag) == "StartTime":
                    start = child.text
                elif _local(child.tag) == "EndTime":
                    end = child.text
            periods.append((start, end))
        elif name in ("SituationNumber", "Progress", "Planned", "Severity", "Priority",
                      "CreationTime", "AlertCause", "ParticipantRef") and text and name not in simple:
            simple[name] = text
    return {
        "id": simple.get("SituationNumber", ""),
        "progres": simple.get("Progress", ""),
        "planifie": simple.get("Planned", "").lower() == "true",
        "gravite": simple.get("Severity", ""),
        "cause": simple.get("AlertCause", ""),
        "source": simple.get("ParticipantRef", ""),
        "cree": simple.get("CreationTime", ""),
        "titre": _pick(fields.get("Summary", {})),
        "description": _pick(fields.get("Description", {})),
        "consequence": _pick(fields.get("Consequence", {})),
        "periodes": [{"debut": s, "fin": e} for s, e in periods],
        "lieux": sorted(places)[:12],
        "lignes": sorted(lines)[:12],
    }


def is_active(sit: dict, at: datetime) -> bool:
    if sit["progres"].lower() == "closed":
        return False
    if not sit["periodes"]:
        return True
    for p in sit["periodes"]:
        start, end = _parse_dt(p["debut"]), _parse_dt(p["fin"])
        if (start is None or start <= at) and (end is None or end >= at):
            return True
    return False


def mentions_area(sit: dict) -> bool:
    """Lausanne must be an affected place or in the title, not just in the text
    (long-distance restrictions often mention Lausanne only as a destination)."""
    hay = " ".join([sit["titre"], *sit["lieux"]]).lower()
    return config.AREA_NAME.lower() in hay


def parse_feed(stream: IO[bytes], at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    kept, total, active_total = [], 0, 0
    for _event, el in ET.iterparse(stream, events=("end",)):
        if _local(el.tag) != "PtSituationElement":
            continue
        total += 1
        sit = situation_to_dict(el)
        el.clear()
        if not is_active(sit, at):
            continue
        active_total += 1
        if mentions_area(sit):
            kept.append(sit)
    kept.sort(key=lambda s: (s["planifie"], s["titre"]))
    return {"situations_suisse": total, "actives_suisse": active_total, "lausanne": kept}


def fetch(api_key: str | None = None) -> dict:
    key = api_key or os.environ.get("OTD_API_KEY")
    if not key:
        raise RuntimeError("OTD_API_KEY is not set (GitHub secret).")
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": config.USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    r = requests.get(config.SIRI_SX_URL, headers=headers, timeout=(30, 180), allow_redirects=True)
    if r.status_code == 429:
        raise RuntimeError("SIRI-SX quota reached (HTTP 429).")
    r.raise_for_status()
    result = parse_feed(io.BytesIO(r.content))
    result["octets"] = len(r.content)
    return result
