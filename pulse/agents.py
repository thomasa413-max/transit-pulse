"""The three daily agents: writer, fact checker, translator.

Each agent has one job, so a failure always points to one step. Every call is
written to the run log with its model, tokens, cost, duration and outcome.
"""
from __future__ import annotations

import json
from datetime import date

from . import config, factcheck, llm, util


def _prompt(name: str) -> str:
    return (config.PROMPTS / f"{name}_{config.PROMPT_VERSION}.md").read_text(encoding="utf-8")


def _log(agent: str, day: date, result: llm.LLMResult, status: str, **extra) -> None:
    util.append_run({
        "job": "daily", "agent": agent, "date": day.isoformat(), "status": status,
        "prompt_version": config.PROMPT_VERSION, **result.usage(), **extra,
    })


def bulletin_text(b: dict) -> str:
    return "\n\n".join([b.get("titre", ""), *b.get("paragraphes", [])])


# ---------------------------------------------------------------------------
# Input given to the writer: a compact extract, with comparisons precomputed
# by code so the model never has to calculate.
# ---------------------------------------------------------------------------

def writer_input(agg: dict, history: list[dict], disruptions: list[dict]) -> dict:
    t = agg["total"]
    comparison = {}
    prev = [h for h in history if h["date"] < agg["date"]]
    if prev and prev[-1].get("ponctualite_pct") is not None and t["ponctualite_pct"] is not None:
        comparison["ponctualite_veille_pct"] = prev[-1]["ponctualite_pct"]
        comparison["ecart_vs_veille_points"] = round(t["ponctualite_pct"] - prev[-1]["ponctualite_pct"], 1)
    last7 = [h["ponctualite_pct"] for h in prev[-7:] if h.get("ponctualite_pct") is not None]
    if len(last7) >= 3 and t["ponctualite_pct"] is not None:
        avg = round(sum(last7) / len(last7), 1)
        comparison["moyenne_7_jours_precedents_pct"] = avg
        comparison["ecart_vs_moyenne_7j_points"] = round(t["ponctualite_pct"] - avg, 1)
        comparison["jours_dans_la_moyenne"] = len(last7)
    hours = [h for h in agg["par_heure"] if h["mesures"] >= 30 and h["ponctualite_pct"] is not None]
    worst_hours = sorted(hours, key=lambda h: h["ponctualite_pct"])[:3]
    return {
        "date": agg["date"],
        "zone": agg["zone"],
        "regle": agg["regle_ponctualite"],
        "global": t,
        "comparaison": comparison,
        "par_mode": agg["par_mode"],
        "heures_les_moins_ponctuelles": worst_hours,
        "lignes_moins_ponctuelles": agg["lignes_moins_ponctuelles"][:5],
        "lignes_plus_ponctuelles": agg["lignes_plus_ponctuelles"][:3],
        "arrets_moins_ponctuels": agg["arrets_moins_ponctuels"][:5],
        "plus_gros_retards": agg["plus_gros_retards"][:3],
        "perturbations_signalees": [
            {"titre": d["titre"], "planifiee": d["planifie"]} for d in disruptions[:5] if d.get("titre")
        ],
    }


# ---------------------------------------------------------------------------
# Fake responses for offline runs (PULSE_FAKE_LLM=1)
# ---------------------------------------------------------------------------

def _fake_writer(user: str) -> str:
    data = json.loads(user.split("DONNÉES:\n", 1)[1])
    g = data["global"]
    p = [f"Le {data['date']}, {g['ponctualite_pct']} % des passages mesurés à Lausanne étaient à l'heure, "
         f"sur {g['mesures']} passages mesurés."]
    if data["lignes_moins_ponctuelles"]:
        l = data["lignes_moins_ponctuelles"][0]
        p.append(f"La ligne {l['ligne']} ({l['exploitant']}) a été la moins ponctuelle, avec {l['ponctualite_pct']} %.")
    if data["heures_les_moins_ponctuelles"]:
        h = data["heures_les_moins_ponctuelles"][0]
        p.append(f"Le créneau de {h['heure']} h a été le plus difficile ({h['ponctualite_pct']} % à l'heure).")
    return json.dumps({"titre": f"{g['ponctualite_pct']} % de passages à l'heure à Lausanne", "paragraphes": p},
                      ensure_ascii=False)


def _fake_checker(_user: str) -> str:
    return json.dumps({"verdict": "pass", "problemes": []})


def _fake_translator(user: str) -> str:
    b = json.loads(user.split("BULLETIN:\n", 1)[1])
    return json.dumps({lang: {"titre": f"[{lang}] {b['titre']}",
                              "paragraphes": [f"[{lang}] {x}" for x in b["paragraphes"]]}
                       for lang in ("de", "it", "en")}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def write(day: date, facts: dict, feedback: list[str] | None = None) -> dict:
    user = "DONNÉES:\n" + json.dumps(facts, ensure_ascii=False)
    if feedback:
        user = ("Ta version précédente a été refusée par le contrôle. Corrige ces points :\n- "
                + "\n- ".join(feedback) + "\n\n" + user)
    res = llm.call(_prompt("writer"), user, fake_responder=_fake_writer)
    try:
        b = llm.parse_json(res.text)
        assert isinstance(b.get("titre"), str) and isinstance(b.get("paragraphes"), list)
    except Exception as exc:  # noqa: BLE001
        _log("writer", day, res, "error", detail=f"invalid JSON: {exc}")
        raise
    _log("writer", day, res, "ok", attempt=2 if feedback else 1, words=len(bulletin_text(b).split()))
    return b


def check(day: date, facts: dict, bulletin: dict) -> dict:
    text = bulletin_text(bulletin)
    unknown = factcheck.unknown_numbers(text, facts, day)
    user = "DONNÉES:\n" + json.dumps(facts, ensure_ascii=False) + "\n\nBULLETIN:\n" + text
    res = llm.call(_prompt("checker"), user, fake_responder=_fake_checker, max_tokens=800)
    try:
        verdict = llm.parse_json(res.text)
    except Exception:  # noqa: BLE001 - an unreadable verdict is a failed check
        verdict = {"verdict": "fail", "problemes": [{"phrase": "", "raison": "réponse du contrôleur illisible"}]}
    problems = list(verdict.get("problemes") or [])
    for n in unknown:
        problems.append({"phrase": "", "raison": f"chiffre absent des données : {n:g}"})
    passed = verdict.get("verdict") == "pass" and not unknown
    _log("checker", day, res, "pass" if passed else "fail",
         code_check="pass" if not unknown else "fail", model_check=verdict.get("verdict"),
         problems=problems[:10])
    return {"passed": passed, "problems": problems, "unknown_numbers": unknown}


def translate(day: date, bulletin: dict) -> dict:
    user = "BULLETIN:\n" + json.dumps(bulletin, ensure_ascii=False)
    res = llm.call(_prompt("translator"), user, fake_responder=_fake_translator, max_tokens=2500)
    out, problems = {}, []
    try:
        data = llm.parse_json(res.text)
    except Exception:  # noqa: BLE001
        data = {}
        problems.append("réponse illisible")
    fr_text = bulletin_text(bulletin)
    for lang in ("de", "it", "en"):
        b = data.get(lang)
        if not isinstance(b, dict) or not b.get("paragraphes"):
            problems.append(f"{lang}: manquant")
            continue
        ok, missing, extra = factcheck.same_numbers(fr_text, bulletin_text(b))
        if ok:
            out[lang] = b
        else:
            problems.append(f"{lang}: chiffres différents (manquants {missing}, en trop {extra})")
    _log("translator", day, res, "ok" if not problems else "partial",
         languages=sorted(out), problems=problems)
    return out
