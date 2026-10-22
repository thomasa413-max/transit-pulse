# Transit Pulse · Lausanne

An autonomous AI pipeline that measures public transport punctuality in Lausanne every day and publishes a fact-checked bulletin in French, German, Italian and English. Proof of concept before a canton of Vaud version (and a live 3D map).

**Live site:** https://transit-pulse.thomasa413.workers.dev (not indexed during the pilot)

## What runs, and when

| Every | Job | What happens |
| --- | --- | --- |
| Morning (up to 4 attempts) | `pulse.daily` | Streams yesterday's national actual-data file (≈ 500 MB), keeps Lausanne stops, computes punctuality; writer → checker → translator agents produce the bulletin |
| 3 hours | `pulse.hourly` | SIRI-SX disruptions (8 calls/day on a 48 quota) + health check |
| Monday, and after site changes | Lighthouse | Mobile lab scores of 4 key pages; fails below target |
| Push | Tests | 28 Python tests + Worker unit tests, offline |
| Daily (Cloudflare cron) | Worker | Deletes IPs older than 90 days and statistics older than 400 days |

Each job commits `data/` and `public/`; Cloudflare redeploys.

## Agents

1. **Writer** (Claude Sonnet 5.5) gets a compact JSON with unambiguous labels, ranked lists and precomputed comparisons.
2. **Checker** (Claude Sonnet 5.5) reviews each sentence and flags errors; **code** checks every number exists in the data. The verdict is decided by code.
3. Up to two corrections with the checker's remarks; a third refusal blocks publication and fails the workflow (e-mail to the owner).
4. **Translator** (Claude Haiku 5.5), one call per language, retried once; code checks each translation has exactly the French numbers.

Every call is logged in `data/runs.jsonl` and shown on the Agents, Quality and Costs pages.

## Site

- Four languages with localised URLs (`/fr/qualite/`, `/de/qualitaet/`, `/it/qualita/`, `/en/quality/`), language menu (globe + native names), `/` redirects by cookie then browser language. Texts in `pulse/i18n.py` (Swiss German spelling).
- Display settings: text size, easier-to-read font (Atkinson Hyperlegible, self-hosted), light / dark / system theme.
- Comments under each bulletin, reviewed before publication; likes on comments. Cloudflare Turnstile loads only on interaction; one successful check sets a 12 h signed cookie that unlocks likes.
- Public visitor numbers on `/fr/visiteurs/` (not the homepage).
- Admin at `/admin/` (French): pending comments, moderation, visitor statistics (countries, referrers, pages, devices, languages), Core Web Vitals from real visits (p75, mobile / desktop) and the latest Lighthouse scores.

## Security

- Static pages, no inline script or style, strict CSP and security headers (`site_static/_headers`), HSTS, anti-framing.
- Admin: password checked in constant time, 5 attempts per 15 min, session = HMAC-signed HttpOnly Secure SameSite=Strict cookie scoped to `/api/admin` (8 h). The password is never stored in the browser.
- All writes check the `Origin` header (CSRF), body size limits, bound SQL parameters, output always inserted as text.
- Comments: Turnstile (token bound to this hostname), honeypot field, 3 per 10 min per visitor, length and word checks.
- Privacy: visit statistics are daily totals only; no tracking when Do Not Track / GPC is on; IPs on comments deleted after 90 days.
- Secrets only in GitHub and Cloudflare; Dependabot proposes updates weekly.

## Accessibility and SEO

- WCAG 2.2 AA: axe-core reports 0 violations on all page types, light and dark; 44 px targets; skip link; keyboard menus with Escape; charts drawn as SVG with a data table alternative; `lang` set on every translated block.
- SEO: canonical, reciprocal `hreflang` (+ `x-default`), Open Graph images per language, JSON-LD (WebSite, Dataset, NewsArticle, BreadcrumbList), sitemap with alternates. Lighthouse: 100 / 100 / 100 / 100 on the tested pages.

## Cloudflare setup (once)

- Workers & Pages → `transit-pulse`, connected to this repo (Workers Builds, deploy command `npx wrangler deploy`).
- D1 database `transit-pulse` (ID in `wrangler.jsonc`), Turnstile widget for the hostname (site key in `pulse/config.py`).
- Worker secrets: `TURNSTILE_SECRET`, `ADMIN_PASSWORD` (16+ chars), `SESSION_SECRET` (40+ random chars), `IP_SALT` (40+ random chars).
- GitHub secrets: `ANTHROPIC_API_KEY`, `OTD_API_KEY`.

## Go-live checklist (Vaud domain)

1. Add the domain to the Worker (Settings → Domains) and to the Turnstile widget's hostnames.
2. In `pulse/config.py`: `SITE_URL` = the new domain, `INDEXING = True`.
3. Push: robots.txt then lists the sitemap, pages become indexable, Lighthouse checks the crawlability audit again.
4. Submit the sitemap in Google Search Console and Bing Webmaster Tools (Bing also feeds DuckDuckGo, Yahoo and Ecosia).
5. Optional: Email Routing on the domain for comment notifications.

## Run locally

```bash
pip install -r requirements.txt
python -m unittest -v && node --test tests/worker.test.mjs
PULSE_FAKE_LLM=1 python -m pulse.daily --sample tests/fixtures/sample_istdaten.csv --date 2026-10-21
python -m pulse.site
npx wrangler dev --local        # site + API on http://127.0.0.1:8787 (secrets in .dev.vars, never committed)
```

Data: [opentransportdata.swiss](https://opentransportdata.swiss/). Personal project, not affiliated with SBB/CFF, tl or any operator.
