# Transit Pulse · Lausanne

An autonomous AI pipeline that measures public transport punctuality in Lausanne every day and publishes a fact-checked bulletin in four languages, for a few dollars a month. Proof of concept before a canton of Vaud version.

**Live site:** `https://<project>.pages.dev` (Cloudflare Pages, not indexed during the pilot)

## What it does

| Every | Job | What happens |
| --- | --- | --- |
| Morning (up to 4 attempts) | `pulse.daily` | Streams yesterday's national actual-data file (≈ 500 MB), keeps Lausanne stops, computes punctuality, then three agents write, check and translate the bulletin |
| 3 hours | `pulse.hourly` | Reads the SIRI-SX disruption feed (8 calls/day on a 48 quota), keeps Lausanne situations, runs a health check |
| Push | tests | 15 offline tests, no network or API key needed |

Each run commits `data/` and `public/`; Cloudflare Pages republishes the site.

## Agents (Claude Haiku 5.5)

1. **Writer** gets a compact JSON of the day's figures, with comparisons precomputed by code so the model never calculates.
2. **Checker** reviews every sentence against the data. In parallel, **code** checks that every number written exists in the data.
3. If either refuses, the writer gets the remarks and tries once more. A second refusal blocks publication and the workflow fails, which emails the owner.
4. **Translator** produces German, Italian and English; code checks each translation has exactly the same numbers as the French text.

Every call is logged in `data/runs.jsonl` (model, tokens, cost, duration, outcome) and shown on the site's Agents, Quality and Costs pages.

## Safeguards

- API keys only in GitHub Secrets (`ANTHROPIC_API_KEY`, `OTD_API_KEY`).
- Anthropic workspace capped at USD 10/month, alert at USD 5.
- Static site: no cookies, no JavaScript, no external resources, strict CSP (`site_static/_headers`), `noindex` during the pilot.
- Data source credited on every page (opentransportdata.swiss terms of use).

## Run locally

```bash
pip install -r requirements.txt
python -m unittest -v                                   # offline tests
PULSE_FAKE_LLM=1 python -m pulse.daily --sample tests/fixtures/sample_istdaten.csv --date 2026-10-21
python -m pulse.site && python -m http.server -d public  # preview at http://localhost:8000
```

`PULSE_FAKE_LLM=1` replaces the model with deterministic answers (no API key, no cost). Delete the generated `data/` files before committing.

## Cloudflare Pages settings

- Framework preset: None
- Build command: *(empty)*
- Build output directory: `public`

## Layout

```
pulse/        collector, disruption parser, agents, fact check, site builder
prompts/      versioned prompts (a prompt change is a commit)
data/         daily aggregates, bulletins, run log (written by the jobs)
public/       generated site (served by Cloudflare Pages)
site_static/  stylesheet, headers, robots.txt
tests/        offline tests and fixtures
```

Data: [opentransportdata.swiss](https://opentransportdata.swiss/). Personal project, not affiliated with SBB/CFF, tl or any operator.
