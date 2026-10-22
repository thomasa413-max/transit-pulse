"""Build the static site in public/ from the files in data/, in four languages.

    python -m pulse.site

Each page exists at /<lang>/<localised slug>/ with hreflang links to its
translations. The admin area (/admin/) is French only and holds no data:
everything it shows comes from the Worker API after login.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape

from . import charts, config, stops as stop_register, util
from .i18n import LANGS, LOCALE, MODES, MONTHS, NATIVE, OG_LOCALE, SLUGS, WEEKDAYS, T, t

MODEL_NAMES = {"claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}
NAV = ("dashboard", "map", "bulletin", "agents", "quality", "costs", "about")
ASSET_V: dict[str, str] = {}


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def url(lang: str, key: str | None = None, *parts: str) -> str:
    if key in (None, "dashboard"):
        return f"/{lang}/"
    return "/" + "/".join([lang, SLUGS[lang][key], *parts]) + "/"


def alternates(key: str | None, *parts: str) -> dict[str, str]:
    return {lang: url(lang, key, *parts) for lang in LANGS}


def absolute(path: str) -> str:
    return config.SITE_URL.rstrip("/") + path


def asset(name: str) -> str:
    return f"/assets/{name}?v={ASSET_V.get(name, '0')}"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def n(v, lang: str, dec: int = 1, unit: str = "") -> str:
    if v is None:
        return "–"
    if isinstance(v, int) or dec == 0:
        s = f"{round(v):,}".replace(",", "'")
    else:
        s = f"{v:.{dec}f}"
        if lang != "en":
            s = s.replace(".", ",")
    return s + unit


def pct(v, lang: str) -> str:
    if v is None:
        return "–"
    return n(v, lang) + (" %" if lang in ("fr", "de") else "%")


def minutes(v, lang: str) -> str:
    return n(v, lang) + " " + t("min", lang) if v is not None else "–"


def usd(v: float, lang: str) -> str:
    s = f"{v:.4f}" if v < 0.01 else f"{v:.2f}"
    if lang in ("fr", "it"):
        s = s.replace(".", ",")
    return f"{s} $" if lang != "en" else f"${s}"


def long_date(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    wd, m = WEEKDAYS[lang][d.weekday()], MONTHS[lang][d.month - 1]
    if lang == "en":
        return f"{wd} {d.day} {m} {d.year}"
    if lang == "de":
        return f"{wd}, {d.day}. {m} {d.year}"
    return f"{wd} {d.day} {m} {d.year}"


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}"


def local_time(iso_utc: str | None) -> str:
    if not iso_utc:
        return "–"
    return datetime.fromisoformat(iso_utc).astimezone(config.TZ).strftime("%d.%m.%Y %H:%M")


def model_name(m: str | None) -> str:
    return MODEL_NAMES.get(m or "", m or "–")


def mode_name(mode: str, lang: str) -> str:
    return MODES[lang].get(mode, mode)


def badge(status: str, lang: str) -> str:
    cls = {"ok": "good", "pass": "good", "publie": "good", "fail": "bad", "error": "bad",
           "bloque": "bad", "partial": "warn", "skipped": "warn"}.get(status, "neutral")
    key = f"st_{status}"
    label = t(key, lang) if key in T else status
    return f'<span class="badge {cls}">{escape(label)}</span>'


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

GLOBE = ('<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="none" '
         'stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></svg>')
GEAR = ('<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="none" '
        'stroke="currentColor" stroke-width="1.8"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>')


def header(lang: str, active: str | None, alts: dict[str, str]) -> str:
    nav = "".join(
        f'<li><a href="{url(lang, k)}"{" aria-current=\"page\"" if k == active else ""}>{escape(t("nav_" + k, lang))}</a></li>'
        for k in NAV)
    langs = "".join(
        f'<li><a href="{alts[l]}" lang="{l}" hreflang="{l}"{" aria-current=\"true\"" if l == lang else ""}>{NATIVE[l]}</a></li>'
        for l in LANGS)
    settings = f"""<div class="settings" id="reglages" hidden>
  <p class="set-row"><span id="lbl-size">{escape(t("text_size", lang))}</span>
    <span class="seg" role="group" aria-labelledby="lbl-size">
      <button type="button" id="moins" aria-label="{escape(t("smaller", lang))}">A−</button>
      <output id="taille-val" aria-live="polite">100 %</output>
      <button type="button" id="plus" aria-label="{escape(t("larger", lang))}">A+</button></span></p>
  <p class="set-row"><span id="lbl-font">{escape(t("font", lang))}</span>
    <span class="seg" role="group" aria-labelledby="lbl-font">
      <button type="button" id="pol-standard" aria-pressed="true">{escape(t("font_standard", lang))}</button>
      <button type="button" id="pol-lisible" aria-pressed="false">{escape(t("font_readable", lang))}</button></span></p>
  <p class="set-row"><span id="lbl-theme">{escape(t("theme", lang))}</span>
    <span class="seg" role="group" aria-labelledby="lbl-theme">
      <button type="button" data-theme-set="light" aria-pressed="false">{escape(t("theme_light", lang))}</button>
      <button type="button" data-theme-set="dark" aria-pressed="false">{escape(t("theme_dark", lang))}</button>
      <button type="button" data-theme-set="system" aria-pressed="true">{escape(t("theme_system", lang))}</button></span></p>
</div>"""
    return f"""<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{url(lang)}"><span class="brand-mark" aria-hidden="true"></span>Transit Pulse <span class="brand-zone">Lausanne</span></a>
    <div class="tools">
      <div class="lang-wrap">
        <button type="button" class="tool" id="btn-lang" aria-expanded="false" aria-controls="lang-menu">{GLOBE}<span class="sr-only">{escape(t("lang_button", lang))} : </span><span>{NATIVE[lang]}</span></button>
        <ul class="lang-menu" id="lang-menu" hidden>{langs}</ul>
      </div>
      <button type="button" class="tool" id="btn-reglages" aria-expanded="false" aria-controls="reglages">{GEAR}<span>{escape(t("settings", lang))}</span></button>
    </div>
    <nav aria-label="{escape(t("nav_label", lang))}"><ul>{nav}</ul></nav>
  </div>
  <div class="wrap">{settings}</div>
</header>"""


def footer(lang: str) -> str:
    link = '<a href="https://opentransportdata.swiss/">opentransportdata.swiss</a>'
    return f"""<footer class="site-footer">
  <div class="wrap">
    <p>{t("footer_data", lang, link=link)}</p>
    <p>{escape(t("footer_disclaimer", lang))}</p>
    <ul class="footer-links">
      <li><a href="{url(lang, "visitors")}">{escape(t("nav_visitors", lang))}</a></li>
      <li><a href="{url(lang, "privacy")}">{escape(t("nav_privacy", lang))}</a></li>
      <li><a href="{config.REPO_URL}">{escape(t("source_code", lang))}</a></li>
    </ul>
  </div>
</footer>"""


def write(path: str, html: str) -> None:
    out = config.PUBLIC / path.strip("/") / "index.html" if path.endswith("/") else config.PUBLIC / path.lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


PAGES: list[dict] = []   # for the sitemap


def page(lang: str, key: str | None, title: str, body: str, description: str, *,
         alts: dict[str, str], active: str | None = None, jsonld: list[dict] | None = None,
         scripts: tuple[str, ...] = (), og_type: str = "website", sitemap: bool = True,
         lastmod: str | None = None, path: str | None = None, styles: tuple[str, ...] = ()) -> None:
    path = path or alts[lang]
    full_title = title if key in (None, "dashboard") else f"{title} · {config.SITE_TITLE}"
    robots = "index, follow, max-image-preview:large" if config.INDEXING else "noindex, nofollow"
    hreflang = "".join(f'<link rel="alternate" hreflang="{l}" href="{absolute(alts[l])}">' for l in LANGS)
    hreflang += f'<link rel="alternate" hreflang="x-default" href="{absolute(alts["fr"])}">'
    og_alt = "".join(f'<meta property="og:locale:alternate" content="{OG_LOCALE[l]}">' for l in LANGS if l != lang)
    # "<" escaped so text inside the data (AI-written headlines) can never close the script element.
    ld = "".join(f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False).replace("<", "\\u003c")}</script>'
                 for j in (jsonld or []))
    js = "".join(f'<script src="{asset(s)}" defer></script>' for s in ("site.js", *scripts))
    image = absolute(f"/assets/og/og-{lang}.png")
    html = f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(full_title)}</title>
<meta name="description" content="{escape(description)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{absolute(path)}">
{hreflang}
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{config.SITE_TITLE}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{absolute(path)}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="{OG_LOCALE[lang]}">{og_alt}
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0b6e69">
<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{asset("style.css")}">{"".join(f'<link rel="stylesheet" href="{asset(x)}">' for x in styles)}
<script src="{asset("prefs.js")}"></script>
{js}
{ld}
</head>
<body>
<a class="skip" href="#contenu">{escape(t("skip", lang))}</a>
{header(lang, active, alts)}
<main id="contenu" class="wrap" tabindex="-1">
{body}
</main>
{footer(lang)}
</body>
</html>
"""
    write(path, html)
    if sitemap:
        PAGES.append({"alts": alts, "lastmod": lastmod})


def section(title: str, inner: str, lead: str = "", sid: str = "") -> str:
    lead_html = f'<p class="lead-sm">{lead}</p>' if lead else ""
    return f'<section class="block"{f" id={sid!r}" if sid else ""}><h2>{escape(title)}</h2>{lead_html}{inner}</section>'


def table(headers: list[str], rows: list[list[str]], lang: str, numeric_from: int = 1, caption: str = "",
          numeric_to: int = 99) -> str:
    if not rows:
        return f'<p class="muted">{escape(t("no_data", lang))}</p>'
    num = lambda i: numeric_from <= i <= numeric_to  # noqa: E731
    th = "".join(f'<th scope="col"{" class=num" if num(i) else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(
        f'<td{" class=num" if num(i) else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    cap = f'<caption class="sr-only">{escape(caption)}</caption>' if caption else ""
    return f'<div class="table-wrap" tabindex="0" role="region" aria-label="{escape(caption)}"><table>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def tile(label: str, value: str, note: str = "", tone: str = "") -> str:
    return (f'<div class="tile {tone}"><p class="tile-label">{escape(label)}</p>'
            f'<p class="tile-value">{value}</p>{f"<p class=tile-note>{note}</p>" if note else ""}</div>')


def breadcrumb(items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": absolute(p)} for i, (name, p) in enumerate(items)]}


PUBLISHER = {"@type": "Organization", "name": config.SITE_TITLE, "url": config.SITE_URL,
             "logo": {"@type": "ImageObject", "url": config.SITE_URL + "/assets/og/logo.png"}}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load():
    history = util.read_json(config.DATA / "history.json", []) or []
    latest = util.read_json(config.DAILY_DIR / f"{history[-1]['date']}.json") if history else None
    bulletins = {}
    for p in sorted(config.BULLETIN_DIR.glob("*.json")):
        b = util.read_json(p)
        if b:
            bulletins[b["date"]] = b
    disruptions = util.read_json(config.DISRUPTION_FILE, {}) or {}
    return history, latest, bulletins, disruptions, util.read_runs()


def published(bulletins: dict) -> list[dict]:
    return sorted((b for b in bulletins.values() if b.get("statut") == "publie"), key=lambda b: b["date"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def disruption_list(disruptions: dict, lang: str) -> str:
    if not disruptions:
        return f'<p class="muted">{escape(t("disr_wait", lang))}</p>'
    items = disruptions.get("lausanne") or []
    head = f'<p class="lead-sm">{escape(t("disr_lead", lang, when=local_time(disruptions.get("mis_a_jour")), n=n(disruptions.get("actives_suisse"), lang, 0)))}</p>'
    if not items:
        return head + f'<p class="empty">{escape(t("disr_none", lang))}</p>'
    lis = []
    for s in items[:12]:
        txt = (s.get("textes") or {}).get(lang) or {"titre": s.get("titre"), "description": s.get("description"), "consequence": s.get("consequence")}
        kind = t("disr_planned" if s.get("planifie") else "disr_unplanned", lang)
        lines = ", ".join(s.get("lignes") or [])
        period = s["periodes"][0] if s.get("periodes") else {}
        until = t("disr_until", lang, d=local_time(period["fin"])) if period.get("fin") and not period["fin"].startswith("2099") else ""
        lines_html = f" <span>{escape(t('disr_lines', lang, l=lines))}</span>" if lines else ""
        desc = txt.get("description") or txt.get("consequence") or ""
        short = desc[:280] + ("…" if len(desc) > 280 else "")
        lis.append(
            f'<li class="disruption"><p class="d-meta"><span class="badge {"neutral" if s.get("planifie") else "warn"}">{escape(kind)}</span>'
            f'{lines_html}'
            f'{f"<span>{escape(until)}</span>" if until else ""}</p>'
            f'<p class="d-title">{escape(txt.get("titre") or t("disr_default", lang))}</p>'
            f'{f"<p class=d-desc>{escape(short)}</p>" if desc else ""}</li>')
    return head + f'<ul class="disruptions">{"".join(lis)}</ul>'


def build_index(lang, history, latest, bulletins, disruptions) -> None:
    alts = alternates(None)
    hero = (f'<div class="hero"><p class="eyebrow">{escape(t("eyebrow", lang))}</p>'
            f'<h1>{escape(t("h1", lang))}</h1><p class="lead">{escape(t("lead", lang))}</p></div>')
    website = {"@context": "https://schema.org", "@type": "WebSite", "name": config.SITE_TITLE,
               "url": absolute(url(lang)), "inLanguage": LOCALE[lang], "description": t("meta_home", lang),
               "publisher": PUBLISHER}
    if not latest:
        body = hero + section(t("waiting_title", lang), f'<p class="empty">{escape(t("waiting_text", lang))}</p>') \
            + section(t("disruptions", lang), disruption_list(disruptions, lang))
        page(lang, "dashboard", t("home_title", lang), body, t("meta_home", lang), alts=alts, active="dashboard", jsonld=[website])
        return

    tt = latest["total"]
    prev = history[-2] if len(history) >= 2 else None
    delta = ""
    if prev and prev.get("ponctualite_pct") is not None and tt["ponctualite_pct"] is not None:
        d = round(tt["ponctualite_pct"] - prev["ponctualite_pct"], 1)
        sign = "+" if d > 0 else ("−" if d < 0 else "±")
        unit = t("points" if abs(d) >= 2 else "point", lang)
        delta = t("delta_prev", lang, delta=f"{sign}{n(abs(d), lang)} {unit}")
    tiles = "".join([
        tile(t("tile_ontime", lang), pct(tt["ponctualite_pct"], lang), escape(delta), "accent"),
        tile(t("tile_delay", lang), minutes(tt["retard_moyen_min"], lang),
             escape(t("tile_p90", lang, v=minutes(tt["retard_p90_min"], lang))) if tt.get("retard_p90_min") is not None else ""),
        tile(t("tile_cancel", lang), n(tt["suppressions"], lang, 0), escape(t("tile_cancel_note", lang, pct=pct(tt["suppressions_pct"], lang)))),
        tile(t("tile_measured", lang), n(tt["mesures"], lang, 0),
             escape(t("tile_measured_note", lang, planned=n(tt["passages"], lang, 0), stops=n(latest["nb_arrets"], lang, 0)))),
    ])
    body = hero + f'<p class="asof">{t("day_of", lang, date="<strong>" + escape(long_date(latest["date"], lang)) + "</strong>")}</p><div class="tiles">{tiles}</div>'

    pub = published(bulletins)
    if pub:
        b = pub[-1]
        content = b.get(lang) if lang != "fr" else b["fr"]
        content = content or b["fr"]
        link = url(lang, "bulletin", b["date"])
        body += (f'<article class="bulletin-card"><p class="eyebrow">{escape(t("bulletin_of", lang, date=short_date(b["date"])))} · '
                 f'{badge("pass", lang)} {escape(t("verified", lang))}</p><h2><a href="{link}">{escape(content["titre"])}</a></h2>'
                 f'<p>{escape(content["paragraphes"][0] if content["paragraphes"] else "")}</p>'
                 f'<p><a class="more" href="{link}">{escape(t("read_bulletin", lang))}</a></p></article>')

    charts.set_lang(lang)
    pts = [(h["date"], h["ponctualite_pct"]) for h in history[-30:] if h.get("ponctualite_pct") is not None]
    if len(pts) >= 2:
        trend = charts.line_chart(pts, title=t("trend_chart", lang), label_fmt=short_date)
        trend += charts.data_table([t("col_day", lang), t("col_ontime", lang)],
                                   [[long_date(d, lang), pct(v, lang)] for d, v in reversed(pts)], t("trend_chart", lang), t("show_data", lang))
        body += section(t("trend", lang), trend, escape(t("trend_lead", lang)))
    hours = [(t("hour_fmt", lang, h=h["heure"]), h["ponctualite_pct"]) for h in latest["par_heure"]
             if h["mesures"] >= 30 and h["ponctualite_pct"] is not None]
    if len(hours) >= 2:
        chart = charts.line_chart(hours, title=t("hours_chart", lang), highlight_last=False, mark_lowest=2)
        chart += charts.data_table([t("col_hour", lang), t("col_ontime", lang)], [[lab, pct(v, lang)] for lab, v in hours],
                                   t("hours_chart", lang), t("show_data", lang))
        body += section(t("hours", lang), chart, escape(t("hours_lead", lang)))

    body += section(t("by_mode", lang), table(
        [t("col_mode", lang), t("col_ontime", lang), t("col_delay", lang), t("col_cancel", lang), t("col_measured", lang)],
        [[escape(mode_name(m["mode"], lang)), pct(m["ponctualite_pct"], lang), minutes(m["retard_moyen_min"], lang),
          n(m["suppressions"], lang, 0), n(m["mesures"], lang, 0)] for m in latest["par_mode"]], lang, caption=t("by_mode", lang)))
    body += '<div class="two-col">'
    body += section(t("worst_lines", lang), table(
        [t("col_line", lang), t("col_operator", lang), t("col_ontime", lang), t("col_delay", lang)],
        [[f'<strong>{escape(l["ligne"])}</strong> <span class="muted">{escape(mode_name(l["mode"], lang))}</span>', escape(l["exploitant"]),
          pct(l["ponctualite_pct"], lang), minutes(l["retard_moyen_min"], lang)]
         for l in latest["lignes_moins_ponctuelles"][:8]], lang, numeric_from=2, caption=t("worst_lines", lang)),
        escape(t("worst_lines_lead", lang, n=config.MIN_EVENTS_FOR_RANKING)))
    body += section(t("worst_stops", lang), table(
        [t("col_stop", lang), t("col_ontime", lang), t("col_measured", lang)],
        [[escape(s["arret"]), pct(s["ponctualite_pct"], lang), n(s["mesures"], lang, 0)]
         for s in latest["arrets_moins_ponctuels"][:8]], lang, caption=t("worst_stops", lang)))
    body += "</div>"
    if latest["plus_gros_retards"]:
        body += section(t("biggest", lang), table(
            [t("tile_delay", lang).split()[0] if lang == "en" else t("col_delay", lang).replace("Ø ", ""), t("col_line", lang), t("col_stop", lang), t("col_scheduled", lang)],
            [[f"<strong>{minutes(w['retard_min'], lang)}</strong>", f"{escape(w['ligne'])} ({escape(w['exploitant'])})",
              escape(w["arret"]), escape(w["heure_prevue"])] for w in latest["plus_gros_retards"]],
            lang, numeric_from=9, caption=t("biggest", lang)))
    body += section(t("disruptions", lang), disruption_list(disruptions, lang), sid="perturbations")
    body += f'<p class="method">{escape(t("method", lang))} <a href="{url(lang, "about")}#methode">{escape(t("learn_more", lang))}</a></p>'

    first = history[0]["date"] if history else latest["date"]
    dataset = {"@context": "https://schema.org", "@type": "Dataset", "name": t("home_title", lang),
               "description": t("meta_home", lang), "url": absolute(url(lang)), "inLanguage": LOCALE[lang],
               "creator": PUBLISHER, "temporalCoverage": f"{first}/{latest['date']}",
               "spatialCoverage": {"@type": "Place", "name": "Lausanne, Vaud, Switzerland",
                                   "geo": {"@type": "GeoCoordinates", "latitude": 46.5197, "longitude": 6.6323}},
               "variableMeasured": [t("tile_ontime", lang), t("tile_delay", lang), t("tile_cancel", lang)],
               "isBasedOn": "https://data.opentransportdata.swiss/en/dataset/ist-daten-v2",
               "dateModified": latest["date"]}
    page(lang, "dashboard", t("home_title", lang), body, t("meta_home", lang), alts=alts, active="dashboard",
         jsonld=[website, dataset], lastmod=latest["date"])


# ---------------------------------------------------------------------------
# Bulletins
# ---------------------------------------------------------------------------

def comments_block(lang: str, thread: str) -> str:
    key = escape(config.TURNSTILE_SITE_KEY)
    return f"""<section class="block comments" id="commentaires" aria-labelledby="titre-commentaires" data-thread="{escape(thread)}" data-lang="{lang}" data-sitekey="{key}">
<h2 id="titre-commentaires">{escape(t("comments", lang))} <span class="count" id="nb-commentaires"></span></h2>
<p class="lead-sm">{escape(t("comments_lead", lang))}</p>
<ol class="comment-list" id="liste-commentaires" aria-live="polite"></ol>
<p class="muted" id="etat-commentaires" role="status"></p>
<noscript><p class="muted">{escape(t("c_noscript", lang))}</p></noscript>
<form class="comment-form" id="form-commentaire" novalidate>
  <p><label for="c-nom">{escape(t("c_name", lang))}</label>
  <input id="c-nom" name="name" type="text" maxlength="40" autocomplete="nickname" required></p>
  <p><label for="c-texte">{escape(t("c_message", lang))}</label>
  <textarea id="c-texte" name="message" rows="4" minlength="20" maxlength="1000" required aria-describedby="c-aide"></textarea>
  <span class="hint" id="c-aide">{escape(t("c_hint", lang))}</span></p>
  <p class="trap" aria-hidden="true"><label for="c-site">{escape(t("c_trap", lang))}</label><input id="c-site" name="website" type="text" tabindex="-1" autocomplete="off"></p>
  <div class="turnstile" id="turnstile"></div>
  <p><button type="submit" class="btn">{escape(t("c_submit", lang))}</button></p>
  <p class="form-message" id="c-message" role="status" aria-live="polite"></p>
</form>
</section>"""


def bulletin_html(b: dict, lang: str) -> str:
    content, content_lang = (b.get(lang), lang) if lang != "fr" and b.get(lang) else (b["fr"], "fr")
    out = []
    if content_lang != lang:
        out.append(f'<p class="notice">{escape(t("translation_missing", lang))}</p>')
    out.append(f'<article class="bulletin" lang="{content_lang}"><h1>{escape(content["titre"])}</h1>')
    out += [f"<p>{escape(p)}</p>" for p in content["paragraphes"]]
    out.append("</article>")
    check = t("check_first" if b.get("tentatives", 1) == 1 else "check_retry", lang)
    prov = t("provenance", lang, writer=f"<strong>{escape(model_name(b['modele']))}</strong>",
             checker=f"<strong>{escape(model_name(b.get('modele_controle')))}</strong>", check=escape(check),
             when=local_time(b["genere_a"]))
    if content_lang != "fr":
        prov += " " + escape(t("translated_by", lang, model=model_name(b.get("modele_traduction", config.MODEL_DAILY))))
    out.append(f'<aside class="provenance"><p>{badge("pass", lang)} {prov}</p></aside>')
    return "".join(out), content


def build_bulletins(lang: str, bulletins: dict) -> None:
    pub = published(bulletins)
    for i, b in enumerate(pub):
        d = b["date"]
        alts = alternates("bulletin", d)
        html, content = bulletin_html(b, lang)
        nav = '<nav class="pager" aria-label="' + escape(t("bulletins", lang)) + '">'
        if i > 0:
            nav += f'<a rel="prev" href="{url(lang, "bulletin", pub[i - 1]["date"])}">← {escape(t("prev_bulletin", lang))}</a>'
        if i < len(pub) - 1:
            nav += f'<a rel="next" href="{url(lang, "bulletin", pub[i + 1]["date"])}">{escape(t("next_bulletin", lang))} →</a>'
        nav += "</nav>"
        body = (f'<p class="asof"><a href="{url(lang, "bulletin")}">{escape(t("bulletins", lang))}</a> · {escape(long_date(d, lang))}</p>'
                + html + nav + comments_block(lang, d))
        article = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": content["titre"][:110],
                   "datePublished": b["genere_a"], "dateModified": b["genere_a"], "inLanguage": LOCALE[lang],
                   "image": [absolute(f"/assets/og/og-{lang}.png")], "author": PUBLISHER, "publisher": PUBLISHER,
                   "mainEntityOfPage": absolute(alts[lang]), "articleSection": t("nav_bulletin", lang),
                   "isBasedOn": "https://data.opentransportdata.swiss/en/dataset/ist-daten-v2",
                   "contentLocation": {"@type": "Place", "name": "Lausanne"}}
        crumbs = breadcrumb([(t("nav_dashboard", lang), url(lang)), (t("bulletins", lang), url(lang, "bulletin")),
                             (long_date(d, lang), alts[lang])])
        page(lang, "bulletin", content["titre"], body, " ".join(content["paragraphes"])[:155].rsplit(" ", 1)[0] + "…",
             alts=alts, active="bulletin", jsonld=[article, crumbs], scripts=("comments.js",), og_type="article", lastmod=d)

    archive = []
    for d, b in sorted(bulletins.items(), reverse=True)[:90]:
        if b.get("statut") == "publie":
            c = b.get(lang) or b["fr"]
            archive.append(f'<li><a href="{url(lang, "bulletin", d)}">{escape(long_date(d, lang))}</a> — {escape(c["titre"])}</li>')
        elif b.get("statut") == "bloque":
            q = f'<a href="{url(lang, "quality")}">{escape(t("nav_quality", lang))}</a>'
            archive.append(f'<li>{escape(long_date(d, lang))} — {badge("bloque", lang)} {t("blocked_entry", lang, link=q)}</li>')
    alts = alternates("bulletin")
    if pub:
        html, _ = bulletin_html(pub[-1], lang)
        body = (f'<p class="asof">{escape(t("latest_bulletin", lang))} · <a href="{url(lang, "bulletin", pub[-1]["date"])}">'
                f'{escape(long_date(pub[-1]["date"], lang))}</a></p>' + html)
    else:
        body = f'<h1>{escape(t("nav_bulletin", lang))}</h1><p class="empty">{escape(t("no_bulletin", lang))}</p>'
    if archive:
        body += section(t("archives", lang), f'<ul class="archive">{"".join(archive)}</ul>')
    page(lang, "bulletin", t("bulletins", lang), body, t("meta_bulletin", lang), alts=alts, active="bulletin",
         lastmod=pub[-1]["date"] if pub else None)


# ---------------------------------------------------------------------------
# Agents, quality, costs
# ---------------------------------------------------------------------------

def agent_name(a: str | None, lang: str) -> str:
    key = f"agent_{a}"
    return t(key, lang) if key in T else (a or "")


def build_agents(lang: str, runs: list[dict]) -> None:
    def last(pred):
        found = [r for r in runs if pred(r)]
        return found[-1] if found else None
    l_daily = last(lambda r: r.get("job") == "daily" and r.get("agent") == "collector")
    l_pub = last(lambda r: r.get("agent") == "translator" and r.get("status") == "ok")
    l_sx = last(lambda r: r.get("agent") == "siri-sx")
    tiles = "".join([
        tile(t("last_collect", lang), local_time(l_daily["at"]) if l_daily else "–", badge(l_daily["status"], lang) if l_daily else t("pending", lang)),
        tile(t("last_translation", lang), local_time(l_pub["at"]) if l_pub else "–", badge(l_pub["status"], lang) if l_pub else t("pending", lang)),
        tile(t("last_disruptions", lang), local_time(l_sx["at"]) if l_sx else "–", badge(l_sx["status"], lang) if l_sx else t("pending", lang)),
    ])
    schedule = table([t("col_task", lang), t("col_when", lang), t("col_what", lang)], [
        [escape(t("task_daily", lang)), escape(t("task_daily_when", lang)), escape(t("task_daily_what", lang))],
        [escape(t("task_disr", lang)), escape(t("task_every3", lang)), escape(t("task_disr_what", lang))],
        [escape(t("task_health", lang)), escape(t("task_every3", lang)), escape(t("task_health_what", lang))],
        [escape(t("task_perf", lang)), escape(t("task_perf_when", lang)), escape(t("task_perf_what", lang))],
    ], lang, numeric_from=9, caption=t("schedule", lang))
    rows = []
    for r in reversed(runs[-80:]):
        tokens = f"{n(r.get('input_tokens'), lang, 0)} / {n(r.get('output_tokens'), lang, 0)}" if r.get("input_tokens") else "–"
        cost = usd(r["cost_usd"], lang) if r.get("cost_usd") else "–"
        detail, dlang = r.get("detail") or "", "fr"
        if r.get("agent") == "collector" and r.get("measured"):
            detail, dlang = t("d_measured", lang, n=n(r["measured"], lang, 0)), lang
        elif r.get("agent") == "siri-sx" and r.get("status") == "ok":
            detail, dlang = t("d_sx", lang, l=n(r.get("lausanne"), lang, 0), s=n(r.get("situations"), lang, 0)), lang
        elif r.get("agent") == "checker" and r.get("problems"):
            detail, dlang = t("d_problems", lang, n=len(r["problems"])), lang
        elif r.get("agent") == "translator":
            detail, dlang = ", ".join(r.get("languages") or []) or (r.get("language") or ""), lang
        cell = f'<span lang="{dlang}">{escape(detail[:90])}</span>' if detail else ""
        rows.append([local_time(r["at"]), escape(agent_name(r.get("agent"), lang)), escape(model_name(r.get("model"))),
                     n(r.get("seconds"), lang, unit=" s"), tokens, cost, badge(r.get("status", ""), lang), cell])
    body = (f'<h1>{escape(t("agents_title", lang))}</h1><p class="lead">{escape(t("agents_lead", lang))}</p>'
            f'<div class="tiles three">{tiles}</div>'
            + section(t("schedule", lang), schedule)
            + section(t("recent_runs", lang), table(
                [t("col_time", lang), t("col_agent", lang), t("col_model", lang), t("col_duration", lang), t("col_tokens", lang),
                 t("col_cost", lang), t("col_status", lang), t("col_detail", lang)], rows, lang,
                numeric_from=3, numeric_to=5, caption=t("recent_runs", lang))))
    page(lang, "agents", t("agents_title", lang), body, t("meta_agents", lang), alts=alternates("agents"), active="agents")


def build_quality(lang: str, bulletins: dict, runs: list[dict]) -> None:
    since = (date.today() - timedelta(days=30)).isoformat()
    recent = [b for d, b in bulletins.items() if d >= since]
    pub = [b for b in recent if b.get("statut") == "publie"]
    blocked = [b for b in recent if b.get("statut") == "bloque"]
    corrected = [b for b in pub if b.get("tentatives", 1) > 1]
    first = [b for b in pub if b.get("tentatives", 1) == 1]
    rate = round(100 * len(first) / len(recent), 1) if recent else None
    tr = [r for r in runs if r.get("agent") == "translator" and r.get("language")][-90:]
    tr_ok = sum(1 for r in tr if r.get("status") == "ok")
    tiles = "".join([
        tile(t("q_first", lang), pct(rate, lang), escape(t("q_first_note", lang, a=len(first), b=len(recent))), "accent"),
        tile(t("q_corrected", lang), n(len(corrected), lang, 0), escape(t("q_corrected_note", lang))),
        tile(t("q_blocked", lang), n(len(blocked), lang, 0), escape(t("q_blocked_note", lang))),
        tile(t("q_translations", lang), f"{tr_ok} / {len(tr)}" if tr else "–", escape(t("q_translations_note", lang))),
    ])
    fails = []
    for r in reversed([r for r in runs if r.get("agent") == "checker"][-200:]):
        if r.get("status") != "fail":
            continue
        for p in (r.get("problems") or [])[:4]:
            fails.append([escape(r.get("date", "")), f'<span lang="fr">{escape(p.get("raison", ""))}</span>',
                          f'<span lang="fr">{escape((p.get("phrase") or "")[:160])}</span>'])
    problems = (table([t("col_day", lang), t("col_reason", lang), t("col_sentence", lang)], fails[:60], lang, numeric_from=9,
                      caption=t("q_problems", lang)) if fails else f'<p class="empty">{escape(t("q_none", lang))}</p>')
    body = (f'<h1>{escape(t("quality_title", lang))}</h1><p class="lead">{escape(t("quality_lead", lang))}</p>'
            f'<div class="tiles">{tiles}</div>' + section(t("q_problems", lang), problems, escape(t("q_problems_lead", lang)) if fails and lang != "fr" else ""))
    page(lang, "quality", t("quality_title", lang), body, t("meta_quality", lang), alts=alternates("quality"), active="quality")


def build_costs(lang: str, runs: list[dict]) -> None:
    paid = [r for r in runs if r.get("cost_usd")]
    by_day: dict[str, float] = defaultdict(float)
    by_agent: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0.0])
    month = util.now_local().strftime("%Y-%m")
    month_total = 0.0
    for r in paid:
        local = datetime.fromisoformat(r["at"]).astimezone(config.TZ)
        by_day[local.date().isoformat()] += r["cost_usd"]
        a = by_agent[r.get("agent", "?")]
        a[0] += 1
        a[1] += r.get("input_tokens", 0)
        a[2] += r.get("output_tokens", 0)
        a[3] += r["cost_usd"]
        if local.strftime("%Y-%m") == month:
            month_total += r["cost_usd"]
    days_elapsed = util.now_local().day
    projection = month_total / days_elapsed * 30 if days_elapsed else 0
    fake = any(r.get("fake") for r in paid)
    n_bulletins = sum(1 for r in runs if r.get("agent") == "checker" and r.get("status") == "pass") or 1
    per_bulletin = sum(v[3] for k, v in by_agent.items() if k in ("writer", "checker", "translator")) / n_bulletins
    tiles = "".join([
        tile(t("c_month", lang), usd(month_total, lang), escape(t("c_budget", lang, b=f"{config.MONTHLY_BUDGET_USD:.0f}")), "accent"),
        tile(t("c_projection", lang), usd(projection, lang), escape(t("c_pace", lang))),
        tile(t("c_per_bulletin", lang), usd(per_bulletin, lang) if by_agent.get("writer") else "–", escape(t("c_per_bulletin_note", lang))),
        tile(t("c_hosting", lang), usd(0, lang).replace("0,0000", "0,00").replace("0.0000", "0.00"), escape(t("c_hosting_note", lang))),
    ])
    last30 = [(util.now_local().date() - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    charts.set_lang(lang)
    bars = [(short_date(d), by_day.get(d, 0.0) * 100) for d in last30]
    chart = ""
    if any(v for _, v in bars):
        chart = charts.bar_chart(bars, title=t("c_per_day_chart", lang), unit=" ¢")
        chart += charts.data_table([t("col_day", lang), t("col_cost", lang)],
                                   [[d, usd(by_day[d], lang)] for d in reversed(last30) if by_day.get(d)], t("c_per_day", lang), t("show_data", lang))
    rows = [[escape(agent_name(k, lang)), n(v[0], lang, 0), n(v[1], lang, 0), n(v[2], lang, 0), usd(v[3], lang)]
            for k, v in sorted(by_agent.items(), key=lambda kv: -kv[1][3])]
    link = f'<a href="https://platform.claude.com/docs/en/about-claude/pricing">{escape(t("c_price_link", lang))}</a>'
    body = (f'<h1>{escape(t("costs_title", lang))}</h1><p class="lead">{escape(t("costs_lead", lang))}</p>'
            + (f'<p class="notice">{escape(t("demo_notice", lang))}</p>' if fake else "")
            + f'<div class="tiles">{tiles}</div>'
            + (section(t("c_per_day", lang), chart, escape(t("c_per_day_lead", lang))) if chart else "")
            + section(t("c_by_agent", lang), table([t("col_agent", lang), t("col_calls", lang), t("col_tin", lang), t("col_tout", lang), t("col_cost", lang)],
                                                   rows, lang, caption=t("c_by_agent", lang)))
            + f'<p class="method">{t("c_prices", lang, link=link)}</p>')
    page(lang, "costs", t("costs_title", lang), body, t("meta_costs", lang), alts=alternates("costs"), active="costs")


# ---------------------------------------------------------------------------
# About, visitors, privacy, 404
# ---------------------------------------------------------------------------

def arch_svg(lang: str) -> str:
    L = lambda k: escape(t(k, lang))  # noqa: E731
    return f"""<svg class="diagram" viewBox="0 0 720 400" role="img" aria-label="{L('dg_title')}">
<title>{L('dg_title')}</title>
<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="arrowhead"/></marker></defs>
<g class="box"><rect x="16" y="16" width="216" height="56" rx="8"/><text x="28" y="40" class="b">{L('dg_ist')}</text><text x="28" y="58">{L('dg_ist2')}</text></g>
<g class="box"><rect x="252" y="16" width="216" height="56" rx="8"/><text x="264" y="40" class="b">{L('dg_sx')}</text><text x="264" y="58">{L('dg_sx2')}</text></g>
<g class="box"><rect x="488" y="16" width="216" height="56" rx="8"/><text x="500" y="40" class="b">{L('dg_gh')}</text><text x="500" y="58">{L('dg_gh2')}</text></g>
<g class="box"><rect x="16" y="112" width="688" height="56" rx="8"/><text x="28" y="136" class="b">{L('dg_col')}</text><text x="28" y="154">{L('dg_col2')}</text></g>
<g class="box group"><rect x="16" y="208" width="688" height="96" rx="8"/><text x="28" y="230" class="b">{L('dg_agents')}</text>
<rect x="32" y="244" width="200" height="48" rx="8" class="inner"/><text x="44" y="266" class="b">{L('agent_writer')}</text><text x="44" y="282">{L('dg_w2')}</text>
<rect x="260" y="244" width="200" height="48" rx="8" class="inner"/><text x="272" y="266" class="b">{L('dg_c')}</text><text x="272" y="282">{L('dg_c2')}</text>
<rect x="488" y="244" width="200" height="48" rx="8" class="inner"/><text x="500" y="266" class="b">{L('agent_translator')}</text><text x="500" y="282">{L('dg_t2')}</text></g>
<g class="box"><rect x="16" y="336" width="320" height="48" rx="8"/><text x="28" y="358" class="b">{L('dg_block')}</text><text x="28" y="374">{L('dg_block2')}</text></g>
<g class="box accent"><rect x="384" y="336" width="320" height="48" rx="8"/><text x="396" y="358" class="b">{L('dg_site')}</text><text x="396" y="374">{L('dg_site2')}</text></g>
<g class="links"><path d="M124 72V112" marker-end="url(#arr)"/><path d="M360 72V112" marker-end="url(#arr)"/><path d="M360 168V208" marker-end="url(#arr)"/>
<path d="M232 268H260" marker-end="url(#arr)"/><path d="M460 268H488" marker-end="url(#arr)"/><path d="M176 304V336" marker-end="url(#arr)"/><path d="M544 304V336" marker-end="url(#arr)"/></g>
</svg>"""


def ul(items: list[str]) -> str:
    return '<ul class="plain">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def build_about(lang: str) -> None:
    platform = f'<a href="https://opentransportdata.swiss/">{escape(t("platform_name", lang))}</a>'
    gh = f'<a href="{config.REPO_URL}">{escape(t("source_on_github", lang))}</a>'
    body = (f'<h1>{escape(t("about_title", lang))}</h1><p class="lead">{escape(t("about_lead", lang))}</p>'
            + section(t("architecture", lang), arch_svg(lang) + f'<p class="muted small">{escape(t("arch_note", lang))}</p>')
            + section(t("method_title", lang), ul(t("method_items", lang)), sid="methode")
            + section(t("safeguards", lang), ul([escape(x) for x in t("safeguard_items", lang)]))
            + section(t("sources", lang), f"<p>{t('sources_text', lang, link=platform)}</p>")
            + section(t("author", lang), f"<p>{t('author_text', lang, link=gh)}</p>"))
    page(lang, "about", t("about_title", lang), body, t("meta_about", lang), alts=alternates("about"), active="about",
         jsonld=[{"@context": "https://schema.org", "@type": "AboutPage", "name": t("about_title", lang),
                  "inLanguage": LOCALE[lang], "author": {"@type": "Person", "name": config.AUTHOR}}])


def build_visitors(lang: str) -> None:
    tiles = "".join([
        tile(t("v_total", lang), '<span data-stat="total">–</span>', "", "accent"),
        tile(t("v_30", lang), '<span data-stat="last30">–</span>'),
        tile(t("v_today", lang), '<span data-stat="today">–</span>'),
    ])
    body = (f'<h1>{escape(t("visitors_title", lang))}</h1><p class="lead">{escape(t("visitors_lead", lang))}</p>'
            f'<div class="tiles three" id="visiteurs" data-lang="{lang}" data-locale="{LOCALE[lang]}">{tiles}</div>'
            + section(t("v_chart", lang), f'<div id="graphe-visiteurs" data-title="{escape(t("v_chart", lang))}" data-show="{escape(t("show_data", lang))}"></div>'
                      f'<p class="muted" id="etat-visiteurs" role="status">{escape(t("v_loading", lang))}</p>'
                      f'<template id="txt-unavailable">{escape(t("v_unavailable", lang))}</template>')
            + f'<p class="method"><a href="{url(lang, "privacy")}">{escape(t("v_privacy", lang))}</a></p>')
    page(lang, "visitors", t("visitors_title", lang), body, t("meta_visitors", lang), alts=alternates("visitors"), scripts=("visitors.js",))


def build_privacy(lang: str) -> None:
    body = f'<h1>{escape(t("privacy_title", lang))}</h1>' + section(t("privacy_title", lang), ul(t("privacy_items", lang)))
    page(lang, "privacy", t("privacy_title", lang), body, t("meta_privacy", lang), alts=alternates("privacy"))


def build_404(lang: str) -> None:
    body = (f'<h1>{escape(t("nf_title", lang))}</h1><p class="lead">{escape(t("nf_text", lang))}</p>'
            f'<p><a class="btn" href="{url(lang)}">{escape(t("nf_home", lang))}</a></p>')
    alts = {l: f"/{l}/404.html" for l in LANGS}
    page(lang, None, t("nf_title", lang), body, t("nf_text", lang), alts=alts, sitemap=False, path=f"/{lang}/404.html")
    # A 404 page must never be indexed, whatever the global setting.
    p = config.PUBLIC / lang / "404.html"
    p.write_text(p.read_text(encoding="utf-8").replace('content="index, follow, max-image-preview:large"', 'content="noindex"'), encoding="utf-8")


# ---------------------------------------------------------------------------
# 3D map
# ---------------------------------------------------------------------------

MIN_STOP_MEASURES = 20


def build_map_data(latest: dict | None, disruptions: dict) -> dict:
    """public/data/carte.json: stops with coordinates and punctuality, disruptions placed on a stop."""
    register = stop_register.load()
    by_name = {}
    for number, (lon, lat, name, _muni) in register.items():
        by_name.setdefault(name, (lon, lat))
    stops, missing = [], 0
    for s in (latest or {}).get("arrets", []):
        if s["mesures"] < MIN_STOP_MEASURES or s["ponctualite_pct"] is None:
            continue
        coord = register.get((s.get("numero") or "")[:7])
        pos = (coord[0], coord[1]) if coord else by_name.get(s["arret"])
        if not pos:
            missing += 1
            continue
        stops.append({"id": s.get("numero") or s["arret"], "nom": s["arret"], "lon": pos[0], "lat": pos[1],
                      "pct": s["ponctualite_pct"], "retard": s["retard_moyen_min"], "mesures": s["mesures"],
                      "supprimes": s["suppressions"], "lignes": s.get("lignes", [])})
    pins = []
    for d in disruptions.get("lausanne") or []:
        for place in d.get("lieux") or []:
            pos = by_name.get(place)
            if pos:
                pins.append({"lon": pos[0], "lat": pos[1], "lieu": place, "planifie": d.get("planifie"),
                             "textes": {l: (d.get("textes") or {}).get(l, {}).get("titre") or d.get("titre") for l in LANGS}})
                break
    data = {"date": (latest or {}).get("date"), "arrets": stops, "sans_coordonnees": missing,
            "perturbations": pins, "maj_perturbations": disruptions.get("mis_a_jour")}
    out = config.PUBLIC / "data" / "carte.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data


def toggle(id_: str, label: str, on: bool = True) -> str:
    return (f'<button type="button" class="map-toggle" id="{id_}" aria-pressed="{str(on).lower()}">'
            f'<span class="dot" aria-hidden="true"></span>{escape(label)}</button>')


def build_map(lang: str, data: dict) -> None:
    alts = alternates("map")
    i18n_js = {k: t(k, lang) for k in ("map_show", "col_ontime", "col_delay", "col_measured", "col_cancel", "col_lines",
                                       "map_weather", "map_nowebgl", "disr_planned", "disr_unplanned", "min",
                                       "map_zoom_in", "map_zoom_out", "map_rotate_left", "map_rotate_right", "map_reset")}
    i18n_js["close"] = t("map_close", lang)
    i18n_js["locale"] = LOCALE[lang]
    i18n_js["lang"] = lang
    stops = sorted(data["arrets"], key=lambda x: (x["pct"], -x["mesures"]))
    rows = [[escape(s["nom"]), pct(s["pct"], lang), minutes(s["retard"], lang), n(s["mesures"], lang, 0),
             escape(", ".join(s["lignes"][:6])),
             f'<button type="button" class="tool small-btn" data-fly="{escape(str(s["id"]))}">{escape(t("map_show", lang))}</button>']
            for s in stops]
    legend = (f'<div class="map-legend"><p class="legend-title">{escape(t("map_legend", lang))}</p>'
              f'<p><span class="sw good" aria-hidden="true"></span>{escape(t("map_legend_good", lang))}</p>'
              f'<p><span class="sw mid" aria-hidden="true"></span>{escape(t("map_legend_mid", lang))}</p>'
              f'<p><span class="sw low" aria-hidden="true"></span>{escape(t("map_legend_low", lang))}</p>'
              f'<p><span class="sw bad" aria-hidden="true"></span>{escape(t("map_legend_bad", lang))}</p>'
              f'<p class="muted small">{escape(t("map_legend_height", lang))}</p></div>')
    controls = (f'<div class="map-panel" role="group" aria-label="{escape(t("map_layers", lang))}">'
                f'<p class="legend-title">{escape(t("map_layers", lang))}</p>'
                + toggle("t-stops", t("map_punct", lang)) + toggle("t-disr", t("map_disr", lang))
                + toggle("t-buildings", t("map_buildings", lang)) + toggle("t-photo", t("map_photo", lang))
                + toggle("t-2d", t("map_view_2d", lang), False)
                + f'<p class="legend-title" id="lbl-light">{escape(t("map_light", lang))}</p>'
                f'<span class="seg" role="group" aria-labelledby="lbl-light">'
                f'<button type="button" data-light="auto" aria-pressed="true">{escape(t("map_auto", lang))}</button>'
                f'<button type="button" data-light="day" aria-pressed="false">{escape(t("map_day", lang))}</button>'
                f'<button type="button" data-light="night" aria-pressed="false">{escape(t("map_night", lang))}</button></span>'
                f'</div>')
    asof = t("map_data_of", lang, date=long_date(data["date"], lang)) if data.get("date") else ""
    body = (f'<h1>{escape(t("map_title", lang))}</h1><p class="lead">{escape(t("map_lead", lang))}</p>'
            f'<a class="skip-map" href="#liste-arrets">{escape(t("map_skip", lang))}</a>'
            f'<div class="map-shell">'
            f'<div id="carte" class="map" role="region" aria-label="{escape(t("map_region", lang))}" '
            f'data-src="/data/carte.json?v={ASSET_V.get("carte", "0")}" data-module="{asset("carte3d.js")}">'
            f'<p class="map-status" id="carte-etat" role="status">{escape(t("map_loading", lang))}</p>'
            f'<div class="map-facade" id="carte-apercu" hidden>'
            f'<img src="/assets/carte-apercu.webp?v={ASSET_V.get("carte-apercu.webp", "0")}" width="700" height="612" alt="{escape(t("map_preview_alt", lang))}" decoding="async">'
            f'<button type="button" class="map-start">{escape(t("map_start", lang))}</button></div>'
            f'<div class="map-credits"></div></div>'
            f'<div class="map-side">{controls}{legend}'
            f'<div class="map-weather" id="meteo" aria-live="polite"><p class="legend-title">{escape(t("map_weather", lang))}</p><p class="muted">–</p></div>'
            f'<p class="muted small">{escape(asof)}</p></div></div>'
            f'<p class="muted small">{escape(t("map_controls_hint", lang))}</p>'
            f'<script type="application/json" id="carte-i18n">{json.dumps(i18n_js, ensure_ascii=False).replace("<", "\\u003c")}</script>'
            + section(t("map_list", lang),
                      table([t("col_stop", lang), t("col_ontime", lang), t("col_delay", lang), t("col_measured", lang),
                             t("col_lines", lang), t("map_col_action", lang)], rows, lang, numeric_from=1, numeric_to=3, caption=t("map_list", lang))
                      if rows else f'<p class="empty">{escape(t("map_no_stops", lang))}</p>',
                      escape(t("map_list_lead", lang)), sid="liste-arrets")
            + section(t("disruptions", lang), disruption_list({**DISRUPTIONS_CACHE}, lang))
            + f'<p class="method">{escape(t("map_credits", lang))}</p>')
    page(lang, "map", t("map_title", lang), body, t("meta_map", lang), alts=alts, active="map",
         scripts=("map-boot.js",), lastmod=data.get("date"),
         jsonld=[{"@context": "https://schema.org", "@type": "Map", "name": t("map_title", lang), "inLanguage": LOCALE[lang],
                  "description": t("meta_map", lang), "spatialCoverage": {"@type": "Place", "name": "Lausanne"}}])


DISRUPTIONS_CACHE: dict = {}

# CesiumJS adds this stylesheet for its data credits; the hash allows exactly that text and nothing else.
CESIUM_CREDIT_STYLE_HASH = "'sha256-gM2CWYHXIHTu7Ts6ncwv0GMWZ9LXGrz2qqqjyuDojl8='"


# ---------------------------------------------------------------------------
# Admin shell (French; data comes from the API after login)
# ---------------------------------------------------------------------------

ADMIN_SECTIONS = [
    ("/admin/", "Accueil", "admin-home.js"),
    ("/admin/commentaires/", "Commentaires", "admin-comments.js"),
    ("/admin/statistiques/", "Statistiques", "admin-stats.js"),
    ("/admin/performance/", "Performance", "admin-perf.js"),
]


def build_admin() -> None:
    for path, label, script in ADMIN_SECTIONS:
        menu = "".join(
            f'<li><a href="{p}"{" aria-current=\"page\"" if p == path else ""}>{l}'
            f'{" <span class=badge-count id=nb-attente hidden></span>" if p == "/admin/commentaires/" else ""}</a></li>'
            for p, l, _ in ADMIN_SECTIONS)
        html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{label} · Administration · {config.SITE_TITLE}</title>
<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{asset("style.css")}">
<link rel="stylesheet" href="{asset("admin.css")}">
<script src="{asset("prefs.js")}"></script>
<script src="{asset("admin-core.js")}" defer></script>
<script src="{asset(script)}" defer></script>
</head>
<body class="admin">
<a class="skip" href="#contenu">Aller au contenu</a>
<header class="site-header"><div class="wrap header-inner">
  <a class="brand" href="/admin/"><span class="brand-mark" aria-hidden="true"></span>Transit Pulse <span class="brand-zone">Administration</span></a>
  <nav aria-label="Administration" id="menu-admin" hidden><ul>{menu}</ul></nav>
  <button type="button" class="tool" id="deconnexion" hidden>Se déconnecter</button>
</div></header>
<main id="contenu" class="wrap" tabindex="-1">
<section class="block login" id="connexion" hidden>
  <h1>Connexion</h1>
  <form id="form-connexion">
    <p><label for="mdp">Mot de passe</label><input id="mdp" type="password" autocomplete="current-password" required></p>
    <p><button class="btn" type="submit">Se connecter</button></p>
    <p class="form-message" id="erreur-connexion" role="alert"></p>
  </form>
</section>
<div id="app" hidden>
<h1>{label}</h1>
<div id="contenu-admin"><p class="muted" role="status">Chargement…</p></div>
</div>
</main>
</body>
</html>
"""
        write(path, html)


# ---------------------------------------------------------------------------
# SEO files
# ---------------------------------------------------------------------------

def build_sitemap() -> None:
    entries = []
    for p in PAGES:
        alts = p["alts"]
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{absolute(alts[l])}"/>' for l in LANGS)
        links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{absolute(alts["fr"])}"/>'
        lastmod = f"<lastmod>{p['lastmod']}</lastmod>" if p.get("lastmod") else ""
        for l in LANGS:
            entries.append(f"<url><loc>{absolute(alts[l])}</loc>{lastmod}{links}</url>")
    # Each page is listed once per language; de-duplicate (pages are registered per language).
    unique = list(dict.fromkeys(entries))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
           + "\n".join(unique) + "\n</urlset>\n")
    (config.PUBLIC / "sitemap.xml").write_text(xml, encoding="utf-8")
    if config.INDEXING:
        robots = (f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\n\nSitemap: {absolute('/sitemap.xml')}\n")
    else:
        robots = "# Pilot phase: not indexed. Set INDEXING = True in pulse/config.py at go-live.\nUser-agent: *\nDisallow: /\n"
    (config.PUBLIC / "robots.txt").write_text(robots, encoding="utf-8")
    headers = (config.STATIC / "_headers").read_text(encoding="utf-8")
    # The 3D map loads swisstopo's tiles (geo.admin.ch), runs the engine's own web workers and
    # WebAssembly decoders, and its credit box adds one known stylesheet (allowed by hash).
    # Only the map pages and the engine files get this wider policy ("! header" removes the global one).
    swiss = "https://3d.geo.admin.ch https://wmts.geo.admin.ch"
    map_csp = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; child-src 'self' blob:; "
               f"style-src 'self' {CESIUM_CREDIT_STYLE_HASH}; style-src-attr 'unsafe-inline'; img-src 'self' data: blob: {swiss}; font-src 'self'; "
               f"connect-src 'self' {swiss}; base-uri 'none'; "
               "form-action 'self'; frame-ancestors 'none'; object-src 'none'; upgrade-insecure-requests")
    for lang in LANGS:
        headers += f"\n{url(lang, 'map')}\n  ! Content-Security-Policy\n  Content-Security-Policy: {map_csp}\n"
    engine_csp = (f"default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' {swiss}; "
                  "worker-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'")
    engine_dir = next((d.name for d in (config.STATIC / "assets").glob("cesium-*")), "cesium")
    headers += f"\n/assets/{engine_dir}/*\n  ! Content-Security-Policy\n  Content-Security-Policy: {engine_csp}\n"
    if not config.INDEXING:
        headers = headers.replace("/*\n", "/*\n  X-Robots-Tag: noindex, nofollow\n", 1)
    (config.PUBLIC / "_headers").write_text(headers, encoding="utf-8")


# ---------------------------------------------------------------------------

def build() -> None:
    if config.PUBLIC.exists():
        shutil.rmtree(config.PUBLIC)
    shutil.copytree(config.STATIC, config.PUBLIC)
    for f in (config.PUBLIC / "assets").glob("*.*"):
        if f.suffix in (".css", ".js", ".webp"):
            ASSET_V[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()[:10]
    PAGES.clear()

    history, latest, bulletins, disruptions, runs = load()
    DISRUPTIONS_CACHE.clear()
    DISRUPTIONS_CACHE.update(disruptions)
    map_data = build_map_data(latest, disruptions)
    ASSET_V["carte"] = hashlib.sha256(json.dumps(map_data, sort_keys=True).encode()).hexdigest()[:10]
    for lang in LANGS:
        build_map(lang, map_data)
        build_index(lang, history, latest, bulletins, disruptions)
        build_bulletins(lang, bulletins)
        build_agents(lang, runs)
        build_quality(lang, bulletins, runs)
        build_costs(lang, runs)
        build_about(lang)
        build_visitors(lang)
        build_privacy(lang)
        build_404(lang)
    build_admin()
    lh = config.DATA / "lighthouse.json"
    if lh.exists():
        shutil.copy(lh, config.PUBLIC / "admin" / "lighthouse.json")
    # Pages are registered once per language with identical alternates: keep one entry per page.
    seen, unique = set(), []
    for p in PAGES:
        key = p["alts"]["fr"]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    PAGES[:] = unique
    build_sitemap()
    print(f"Site built in {config.PUBLIC} ({len(PAGES)} pages × {len(LANGS)} languages)")


if __name__ == "__main__":
    build()
