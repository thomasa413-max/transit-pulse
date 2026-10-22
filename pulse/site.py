"""Build the static site in public/ from the files in data/.

    python -m pulse.site
"""
from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape

from . import charts, config, util

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
NAV = [("/", "Tableau de bord"), ("/bulletin/", "Bulletin"), ("/agents/", "Agents"),
       ("/qualite/", "Qualité"), ("/couts/", "Coûts"), ("/a-propos/", "À propos")]
AGENT_FR = {"collector": "Collecteur", "writer": "Rédacteur", "checker": "Contrôleur",
            "translator": "Traducteur", "siri-sx": "Perturbations"}
STATUS_FR = {"ok": "Réussi", "pass": "Validé", "fail": "Refusé", "error": "Erreur",
             "partial": "Partiel", "skipped": "Ignoré"}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def n(v, dec: int = 1, unit: str = "") -> str:
    if v is None:
        return "–"
    if isinstance(v, int) or dec == 0:
        s = f"{round(v):,}".replace(",", "'")
    else:
        s = f"{v:.{dec}f}".replace(".", ",")
    return s + unit


def usd(v: float) -> str:
    if v < 0.01:
        return f"{v:.4f} $".replace(".", ",")
    return f"{v:.2f} $".replace(".", ",")


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}"


def local_time(iso_utc: str | None, with_date: bool = True) -> str:
    if not iso_utc:
        return "–"
    dt = datetime.fromisoformat(iso_utc).astimezone(config.TZ)
    return dt.strftime("%d.%m.%Y %H:%M" if with_date else "%H:%M")


def badge(status: str) -> str:
    cls = {"ok": "good", "pass": "good", "publie": "good", "fail": "bad", "error": "bad",
           "bloque": "bad", "partial": "warn", "skipped": "warn"}.get(status, "neutral")
    label = STATUS_FR.get(status, {"publie": "Publié", "bloque": "Bloqué"}.get(status, status))
    return f'<span class="badge {cls}">{escape(label)}</span>'


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_ASSET_VERSION = ""


def page(path: str, title: str, body: str, description: str) -> None:
    nav = "".join(
        f'<li><a href="{href}"{" aria-current=\"page\"" if href == path else ""}>{escape(label)}</a></li>'
        for href, label in NAV)
    full_title = config.SITE_TITLE if path == "/" else f"{title} · {config.SITE_TITLE}"
    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="description" content="{escape(description)}">
<title>{escape(full_title)}</title>
<link rel="stylesheet" href="/assets/style.css?v={_ASSET_VERSION}">
<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">
</head>
<body>
<a class="skip" href="#contenu">Aller au contenu</a>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>Transit Pulse <span class="brand-zone">Lausanne</span></a>
    <nav aria-label="Navigation principale"><ul>{nav}</ul></nav>
  </div>
</header>
<main id="contenu" class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>Données : <a href="https://opentransportdata.swiss/">opentransportdata.swiss</a> (horaires réels et perturbations des transports publics suisses). Calculs et textes générés automatiquement.</p>
    <p>Preuve de concept personnelle, sans lien avec les CFF, les tl ou les autres exploitants. <a href="{config.REPO_URL}">Code source</a></p>
  </div>
</footer>
</body>
</html>
"""
    out = config.PUBLIC / path.strip("/") / "index.html" if path != "/" else config.PUBLIC / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def section(title: str, inner: str, lead: str = "", sid: str = "") -> str:
    lead_html = f'<p class="lead-sm">{lead}</p>' if lead else ""
    return f'<section class="block"{f" id={sid!r}" if sid else ""}><h2>{escape(title)}</h2>{lead_html}{inner}</section>'


def table(headers: list[str], rows: list[list[str]], numeric_from: int = 1, caption: str = "",
          numeric_to: int = 99) -> str:
    if not rows:
        return '<p class="muted">Aucune donnée.</p>'
    num = lambda i: numeric_from <= i <= numeric_to  # noqa: E731
    th = "".join(f'<th scope="col"{" class=num" if num(i) else ""}>{escape(h)}</th>'
                 for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(
        f'<td{" class=num" if num(i) else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    cap = f'<caption class="sr-only">{escape(caption)}</caption>' if caption else ""
    return f'<div class="table-wrap"><table>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def tile(label: str, value: str, note: str = "", tone: str = "") -> str:
    return (f'<div class="tile {tone}"><p class="tile-label">{escape(label)}</p>'
            f'<p class="tile-value">{value}</p>{f"<p class=tile-note>{note}</p>" if note else ""}</div>')


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load():
    history = util.read_json(config.DATA / "history.json", []) or []
    latest = None
    if history:
        latest = util.read_json(config.DAILY_DIR / f"{history[-1]['date']}.json")
    bulletins = {}
    for p in sorted(config.BULLETIN_DIR.glob("*.json")):
        b = util.read_json(p)
        if b:
            bulletins[b["date"]] = b
    disruptions = util.read_json(config.DISRUPTION_FILE, {}) or {}
    runs = util.read_runs()
    return history, latest, bulletins, disruptions, runs


def latest_published(bulletins: dict) -> dict | None:
    pub = [b for b in bulletins.values() if b.get("statut") == "publie"]
    return max(pub, key=lambda b: b["date"]) if pub else None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def disruption_list(disruptions: dict) -> str:
    items = disruptions.get("lausanne") or []
    when = local_time(disruptions.get("mis_a_jour"))
    if not disruptions:
        return '<p class="muted">Première interrogation du flux de perturbations en attente.</p>'
    head = (f'<p class="lead-sm">Situations actives qui mentionnent Lausanne, d\'après le flux officiel SIRI-SX. '
            f'Mis à jour le {when} ; {n(disruptions.get("actives_suisse"), 0)} situations actives dans toute la Suisse.</p>')
    if not items:
        return head + '<p class="empty">Aucune perturbation signalée pour Lausanne.</p>'
    lis = []
    for s in items[:12]:
        kind = "Travaux / planifié" if s.get("planifie") else "Imprévu"
        lines = ", ".join(s.get("lignes") or [])
        period = s["periodes"][0] if s.get("periodes") else {}
        until = ""
        if period.get("fin"):
            until = f" · jusqu'au {local_time(period['fin'])}"
        desc = s.get("description") or s.get("consequence") or ""
        lis.append(
            f'<li class="disruption"><p class="d-meta"><span class="badge {"neutral" if s.get("planifie") else "warn"}">{kind}</span>'
            f'{f" <span>Lignes : {escape(lines)}</span>" if lines else ""}<span>{escape(until)}</span></p>'
            f'<p class="d-title">{escape(s.get("titre") or "Perturbation")}</p>'
            f'{f"<p class=d-desc>{escape(desc[:280])}{chr(8230) if len(desc) > 280 else str()}</p>" if desc else ""}</li>')
    return head + f'<ul class="disruptions">{"".join(lis)}</ul>'


def build_index(history, latest, bulletins, disruptions) -> None:
    hero = ('<div class="hero"><p class="eyebrow">Mesure quotidienne · automatique</p>'
            '<h1>La ponctualité des transports publics à Lausanne, chaque jour</h1>'
            '<p class="lead">Horaires réels de tous les arrêts lausannois (trains, métro, bus, bateaux), '
            'analysés chaque matin par un pipeline d\'agents IA qui rédige, vérifie et traduit le bulletin du jour.</p></div>')
    if not latest:
        body = hero + section("Première mesure en attente",
                              '<p class="empty">Le collecteur s\'exécute chaque matin. Les premiers chiffres et le premier '
                              'bulletin apparaîtront ici après son prochain passage.</p>') \
            + section("Perturbations en cours", disruption_list(disruptions))
        page("/", "Tableau de bord", body, "Ponctualité des transports publics à Lausanne, mesurée chaque jour.")
        return

    t = latest["total"]
    prev = history[-2] if len(history) >= 2 else None
    delta = ""
    if prev and prev.get("ponctualite_pct") is not None and t["ponctualite_pct"] is not None:
        d = round(t["ponctualite_pct"] - prev["ponctualite_pct"], 1)
        sign = "+" if d > 0 else ("−" if d < 0 else "±")
        delta = f"{sign}{n(abs(d))} point{'s' if abs(d) >= 2 else ''} par rapport à la veille"
    tiles = "".join([
        tile("À l'heure (moins de 3 min)", n(t["ponctualite_pct"], unit=" %"), delta, "accent"),
        tile("Retard moyen", n(t["retard_moyen_min"], unit=" min"),
             f"90 % des passages sous {n(t.get('retard_p90_min'), unit=' min')}" if t.get("retard_p90_min") is not None else ""),
        tile("Passages supprimés", n(t["suppressions"], 0), f"{n(t['suppressions_pct'], unit=' %')} des passages prévus"),
        tile("Passages mesurés", n(t["mesures"], 0), f"sur {n(t['passages'], 0)} prévus, {n(latest['nb_arrets'], 0)} arrêts"),
    ])
    body = hero + f'<p class="asof">Journée du <strong>{long_date(latest["date"])}</strong></p><div class="tiles">{tiles}</div>'

    b = latest_published(bulletins)
    if b:
        fr = b["fr"]
        body += (f'<article class="bulletin-card"><p class="eyebrow">Bulletin du {short_date(b["date"])} · '
                 f'{badge("pass")} vérifié automatiquement</p><h2><a href="/bulletin/{b["date"]}/">{escape(fr["titre"])}</a></h2>'
                 f'<p>{escape(fr["paragraphes"][0] if fr["paragraphes"] else "")}</p>'
                 f'<p><a class="more" href="/bulletin/{b["date"]}/">Lire le bulletin complet, en 4 langues</a></p></article>')

    pts = [(h["date"], h["ponctualite_pct"]) for h in history[-30:] if h.get("ponctualite_pct") is not None]
    if len(pts) >= 2:
        trend = charts.line_chart(pts, title="Part des passages à l'heure, 30 derniers jours", label_fmt=short_date)
        trend += charts.data_table(["Jour", "À l'heure"], [[long_date(d), n(v, unit=" %")] for d, v in reversed(pts)],
                                   "Ponctualité par jour")
        body += section("Évolution", trend, "Part des passages à l'heure, par jour.")
    hours = [(f"{h['heure']} h", h["ponctualite_pct"]) for h in latest["par_heure"]
             if h["mesures"] >= 30 and h["ponctualite_pct"] is not None]
    if hours:
        hour_chart = charts.line_chart(hours, title="Part des passages à l'heure selon l'heure prévue",
                                       highlight_last=False, mark_lowest=2)
        hour_chart += charts.data_table(["Heure", "À l'heure"], [[lab, n(v, unit=" %")] for lab, v in hours],
                                        "Ponctualité par heure")
        body += section("Au fil de la journée", hour_chart,
                        "Selon l'heure prévue du passage. Les deux créneaux les moins ponctuels sont mis en évidence. "
                        "Heures avec au moins 30 passages mesurés.")

    body += section("Par mode de transport", table(
        ["Mode", "À l'heure", "Retard moyen", "Supprimés", "Mesurés"],
        [[escape(m["mode"]), n(m["ponctualite_pct"], unit=" %"), n(m["retard_moyen_min"], unit=" min"),
          n(m["suppressions"], 0), n(m["mesures"], 0)] for m in latest["par_mode"]], caption="Ponctualité par mode"))
    body += '<div class="two-col">'
    body += section("Lignes les moins ponctuelles", table(
        ["Ligne", "Exploitant", "À l'heure", "Retard moyen"],
        [[f'<strong>{escape(l["ligne"])}</strong> <span class="muted">{escape(l["mode"])}</span>', escape(l["exploitant"]),
          n(l["ponctualite_pct"], unit=" %"), n(l["retard_moyen_min"], unit=" min")]
         for l in latest["lignes_moins_ponctuelles"][:8]], numeric_from=2, caption="Lignes les moins ponctuelles"),
        f"Lignes avec au moins {config.MIN_EVENTS_FOR_RANKING} passages mesurés à Lausanne.")
    body += section("Arrêts les moins ponctuels", table(
        ["Arrêt", "À l'heure", "Mesurés"],
        [[escape(s["arret"]), n(s["ponctualite_pct"], unit=" %"), n(s["mesures"], 0)]
         for s in latest["arrets_moins_ponctuels"][:8]], caption="Arrêts les moins ponctuels"))
    body += "</div>"
    if latest["plus_gros_retards"]:
        body += section("Plus gros retards mesurés", table(
            ["Retard", "Ligne", "Arrêt", "Heure prévue"],
            [[f"<strong>{n(w['retard_min'], unit=' min')}</strong>", f"{escape(w['ligne'])} ({escape(w['exploitant'])})",
              escape(w["arret"]), escape(w["heure_prevue"])] for w in latest["plus_gros_retards"]],
            numeric_from=9, caption="Plus gros retards"))
    body += section("Perturbations en cours", disruption_list(disruptions), sid="perturbations")
    body += ('<p class="method">Méthode : un passage est « à l\'heure » s\'il a moins de 3 minutes de retard, '
             'comme pour la ponctualité clients en Suisse. Seuls les horaires réellement mesurés sont pris en compte ; '
             'les estimations et prévisions sont exclues. <a href="/a-propos/#methode">En savoir plus</a></p>')
    page("/", "Tableau de bord", body, "Ponctualité des transports publics à Lausanne, mesurée chaque jour.")


def bulletin_html(b: dict) -> str:
    fr = b["fr"]
    out = [f'<article class="bulletin" lang="fr"><h1>{escape(fr["titre"])}</h1>']
    out += [f"<p>{escape(p)}</p>" for p in fr["paragraphes"]]
    out.append("</article>")
    attempts = b.get("tentatives", 1)
    check = ("Contrôle réussi du premier coup." if attempts == 1
             else "Version corrigée après les remarques du contrôle, puis validée.")
    out.append(f'<aside class="provenance"><p>{badge("pass")} Rédigé par <strong>{escape(b["modele"])}</strong> à partir '
               f'des données du jour, puis vérifié phrase par phrase par un second agent '
               f'(<strong>{escape(b.get("modele_controle", "un autre modèle"))}</strong>) et chiffre par chiffre par du code. '
               f'{check} Publié le {local_time(b["genere_a"])}.</p></aside>')
    others = [(code, label) for code, label in config.LANGS.items() if code != "fr" and b.get(code)]
    if others:
        out.append('<section class="block"><h2>Dans les autres langues</h2>')
        for code, label in others:
            t = b[code]
            out.append(f'<details class="lang-version" lang="{code}"><summary>{escape(label)}</summary>'
                       f'<h3>{escape(t["titre"])}</h3>' + "".join(f"<p>{escape(p)}</p>" for p in t["paragraphes"])
                       + "</details>")
        out.append('<p class="muted small">Traductions automatiques ; les chiffres sont comparés par code à la version française.</p></section>')
    return "".join(out)


def build_bulletins(bulletins: dict) -> None:
    for d, b in bulletins.items():
        if b.get("statut") != "publie":
            continue
        body = f'<p class="asof"><a href="/bulletin/">Bulletins</a> · {long_date(d)}</p>' + bulletin_html(b)
        page(f"/bulletin/{d}/", f"Bulletin du {short_date(d)}", body, b["fr"]["titre"])
    latest = latest_published(bulletins)
    archive = "".join(
        f'<li><a href="/bulletin/{d}/">{long_date(d)}</a> — {escape(b["fr"]["titre"])}</li>' if b.get("statut") == "publie"
        else f'<li>{long_date(d)} — {badge("bloque")} non publié, voir <a href="/qualite/">Qualité</a></li>'
        for d, b in sorted(bulletins.items(), reverse=True)[:60])
    if latest:
        body = f'<p class="asof">Dernier bulletin · {long_date(latest["date"])}</p>' + bulletin_html(latest)
    else:
        body = '<h1>Bulletin</h1><p class="empty">Aucun bulletin publié pour l\'instant.</p>'
    if archive:
        body += section("Archives", f'<ul class="archive">{archive}</ul>')
    page("/bulletin/", "Bulletin", body, "Bulletin quotidien de ponctualité, rédigé et vérifié par des agents IA.")


def build_agents(runs: list[dict], disruptions: dict) -> None:
    def last(pred):
        found = [r for r in runs if pred(r)]
        return found[-1] if found else None
    l_daily = last(lambda r: r.get("job") == "daily" and r.get("agent") == "collector")
    l_pub = last(lambda r: r.get("agent") == "translator")
    l_sx = last(lambda r: r.get("agent") == "siri-sx")
    tiles = "".join([
        tile("Dernière collecte quotidienne", local_time(l_daily["at"]) if l_daily else "–",
             badge(l_daily["status"]) if l_daily else "En attente"),
        tile("Dernier bulletin traduit", local_time(l_pub["at"]) if l_pub else "–",
             badge(l_pub["status"]) if l_pub else "En attente"),
        tile("Dernier relevé des perturbations", local_time(l_sx["at"]) if l_sx else "–",
             badge(l_sx["status"]) if l_sx else "En attente"),
    ])
    schedule = table(["Tâche", "Quand", "Ce qu'elle fait"], [
        ["Collecte + agents", "Chaque matin, jusqu'à 4 tentatives",
         "Télécharge le fichier national de la veille (≈ 500 Mo, lu en flux), calcule la ponctualité, puis lance rédaction, contrôle et traduction."],
        ["Perturbations", "Toutes les 3 heures", "Interroge le flux SIRI-SX (8 appels sur un quota de 48 par jour) et garde les situations lausannoises."],
        ["Contrôle de santé", "Toutes les 3 heures", "Déclenche une alerte e-mail si aucun bulletin n'a été publié depuis 30 heures."],
    ], numeric_from=9, caption="Planning des tâches")
    rows = []
    for r in reversed(runs[-80:]):
        tokens = f"{n(r.get('input_tokens'), 0)} / {n(r.get('output_tokens'), 0)}" if r.get("input_tokens") else "–"
        cost = usd(r["cost_usd"]) if r.get("cost_usd") else "–"
        detail = r.get("detail") or ""
        if r.get("agent") == "collector" and r.get("measured"):
            detail = f"{n(r['measured'], 0)} passages mesurés"
        elif r.get("agent") == "siri-sx" and r.get("status") == "ok":
            detail = f"{n(r.get('lausanne'), 0)} à Lausanne / {n(r.get('situations'), 0)} en Suisse"
        elif r.get("agent") == "checker" and r.get("problems"):
            detail = f"{len(r['problems'])} problème(s) relevé(s)"
        elif r.get("agent") == "translator":
            detail = ", ".join(r.get("languages") or []) or detail
        rows.append([local_time(r["at"]), escape(AGENT_FR.get(r.get("agent"), r.get("agent", ""))),
                     escape(r.get("model", "–")), n(r.get("seconds"), unit=" s"), tokens, cost,
                     badge(r.get("status", "")), escape(detail[:90])])
    body = ('<h1>Journal des agents</h1><p class="lead">Chaque exécution est enregistrée : quand, quel agent, quel modèle, '
            'combien de temps, combien de jetons, combien cela a coûté et le résultat. Rien n\'est filtré.</p>'
            f'<div class="tiles three">{tiles}</div>'
            + section("Planning", schedule)
            + section("Dernières exécutions", table(
                ["Heure", "Agent", "Modèle", "Durée", "Jetons (entrée / sortie)", "Coût", "Statut", "Détail"], rows,
                numeric_from=3, numeric_to=5, caption="Journal des exécutions")))
    page("/agents/", "Journal des agents", body, "Journal public des exécutions des agents.")


def build_quality(bulletins: dict, runs: list[dict]) -> None:
    recent = [b for d, b in bulletins.items() if d >= (date.today() - timedelta(days=30)).isoformat()]
    published = [b for b in recent if b.get("statut") == "publie"]
    blocked = [b for b in recent if b.get("statut") == "bloque"]
    corrected = [b for b in published if b.get("tentatives", 1) > 1]
    first_try = [b for b in published if b.get("tentatives", 1) == 1]
    rate = round(100 * len(first_try) / len(recent), 1) if recent else None
    checks = [r for r in runs if r.get("agent") == "checker"][-200:]
    translations = [r for r in runs if r.get("agent") == "translator" and r.get("language")][-90:]
    tr_ok = sum(1 for r in translations if r.get("status") == "ok")
    tiles = "".join([
        tile("Validés du premier coup", n(rate, unit=" %") if rate is not None else "–",
             f"{len(first_try)} bulletin(s) sur {len(recent)}, 30 derniers jours", "accent"),
        tile("Corrigés au 2e essai", n(len(corrected), 0), "Le rédacteur reçoit les remarques du contrôleur"),
        tile("Bloqués", n(len(blocked), 0), "Jamais publiés"),
        tile("Traductions acceptées", f"{tr_ok} / {len(translations)}" if translations else "–", "Essais dont les chiffres sont identiques au français"),
    ])
    fails = []
    for r in reversed(checks):
        if r.get("status") != "fail":
            continue
        for p in (r.get("problems") or [])[:4]:
            fails.append([escape(r.get("date", "")), escape(p.get("raison", "")), escape((p.get("phrase") or "")[:160])])
    body = ('<h1>Qualité</h1><p class="lead">Aucun bulletin n\'est publié sans deux contrôles indépendants : '
            'un agent relit chaque phrase face aux données, et du code vérifie que chaque chiffre écrit existe dans les données. '
            'Si l\'un des deux refuse, le rédacteur corrige, deux fois au plus ; en cas de troisième refus, rien n\'est publié et une alerte part.</p>'
            f'<div class="tiles">{tiles}</div>'
            + section("Problèmes relevés par les contrôles", table(["Journée", "Raison", "Phrase concernée"], fails, numeric_from=9,
                                                                caption="Refus du contrôle")
                      if fails else '<p class="empty">Aucun refus pour l\'instant.</p>'))
    page("/qualite/", "Qualité", body, "Taux de réussite des contrôles automatiques des bulletins.")


def build_costs(runs: list[dict]) -> None:
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
    tiles = "".join([
        tile("Ce mois-ci", usd(month_total), f"Budget plafonné à {config.MONTHLY_BUDGET_USD:.0f} $", "accent"),
        tile("Projection sur 30 jours", usd(projection), "Au rythme actuel"),
        tile("Coût d'un bulletin", usd(sum(v[3] for k, v in by_agent.items() if k in ("writer", "checker", "translator"))
                                        / max(1, by_agent["writer"][0]) if by_agent.get("writer") else 0),
             "Rédaction, contrôle et traduction"),
        tile("Hébergement et planification", "0,00 $", "Cloudflare Pages et GitHub Actions, offres gratuites"),
    ])
    last30 = [((util.now_local().date() - timedelta(days=i)).isoformat()) for i in range(29, -1, -1)]
    bars = [(short_date(d), by_day.get(d, 0.0) * 100) for d in last30]
    chart = ""
    if any(v for _, v in bars):
        chart = charts.bar_chart(bars, title="Coût IA par jour, en centimes de dollar", unit=" ¢")
        chart += charts.data_table(["Jour", "Coût"], [[d, usd(by_day.get(d, 0.0))] for d in reversed(last30) if by_day.get(d)],
                                   "Coût par jour")
    agents_rows = [[escape(AGENT_FR.get(k, k)), n(v[0], 0), n(v[1], 0), n(v[2], 0), usd(v[3])]
                   for k, v in sorted(by_agent.items(), key=lambda kv: -kv[1][3])]
    body = ('<h1>Coûts</h1><p class="lead">Chaque appel au modèle est compté au jeton près et converti au tarif public de l\'API. '
            'La rédaction et le contrôle utilisent Claude Sonnet 5.5, la traduction (vérifiée par du code) le plus petit modèle, Haiku 5.5 ; un plafond mensuel coupe tout dépassement.</p>'
            + (f'<p class="notice">Données de démonstration : ces coûts viennent d\'une exécution de test hors ligne.</p>' if fake else "")
            + f'<div class="tiles">{tiles}</div>'
            + (section("Coût par jour", chart, "En centimes de dollar américain, 30 derniers jours.") if chart else "")
            + section("Par agent, depuis le début", table(["Agent", "Appels", "Jetons en entrée", "Jetons en sortie", "Coût"],
                                                          agents_rows, caption="Coût par agent"))
            + '<p class="method">Tarifs utilisés : Claude Haiku 5.5, 0,10 $ par million de jetons en entrée et 0,50 $ en sortie ; '
              'Claude Sonnet 5.5 (rédacteur et contrôleur), 2 $ et 10 $ '
              '(<a href="https://platform.claude.com/docs/en/about-claude/pricing">grille tarifaire officielle</a>).</p>')
    page("/couts/", "Coûts", body, "Coût de fonctionnement du pipeline d'agents IA.")


ARCH_SVG = """<svg class="diagram" viewBox="0 0 720 400" role="img" aria-label="Chaque exécution collecte, rédige, vérifie, puis publie">
<title>Chaque exécution collecte, rédige, vérifie, puis publie</title>
<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="arrowhead"/></marker></defs>
<g class="box"><rect x="16" y="16" width="216" height="56" rx="8"/><text x="28" y="40" class="b">Horaires réels (Ist-Daten)</text><text x="28" y="58">Fichier national, chaque jour</text></g>
<g class="box"><rect x="252" y="16" width="216" height="56" rx="8"/><text x="264" y="40" class="b">Perturbations SIRI-SX</text><text x="264" y="58">Toutes les 3 heures</text></g>
<g class="box"><rect x="488" y="16" width="216" height="56" rx="8"/><text x="500" y="40" class="b">GitHub Actions</text><text x="500" y="58">Planification, aucun serveur</text></g>
<g class="box"><rect x="16" y="112" width="688" height="56" rx="8"/><text x="28" y="136" class="b">Collecteur Python</text><text x="28" y="154">Lit le fichier en flux, garde Lausanne, calcule ponctualité, retards, suppressions</text></g>
<g class="box group"><rect x="16" y="208" width="688" height="96" rx="8"/><text x="28" y="230" class="b">Agents IA · Claude Sonnet 5.5 (rédaction, contrôle) et Haiku 5.5 (traduction)</text>
<rect x="32" y="244" width="200" height="48" rx="8" class="inner"/><text x="44" y="266" class="b">Rédacteur</text><text x="44" y="282">Sonnet 5.5, en français</text>
<rect x="260" y="244" width="200" height="48" rx="8" class="inner"/><text x="272" y="266" class="b">Contrôleur + code</text><text x="272" y="282">Sonnet 5.5 : phrases ; code : chiffres</text>
<rect x="488" y="244" width="200" height="48" rx="8" class="inner"/><text x="500" y="266" class="b">Traducteur</text><text x="500" y="282">Haiku 5.5 : de, it, en</text></g>
<g class="box"><rect x="16" y="336" width="320" height="48" rx="8"/><text x="28" y="358" class="b">Refusé deux fois</text><text x="28" y="374">Rien n'est publié, alerte e-mail</text></g>
<g class="box accent"><rect x="384" y="336" width="320" height="48" rx="8"/><text x="396" y="358" class="b">Site statique · Cloudflare Pages</text><text x="396" y="374">Publié après chaque exécution réussie</text></g>
<g class="links"><path d="M124 72V112" marker-end="url(#arr)"/><path d="M360 72V112" marker-end="url(#arr)"/><path d="M360 168V208" marker-end="url(#arr)"/>
<path d="M232 268H260" marker-end="url(#arr)"/><path d="M460 268H488" marker-end="url(#arr)"/><path d="M176 304V336" marker-end="url(#arr)"/><path d="M544 304V336" marker-end="url(#arr)"/></g>
</svg>"""


def build_about() -> None:
    body = f"""<h1>À propos</h1>
<p class="lead">Transit Pulse est une preuve de concept : un pipeline d'agents IA qui fonctionne seul, 24 heures sur 24, sur des données publiques réelles, pour quelques dollars par mois. Lausanne d'abord ; le canton de Vaud ensuite.</p>
{section("Architecture", ARCH_SVG + '<p class="muted small">Le code, les données agrégées et le journal vivent dans un dépôt GitHub public. Chaque exécution réussie ajoute un commit, et Cloudflare Pages republie le site.</p>')}
{section("Méthode", '''<ul class="plain">
<li><strong>Périmètre</strong> : tous les arrêts dont le nom commence par « Lausanne » (gare, métro, bus tl, bateaux), tous exploitants confondus.</li>
<li><strong>À l'heure</strong> : moins de 3 minutes de retard, comme la ponctualité clients en Suisse. Le départ est utilisé s'il a été mesuré, sinon l'arrivée.</li>
<li><strong>Mesuré seulement</strong> : seuls les horaires de statut « réel » comptent ; les estimations et prévisions sont exclues. Les retards de plus de 5 heures sont traités comme des erreurs de données.</li>
<li><strong>Suppressions</strong> : passages annoncés comme supprimés dans le fichier officiel.</li>
<li><strong>Aucune cause inventée</strong> : le bulletin ne cite une perturbation que si elle figure dans le flux officiel, sans affirmer qu'elle explique les chiffres.</li>
</ul>''', sid="methode")}
{section("Garde-fous", '''<ul class="plain">
<li>Deux contrôles indépendants avant publication : un agent relit chaque phrase, du code vérifie chaque chiffre.</li>
<li>Jusqu'à deux corrections automatiques ; au troisième refus, rien n'est publié et une alerte e-mail part.</li>
<li>Plafond de dépense de 10 $ par mois sur l'espace de travail de l'API, alerte à 5 $.</li>
<li>Clés d'API uniquement dans les secrets GitHub, jamais dans le code.</li>
<li>Quota du flux de perturbations protégé par un compteur (8 appels prévus sur 48 autorisés).</li>
<li>Site statique sans cookie, sans script, sans ressource externe ; non indexé par les moteurs de recherche pendant la phase pilote.</li>
</ul>''')}
{section("Sources", '<p>Données ouvertes de la <a href="https://opentransportdata.swiss/">plateforme suisse des données de mobilité</a> : fichier quotidien des horaires réels (Ist-Daten) et flux des perturbations (SIRI-SX). Réutilisation autorisée avec mention de la source.</p>')}
{section("Auteur", f'<p>Conçu et piloté par Michaël Miguel, chef de projet digital certifié PMP, avec Claude comme partenaire de développement. <a href="{config.REPO_URL}">Code source sur GitHub</a>.</p>')}
"""
    page("/a-propos/", "À propos", body, "Architecture, méthode et garde-fous de Transit Pulse.")


def build() -> None:
    global _ASSET_VERSION
    if config.PUBLIC.exists():
        shutil.rmtree(config.PUBLIC)
    shutil.copytree(config.STATIC, config.PUBLIC)
    css = (config.STATIC / "assets" / "style.css").read_bytes()
    _ASSET_VERSION = hashlib.sha256(css).hexdigest()[:10]

    history, latest, bulletins, disruptions, runs = load()
    build_index(history, latest, bulletins, disruptions)
    build_bulletins(bulletins)
    build_agents(runs, disruptions)
    build_quality(bulletins, runs)
    build_costs(runs)
    build_about()
    print(f"Site built in {config.PUBLIC}")


if __name__ == "__main__":
    build()
