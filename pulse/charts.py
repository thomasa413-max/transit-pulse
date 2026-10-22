"""Server-side SVG charts: no JavaScript, readable in light and dark themes.

Colours come from CSS custom properties defined in style.css, so the same
markup follows the visitor's theme. Each chart has a text alternative.
"""
from __future__ import annotations

from html import escape


def _nice_range(values: list[float], floor: float | None = None, ceil: float | None = None) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if floor is not None:
        lo = min(lo, floor)
    if ceil is not None:
        hi = max(hi, ceil)
    if hi - lo < 4:
        mid = (hi + lo) / 2
        lo, hi = mid - 2, mid + 2
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def _ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    span = hi - lo
    raw = span / n
    for step in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        if step >= raw:
            break
    start = int(lo / step) * step
    ticks, v = [], start
    while v <= hi:
        if v >= lo:
            ticks.append(round(v, 2))
        v += step
    return ticks


_LANG = {"value": "fr"}


def set_lang(lang: str) -> None:
    """Decimal separator for chart labels: point in English, comma otherwise."""
    _LANG["value"] = lang


def _num(v: float, unit: str = "") -> str:
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    if _LANG["value"] != "en":
        s = s.replace(".", ",")
    if unit.strip() == "%" and _LANG["value"] in ("en", "it"):
        unit = "%"
    return f"{s}{unit}"


def line_chart(points: list[tuple[str, float]], *, title: str, unit: str = " %",
               label_fmt=lambda d: d, highlight_last: bool = True, ref: float | None = None,
               ref_label: str = "", mark_lowest: int = 0) -> str:
    """points: [(x label, value)] in order."""
    if len(points) < 2:
        return ""
    W, H, L, R, T, B = 720, 260, 52, 20, 24, 40
    vals = [v for _, v in points]
    lo, hi = _nice_range(vals)
    pw, ph = W - L - R, H - T - B
    X = lambda i: L + pw * i / (len(points) - 1)
    Y = lambda v: T + ph * (1 - (v - lo) / (hi - lo))
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">',
             f"<title>{escape(title)}</title>"]
    for t in _ticks(lo, hi):
        y = Y(t)
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{_num(t)}</text>')
    if ref is not None and lo < ref < hi:
        y = Y(ref)
        parts.append(f'<line class="ref" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{W - R}" y="{y - 6:.1f}" text-anchor="end">{escape(ref_label)}</text>')
    step = max(1, len(points) // 6)
    for i, (lab, _) in enumerate(points):
        if i % step == 0 or i == len(points) - 1:
            parts.append(f'<text class="tick" x="{X(i):.1f}" y="{H - 14}" text-anchor="middle">{escape(label_fmt(lab))}</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f} {Y(v):.1f}" for i, (_, v) in enumerate(points))
    parts.append(f'<path class="series" d="{path}"/>')
    lowest = set(sorted(range(len(points)), key=lambda i: points[i][1])[:mark_lowest])
    for i, (lab, v) in enumerate(points):
        strong = (highlight_last and i == len(points) - 1) or i in lowest
        cls = "dot last" if strong else "dot"
        parts.append(f'<circle class="{cls}" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{5 if strong else 3}">'
                     f"<title>{escape(label_fmt(lab))} : {_num(v, unit)}</title></circle>")
        if i in lowest:
            parts.append(f'<text class="value" x="{X(i):.1f}" y="{Y(v) + 22:.1f}" text-anchor="middle">'
                         f"{escape(label_fmt(lab))} · {_num(v, unit)}</text>")
    if highlight_last:
        lab, v = points[-1]
        parts.append(f'<text class="value" x="{X(len(points) - 1) - 8:.1f}" y="{Y(v) - 12:.1f}" text-anchor="end">{_num(v, unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(bars: list[tuple[str, float]], *, title: str, unit: str = " %",
              highlight: set[str] | None = None, floor: float | None = None) -> str:
    if not bars:
        return ""
    highlight = highlight or set()
    W, H, L, R, T, B = 720, 240, 52, 12, 20, 36
    vals = [v for _, v in bars]
    lo, hi = (0.0, max(vals) * 1.15 or 1) if floor is None else _nice_range(vals, floor=floor)
    pw, ph = W - L - R, H - T - B
    bw = pw / len(bars)
    Y = lambda v: T + ph * (1 - (v - lo) / (hi - lo))
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">',
             f"<title>{escape(title)}</title>"]
    for t in _ticks(lo, hi):
        y = Y(t)
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{_num(t)}</text>')
    step = max(1, len(bars) // 12)
    for i, (lab, v) in enumerate(bars):
        x = L + i * bw + bw * 0.15
        y = Y(v)
        cls = "bar hl" if lab in highlight else "bar"
        parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{bw * 0.7:.1f}" '
                     f'height="{max(T + ph - y, 1):.1f}" rx="2"><title>{escape(lab)} : {_num(v, unit)}</title></rect>')
        if i % step == 0:
            parts.append(f'<text class="tick" x="{x + bw * 0.35:.1f}" y="{H - 12}" text-anchor="middle">{escape(lab)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def data_table(headers: list[str], rows: list[list[str]], caption: str, summary: str = "Voir les données") -> str:
    """Text alternative shown under each chart in a <details> element."""
    th = "".join(f"<th scope=\"col\">{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<details class="chart-data"><summary>{escape(summary)}</summary>'
            f'<table><caption class="sr-only">{escape(caption)}</caption><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></details>")
