"""Deterministic checks that do not rely on a model.

1. Every number written in a bulletin must exist in the input data.
2. A translation must contain exactly the same numbers as the French text.
"""
from __future__ import annotations

import re
from datetime import date

# 92,4 / 92.4 / 1'234 / 07:15 are all read as numbers. Thousands use the Swiss
# apostrophe (prompts ask for it) so "1,234" is never mistaken for 1.234.
_NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[’'  ]\d{3})+|\d+)(?:[.,](\d+))?")
_TIME_RE = re.compile(r"\b(\d{1,2}) ?[:h] ?(\d{2})\b")


def numbers_in_text(text: str) -> list[float]:
    found: list[float] = []
    # Times first: "07:15" counts as 7 and 15, "7:00" and "7 h" both count as 7.
    masked = text
    for m in _TIME_RE.finditer(text):
        found.append(float(m.group(1)))
        if int(m.group(2)):
            found.append(float(m.group(2)))
        masked = masked.replace(m.group(0), " ")
    for m in _NUM_RE.finditer(masked):
        whole = re.sub(r"[’'   ]", "", m.group(1))
        value = f"{whole}.{m.group(2)}" if m.group(2) else whole
        found.append(float(value))
    return found


def allowed_numbers(facts, day: date | None = None) -> set[float]:
    allowed: set[float] = set()

    def walk(obj):
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float)):
            allowed.add(float(obj))
        elif isinstance(obj, str):
            allowed.update(numbers_in_text(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            allowed.add(float(len(obj)))
            for v in obj:
                walk(v)

    walk(facts)
    if day:
        allowed.update({float(day.day), float(day.month), float(day.year)})
    allowed.update({3.0, 24.0})  # punctuality rule and "24 heures"
    return allowed


def matches(value: float, allowed: set[float]) -> bool:
    for a in allowed:
        if abs(value - a) < 0.051:          # same value, or rounded to 1 decimal
            return True
        if value == round(a) and abs(value - a) < 0.5:  # rounded to an integer
            return True
    return False


def unknown_numbers(text: str, facts, day: date | None = None) -> list[float]:
    allowed = allowed_numbers(facts, day)
    return sorted({n for n in numbers_in_text(text) if not matches(n, allowed)})


def same_numbers(source: str, translation: str) -> tuple[bool, list[float], list[float]]:
    a = sorted(round(n, 1) for n in numbers_in_text(source))
    b = sorted(round(n, 1) for n in numbers_in_text(translation))
    missing = [n for n in set(a) if a.count(n) > b.count(n)]
    extra = [n for n in set(b) if b.count(n) > a.count(n)]
    return (not missing and not extra), sorted(missing), sorted(extra)
