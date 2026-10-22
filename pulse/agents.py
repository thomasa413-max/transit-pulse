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


BULLETIN_SCHEMA = {
    "type": "object",
    "properties": {
        "titre": {"type": "string"},
        "paragraphes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
    },
    "required": ["titre", "paragraphes"],
}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "problemes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "phrase": {"type": "string"},
                "raison": {"type": "string"},
                "erreur": {"type": "boolean", "description": "true only if the sentence is wrong or unsupported"},
            },
            "required": ["phrase", "raison", "erreur"]}},
    },
    "required": ["verdict", "problemes"],
}


def _log(agent: str, day: date, result: llm.LLMResult, status: str, **extra) -> None:
    util.append_run({
        "job": "daily", "agent": agent, "date": day.isoformat(), "status": status,
        "prompt_version": config.PROMPT_VERSION, **result.usage(), **extra,
    })


def _call(agent: str, day: date, system: str, user: str, **kw) -> llm.LLMResult:
    """llm.call, with API errors written to the run log before re-raising."""
    try:
        return llm.call(system, user, **kw)
    except Exception as exc:  # noqa: BLE001
        util.append_run({"job": "daily", "agent": agent, "date": day.isoformat(), "status": "error",
                         "model": kw.get("model", config.MODEL_DAILY), "prompt_version": config.PROMPT_VERSION,
                         "detail": f"{type(exc).__name__}: {exc}"[:400]})
        raise


def bulletin_text(b: dict) -> str:
    return "\n\n".join([b.get("titre", ""), *b.get("paragraphes", [])])


# ---------------------------------------------------------------------------
# Input given to the writer: a compact extract, with comparisons precomputed
# by code so the model never has to calculate.
# ---------------------------------------------------------------------------

LABELS = {
    "passages": "passages_prevus",
    "mesures": "passages_mesures",
    "suppressions": "passages_supprimes",
    "ponctualite_pct": "pct_a_l_heure",
    "retard_moyen_min": "retard_moyen_minutes",
    "suppressions_pct": "pct_supprimes",
    "retard_p90_min": "neuf_passages_sur_dix_sous_minutes",
}


def _label(item: dict, **extra) -> dict:
    """Unambiguous names for the writer: a small model misread 'passages' vs 'mesures'."""
    return {LABELS.get(k, k): v for k, v in item.items()} | extra


def _ranked(items: list[dict]) -> list[dict]:
    return [_label(x, rang=i + 1) for i, x in enumerate(items)]


def writer_input(agg: dict, history: list[dict], disruptions: list[dict]) -> dict:
    t = agg["total"]
    comparison: dict = {}
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
        "journee_entiere": _label(t),
        **({"comparaison": comparison} if comparison else {}),
        "par_mode_journee_entiere": [_label(m) for m in agg["par_mode"]],
        "heures_les_moins_ponctuelles": _ranked(worst_hours),
        "lignes_moins_ponctuelles_journee_entiere": _ranked(agg["lignes_moins_ponctuelles"][:5]),
        "lignes_plus_ponctuelles_journee_entiere": _ranked(agg["lignes_plus_ponctuelles"][:3]),
        "arrets_moins_ponctuels_journee_entiere": _ranked(agg["arrets_moins_ponctuels"][:5]),
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
    g = data["journee_entiere"]
    p = [f"Le {data['date']}, {g['pct_a_l_heure']} % des passages mesurés à Lausanne étaient à l'heure, "
         f"sur {g['passages_mesures']} passages mesurés."]
    if data["lignes_moins_ponctuelles_journee_entiere"]:
        l = data["lignes_moins_ponctuelles_journee_entiere"][0]
        p.append(f"La ligne {l['ligne']} ({l['exploitant']}) a été la moins ponctuelle, avec {l['pct_a_l_heure']} %.")
    if data["heures_les_moins_ponctuelles"]:
        h = data["heures_les_moins_ponctuelles"][0]
        p.append(f"Le créneau de {h['heure']} h a été le plus difficile ({h['pct_a_l_heure']} % à l'heure).")
    return json.dumps({"titre": f"{g['pct_a_l_heure']} % de passages à l'heure à Lausanne", "paragraphes": p},
                      ensure_ascii=False)


def _fake_checker(_user: str) -> str:
    return json.dumps({"verdict": "pass", "problemes": []})


def _fake_translate_one(user: str, lang: str) -> str:
    b = json.loads(user.split("BULLETIN:\n", 1)[1])
    return json.dumps({"titre": f"[{lang}] {b['titre']}", "paragraphes": [f"[{lang}] {x}" for x in b["paragraphes"]]},
                      ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def write(day: date, facts: dict, feedback: list[str] | None = None) -> dict:
    user = "DONNÉES:\n" + json.dumps(facts, ensure_ascii=False)
    if feedback:
        user = ("Ta version précédente a été refusée par le contrôle. Corrige ces points :\n- "
                + "\n- ".join(feedback) + "\n\n" + user)
    res = _call("writer", day, _prompt("writer"), user, model=config.MODEL_WRITER, fake_responder=_fake_writer, schema=BULLETIN_SCHEMA, max_tokens=2000)
    try:
        b = llm.parse_json(res.text)
        assert isinstance(b.get("titre"), str) and isinstance(b.get("paragraphes"), list)
    except Exception as exc:  # noqa: BLE001
        _log("writer", day, res, "error", detail=f"invalid answer ({res.extra.get('stop_reason')}): {exc}; "
                                                 f"start: {res.text[:200]!r}")
        raise
    _log("writer", day, res, "ok", attempt=2 if feedback else 1, words=len(bulletin_text(b).split()))
    return b


def check(day: date, facts: dict, bulletin: dict) -> dict:
    text = bulletin_text(bulletin)
    unknown = factcheck.unknown_numbers(text, facts, day)
    user = "DONNÉES:\n" + json.dumps(facts, ensure_ascii=False) + "\n\nBULLETIN:\n" + text
    res = _call("checker", day, _prompt("checker"), user, model=config.MODEL_CHECKER, fake_responder=_fake_checker,
                   schema=VERDICT_SCHEMA, max_tokens=1500)
    try:
        verdict = llm.parse_json(res.text)
    except Exception:  # noqa: BLE001 - an unreadable verdict is a failed check
        verdict = {"verdict": "fail", "problemes": [{"phrase": "", "raison": "réponse du contrôleur illisible"}]}
    # The verdict is decided by code from the items flagged as real errors, so a
    # self-contradicting answer ("fail" with only correct sentences) cannot block.
    problems = [p for p in (verdict.get("problemes") or []) if p.get("erreur", True)]
    model_ok = not problems
    for n in unknown:
        problems.append({"phrase": "", "raison": f"chiffre absent des données : {n:g}", "erreur": True})
    passed = model_ok and not unknown
    _log("checker", day, res, "pass" if passed else "fail",
         code_check="pass" if not unknown else "fail", model_check="pass" if model_ok else "fail",
         problems=problems[:10])
    return {"passed": passed, "problems": problems, "unknown_numbers": unknown}


LANG_NAMES = {"de": "German", "it": "Italian", "en": "English"}


def _normalise_keys(b: dict) -> dict:
    """The model sometimes translates the key itself ("paragraphen", "paragraphs")."""
    out = {}
    for k, v in b.items():
        key = "paragraphes" if k.lower().startswith("paragraph") else ("titre" if k.lower().startswith(("tit", "title")) else k)
        if key == "paragraphes" and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                v = [v]
        out[key] = v
    return out


def _translate_one(day: date, bulletin: dict, lang: str, rejected: str = "") -> tuple[dict | None, str]:
    fr_text = bulletin_text(bulletin)
    user = f"Target language: {LANG_NAMES[lang]}.\n"
    if rejected:
        user += (f"Your previous translation was rejected: {rejected}. Every number of the French text must "
                 f"appear exactly as many times as in the French text.\n")
    user += "\nBULLETIN:\n" + json.dumps(bulletin, ensure_ascii=False)
    res = _call("translator", day, _prompt("translator"), user, fake_responder=lambda u: _fake_translate_one(u, lang),
                schema=BULLETIN_SCHEMA, max_tokens=2000)
    problem = ""
    try:
        b = _normalise_keys(llm.parse_json(res.text))
        assert b.get("paragraphes")
        ok, missing, extra = factcheck.same_numbers(fr_text, bulletin_text(b))
        if not ok:
            problem = f"numbers differ (missing {missing}, extra {extra})"
    except Exception:  # noqa: BLE001
        b, problem = None, f"empty or unreadable answer ({res.extra.get('stop_reason')}): {res.text[:120]!r}"
    _log("translator", day, res, "error" if problem else "ok", language=lang, languages=[] if problem else [lang],
         problems=[f"{lang}: {problem}"] if problem else [], retry=bool(rejected))
    return (None if problem else b), problem


def translate(day: date, bulletin: dict) -> dict:
    """One call per language; a language that fails the number check is retried
    once with the reason. Only checked translations are published."""
    out = {}
    for lang in ("de", "it", "en"):
        b, problem = _translate_one(day, bulletin, lang)
        if problem:
            b, _ = _translate_one(day, bulletin, lang, rejected=problem)
        if b:
            out[lang] = b
    return out
