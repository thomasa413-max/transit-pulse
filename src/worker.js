// Transit Pulse: Cloudflare Worker in front of the static site.
//
//   /                         redirect to the visitor's language (cookie, then browser language, then French)
//   /bulletin/... (old URLs)  permanent redirect to /fr/...
//   POST /api/visit           anonymous visit totals per day (no IP, no identifier)
//   GET  /api/visitors        public visitor numbers
//   GET  /api/weather         current weather in Lausanne (Open-Meteo, cached 15 min)
//   POST /api/vitals          Core Web Vitals from real visits, stored as daily histograms
//   POST /api/human           verifies a Turnstile token, sets a short signed "human" cookie (unlocks likes)
//   GET  /api/comments        approved comments of one bulletin
//   POST /api/comments        new comment (Turnstile + rate limit), waits for approval
//   POST /api/comments/like   like / unlike (needs the human cookie)
//   /api/admin/*              login (signed HttpOnly session cookie), moderation, statistics, performance
//   cron (daily)              deletes IPs older than 90 days, statistics older than 400 days
//
// Required Cloudflare settings: D1 binding DB; secrets TURNSTILE_SECRET, ADMIN_PASSWORD,
// SESSION_SECRET, IP_SALT. Everything else is served from public/ (see wrangler.jsonc).

export const LANGS = ["fr", "de", "it", "en"];
const DEFAULT_LANG = "fr";
const MAX_BODY = 8 * 1024;
const MAX_NAME = 40, MIN_NAME = 2;
const MAX_MESSAGE = 1000, MIN_MESSAGE = 20, MIN_WORDS = 3;
const COMMENTS_PER_WINDOW = 3, COMMENT_WINDOW_MIN = 10;
const LIKES_PER_HOUR = 60;
const LOGIN_ATTEMPTS = 5, LOGIN_WINDOW_MIN = 15;
const ADMIN_SESSION_S = 8 * 3600, HUMAN_S = 12 * 3600;
const IP_RETENTION_DAYS = 90, STATS_RETENTION_DAYS = 400;
const THREAD_RE = /^\d{4}-\d{2}-\d{2}$/;
const BOT_UA = /bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|curl|wget|python|monitor|axios|go-http/i;

const LEGACY = { "/bulletin/": "/fr/bulletin/", "/agents/": "/fr/agents/", "/qualite/": "/fr/qualite/",
  "/couts/": "/fr/couts/", "/a-propos/": "/fr/a-propos/" };

// Core Web Vitals: bucket edges (ms, CLS × 1000) and Google's good / poor thresholds.
export const VITALS = {
  LCP: { edges: [500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 7000, 10000], good: 2500, poor: 4000 },
  INP: { edges: [50, 100, 150, 200, 300, 500, 750, 1000, 2000], good: 200, poor: 500 },
  CLS: { edges: [25, 50, 75, 100, 150, 250, 400, 1000], good: 100, poor: 250 },
  FCP: { edges: [500, 1000, 1500, 1800, 2500, 3000, 4000, 6000], good: 1800, poor: 3000 },
  TTFB: { edges: [200, 400, 600, 800, 1200, 1800, 3000, 5000], good: 800, poor: 1800 },
};

// ---------------------------------------------------------------- helpers
const API_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Referrer-Policy": "strict-origin-when-cross-origin",
};

// Same policy as public/_headers, for the pages this Worker serves itself (404).
const PAGE_SECURITY = {
  "Content-Security-Policy": "default-src 'none'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Robots-Tag": "noindex",
  "Cache-Control": "no-store",
};

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), { status, headers: { ...API_HEADERS, ...extra } });
}

export function pickLang(request) {
  const cookie = request.headers.get("Cookie") || "";
  const m = cookie.match(/(?:^|;\s*)lang=([a-z]{2})(?:;|$)/);
  if (m && LANGS.includes(m[1])) return m[1];
  const prefs = (request.headers.get("Accept-Language") || "").split(",").map((part) => {
    const [tag, q] = part.trim().split(";q=");
    return { lang: tag.toLowerCase().split("-")[0], q: q ? parseFloat(q) : 1 };
  }).filter((p) => p.lang).sort((a, b) => b.q - a.q);
  for (const p of prefs) if (LANGS.includes(p.lang)) return p.lang;
  return DEFAULT_LANG;
}

export async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function hmac(secret, text) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(text));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Signed value "expiry.signature"; the signed text also binds a context (e.g. the visitor's IP hash).
export async function signToken(secret, purpose, seconds, context = "", now = Date.now()) {
  const exp = Math.floor(now / 1000) + seconds;
  return `${exp}.${await hmac(secret, `${purpose}.${exp}.${context}`)}`;
}

export async function verifyToken(secret, purpose, token, context = "", now = Date.now()) {
  if (!secret || secret.length < 32 || typeof token !== "string") return false;
  const [expStr, sig] = token.split(".");
  const exp = Number(expStr);
  if (!Number.isInteger(exp) || exp < Math.floor(now / 1000) || !sig) return false;
  return timingSafeEqual(sig, await hmac(secret, `${purpose}.${exp}.${context}`));
}

function cookieValue(request, name) {
  const m = (request.headers.get("Cookie") || "").match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return m ? m[1] : "";
}

function ipOf(request) { return request.headers.get("CF-Connecting-IP") || ""; }

async function ipHash(request, env, purpose = "") {
  return sha256(`${purpose}:${env.IP_SALT || ""}:${ipOf(request)}`);
}

function countryOf(request) {
  const c = String((request.cf && request.cf.country) || request.headers.get("CF-IPCountry") || "").toUpperCase();
  return /^[A-Z]{2}$/.test(c) && c !== "XX" && c !== "T1" ? c : null;
}

// State-changing requests must come from this site (blocks cross-site form posts and CSRF).
function sameOrigin(request, url, { allowMissing = false } = {}) {
  const origin = request.headers.get("Origin");
  if (!origin) return allowMissing;
  return origin === url.origin;
}

async function readJson(request) {
  const len = Number(request.headers.get("Content-Length") || 0);
  if (len > MAX_BODY) throw new Error("too_large");
  const text = await request.text();
  if (text.length > MAX_BODY) throw new Error("too_large");
  return text ? JSON.parse(text) : {};
}

export function clean(text, max) {
  return String(text || "")
    .normalize("NFC")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F​-‏‪-‮⁦-⁩]/g, "")
    .replace(/\r\n?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, max);
}

export function validComment(name, message) {
  if (name.length < MIN_NAME) return "name";
  const words = message.split(/\s+/).filter((w) => /\p{L}{2,}/u.test(w)).length;
  if (message.length < MIN_MESSAGE || words < MIN_WORDS) return "empty";
  if ((message.match(/https?:\/\//gi) || []).length > 2) return "links";
  return null;
}

async function verifyTurnstile(token, request, secret) {
  if (!token || !secret || typeof token !== "string" || token.length > 2048) return false;
  const body = new FormData();
  body.append("secret", secret);
  body.append("response", token);
  const ip = ipOf(request);
  if (ip) body.append("remoteip", ip);
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body });
    if (!r.ok) return false;
    const data = await r.json();
    // The token must have been issued for this site (blocks tokens solved on another site).
    const host = new URL(request.url).hostname;
    return data.success === true && (!data.hostname || data.hostname === host);
  } catch {
    return false; // verification service unreachable: refuse, never let it through
  }
}

function cookie(name, value, maxAge, path = "/", sameSite = "Strict") {
  return `${name}=${value}; Path=${path}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=${sameSite}`;
}

// ---------------------------------------------------------------- database
let schemaReady = false;
async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS comments (
      id INTEGER PRIMARY KEY AUTOINCREMENT, thread TEXT NOT NULL, created_at TEXT NOT NULL,
      name TEXT NOT NULL, message TEXT NOT NULL, lang TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', ip_hash TEXT NOT NULL, ip TEXT, country TEXT)`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_comments_thread ON comments(thread, status)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_comments_ip ON comments(ip_hash, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS comment_likes (
      comment_id INTEGER NOT NULL, voter TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (comment_id, voter))`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_likes_voter ON comment_likes(voter, created_at)"),
    db.prepare("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS visit_stats (
      day TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, kind, key))`),
    db.prepare(`CREATE TABLE IF NOT EXISTS vitals (
      day TEXT NOT NULL, metric TEXT NOT NULL, device TEXT NOT NULL, bucket INTEGER NOT NULL, n INTEGER NOT NULL,
      PRIMARY KEY (day, metric, device, bucket))`),
    db.prepare("CREATE TABLE IF NOT EXISTS login_attempts (ip_hash TEXT NOT NULL, at TEXT NOT NULL)"),
  ]);
  schemaReady = true;
}

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

// ---------------------------------------------------------------- statistics
function deviceOf(ua) {
  if (/ipad|tablet|kindle|silk|(android(?!.*mobile))/i.test(ua)) return "tablette";
  if (/mobi|iphone|ipod|android/i.test(ua)) return "mobile";
  return "ordinateur";
}

export function refererHost(ref, host) {
  if (!ref) return "direct";
  try {
    const h = new URL(ref).hostname.replace(/^www\./, "").toLowerCase();
    if (!h) return "direct";
    if (h === host.replace(/^www\./, "")) return null; // internal navigation
    return h.slice(0, 80);
  } catch { return "direct"; }
}

async function handleVisit(request, env, url) {
  const ua = request.headers.get("User-Agent") || "";
  if (BOT_UA.test(ua) || !sameOrigin(request, url, { allowMissing: true })) return json({ ok: true });
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  const path = String(data.path || "").slice(0, 120);
  if (!/^\/(fr|de|it|en)\/[a-z0-9\-/]*$/.test(path)) return json({ ok: true });
  await ensureSchema(env.DB);
  const day = today();
  const seenToday = cookieValue(request, "tp_d") === day;
  const known = cookieValue(request, "tp_v") === "1";
  const stmts = [];
  const up = (kind, key) => stmts.push(env.DB.prepare(
    "INSERT INTO visit_stats (day, kind, key, n) VALUES (?, ?, ?, 1) ON CONFLICT(day, kind, key) DO UPDATE SET n = n + 1"
  ).bind(day, kind, key));
  up("views", "");
  up("page", path);
  up("lang", path.slice(1, 3));
  const cookies = [];
  if (!seenToday) {
    up("visitors", "");
    up("country", countryOf(request) || "??");
    const ref = refererHost(String(data.ref || ""), url.hostname);
    if (ref) up("referrer", ref);
    up("device", deviceOf(ua));
    if (!known) {
      up("new", "");
      stmts.push(env.DB.prepare("INSERT INTO counters (name, value) VALUES ('visitors', 1) ON CONFLICT(name) DO UPDATE SET value = value + 1"));
      cookies.push(cookie("tp_v", "1", 31536000, "/", "Lax"));
    }
    cookies.push(cookie("tp_d", day, 86400, "/", "Lax"));
  }
  await env.DB.batch(stmts);
  const res = json({ ok: true });
  for (const c of cookies) res.headers.append("Set-Cookie", c);
  return res;
}

async function handleVisitors(env) {
  await ensureSchema(env.DB);
  const since = daysAgo(29);
  const { results } = await env.DB.prepare(
    "SELECT day, n FROM visit_stats WHERE kind = 'visitors' AND day >= ? ORDER BY day").bind(since).all();
  const total = await env.DB.prepare("SELECT value FROM counters WHERE name = 'visitors'").first();
  const day = today();
  return json({
    total: total ? total.value : 0,
    today: (results.find((r) => r.day === day) || { n: 0 }).n,
    last30: results.reduce((s, r) => s + r.n, 0),
    daily: results,
  }, 200, { "Cache-Control": "public, max-age=300" });
}

export function bucketOf(metric, value) {
  const e = VITALS[metric].edges;
  for (let i = 0; i < e.length; i++) if (value <= e[i]) return i;
  return e.length;
}

async function handleVitals(request, env, url) {
  const ua = request.headers.get("User-Agent") || "";
  if (BOT_UA.test(ua) || !sameOrigin(request, url, { allowMissing: true })) return json({ ok: true });
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  const device = data.device === "mobile" ? "mobile" : "desktop";
  const metrics = Array.isArray(data.metrics) ? data.metrics.slice(0, 6) : [];
  const day = today();
  const stmts = [];
  for (const m of metrics) {
    const value = Number(m && m.value);
    if (!VITALS[m && m.name] || !Number.isFinite(value) || value < 0 || value > 600000) continue;
    stmts.push(env.DB.prepare(
      "INSERT INTO vitals (day, metric, device, bucket, n) VALUES (?, ?, ?, ?, 1) ON CONFLICT(day, metric, device, bucket) DO UPDATE SET n = n + 1"
    ).bind(day, m.name, device, bucketOf(m.name, value)));
  }
  if (stmts.length) { await ensureSchema(env.DB); await env.DB.batch(stmts); }
  return json({ ok: true });
}

// ---------------------------------------------------------------- weather
// Open-Meteo (MeteoSwiss ICON-CH model, CC BY 4.0), fetched by the server and cached 15 min:
// visitors' IP addresses never reach Open-Meteo, and the free quota is barely used.
const WEATHER_URL = "https://api.open-meteo.com/v1/forecast?latitude=46.5197&longitude=6.6323"
  + "&current=temperature_2m,weather_code,wind_speed_10m,precipitation,cloud_cover,is_day"
  + "&daily=sunrise,sunset&forecast_days=1&timezone=Europe%2FZurich&models=meteoswiss_icon_ch1";

async function handleWeather(ctx) {
  const cache = caches.default;
  const key = new Request("https://cache.transit-pulse/weather-v1");
  const hit = await cache.match(key);
  if (hit) return new Response(hit.body, { headers: { ...API_HEADERS, "Cache-Control": "public, max-age=300" } });
  const r = await fetch(WEATHER_URL, { headers: { "User-Agent": "transit-pulse/1.0" } });
  if (!r.ok) return json({ error: "upstream" }, 502);
  const d = await r.json();
  const body = JSON.stringify({ current: d.current, daily: d.daily, source: "Open-Meteo, MeteoSwiss ICON-CH (CC BY 4.0)" });
  ctx.waitUntil(cache.put(key, new Response(body, { headers: { "Cache-Control": "public, max-age=900", "Content-Type": "application/json" } })));
  return new Response(body, { headers: { ...API_HEADERS, "Cache-Control": "public, max-age=300" } });
}

// ---------------------------------------------------------------- bot check and comments
async function handleHuman(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: "origin" }, 403);
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  if (!(await verifyTurnstile(data.token, request, env.TURNSTILE_SECRET))) return json({ error: "captcha" }, 403);
  const ctx = await ipHash(request, env, "human");
  const res = json({ ok: true });
  res.headers.append("Set-Cookie", cookie("tp_h", await signToken(env.SESSION_SECRET, "human", HUMAN_S, ctx), HUMAN_S, "/api"));
  return res;
}

async function isHuman(request, env) {
  return verifyToken(env.SESSION_SECRET, "human", cookieValue(request, "tp_h"), await ipHash(request, env, "human"));
}

async function listComments(request, env, url) {
  const thread = url.searchParams.get("thread") || "";
  if (!THREAD_RE.test(thread)) return json({ error: "invalid" }, 400);
  await ensureSchema(env.DB);
  const voter = await ipHash(request, env, "like");
  const { results } = await env.DB.prepare(
    `SELECT c.id, c.created_at, c.name, c.message, c.lang,
       (SELECT COUNT(*) FROM comment_likes l WHERE l.comment_id = c.id) AS likes,
       EXISTS (SELECT 1 FROM comment_likes l WHERE l.comment_id = c.id AND l.voter = ?) AS liked
     FROM comments c WHERE c.thread = ? AND c.status = 'approved' ORDER BY c.id ASC LIMIT 300`
  ).bind(voter, thread).all();
  return json({ comments: results });
}

async function postComment(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: "origin" }, 403);
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  if (data.website) return json({ error: "invalid" }, 400); // honeypot field, only bots fill it
  const thread = String(data.thread || "");
  if (!THREAD_RE.test(thread)) return json({ error: "invalid" }, 400);
  const lang = LANGS.includes(data.lang) ? data.lang : DEFAULT_LANG;
  const name = clean(data.name, MAX_NAME).replace(/\s+/g, " ");
  const message = clean(data.message, MAX_MESSAGE);
  const problem = validComment(name, message);
  if (problem) return json({ error: problem === "links" ? "empty" : problem }, 400);
  if (!(await verifyTurnstile(data.token, request, env.TURNSTILE_SECRET))) return json({ error: "captcha" }, 403);

  await ensureSchema(env.DB);
  const hash = await ipHash(request, env, "comment");
  const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM comments WHERE ip_hash = ? AND created_at > ?")
    .bind(hash, new Date(Date.now() - COMMENT_WINDOW_MIN * 60000).toISOString()).first();
  if (recent && recent.n >= COMMENTS_PER_WINDOW) return json({ error: "rate" }, 429);
  await env.DB.prepare(
    "INSERT INTO comments (thread, created_at, name, message, lang, status, ip_hash, ip, country) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)"
  ).bind(thread, new Date().toISOString(), name, message, lang, hash, ipOf(request) || null, countryOf(request)).run();
  // A successful bot check also unlocks likes for this visit.
  const res = json({ pending: true }, 201);
  res.headers.append("Set-Cookie", cookie("tp_h", await signToken(env.SESSION_SECRET, "human", HUMAN_S, await ipHash(request, env, "human")), HUMAN_S, "/api"));
  return res;
}

async function toggleLike(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: "origin" }, 403);
  if (!(await isHuman(request, env))) return json({ error: "human" }, 403);
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  const id = Number(data.id);
  if (!Number.isInteger(id) || id < 1) return json({ error: "invalid" }, 400);
  await ensureSchema(env.DB);
  const visible = await env.DB.prepare("SELECT 1 AS ok FROM comments WHERE id = ? AND status = 'approved'").bind(id).first();
  if (!visible) return json({ error: "not_found" }, 404);
  const voter = await ipHash(request, env, "like");
  const existing = await env.DB.prepare("SELECT 1 AS ok FROM comment_likes WHERE comment_id = ? AND voter = ?").bind(id, voter).first();
  if (existing) {
    await env.DB.prepare("DELETE FROM comment_likes WHERE comment_id = ? AND voter = ?").bind(id, voter).run();
  } else {
    const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM comment_likes WHERE voter = ? AND created_at > ?")
      .bind(voter, new Date(Date.now() - 3600000).toISOString()).first();
    if (recent && recent.n >= LIKES_PER_HOUR) return json({ error: "rate" }, 429);
    await env.DB.prepare("INSERT OR IGNORE INTO comment_likes (comment_id, voter, created_at) VALUES (?, ?, ?)")
      .bind(id, voter, new Date().toISOString()).run();
  }
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM comment_likes WHERE comment_id = ?").bind(id).first();
  return json({ likes: row ? row.n : 0, liked: !existing });
}

// ---------------------------------------------------------------- admin
async function isAdmin(request, env) {
  return verifyToken(env.SESSION_SECRET, "admin", cookieValue(request, "tp_admin"));
}

async function adminLogin(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: "origin" }, 403);
  if (!env.ADMIN_PASSWORD || env.ADMIN_PASSWORD.length < 16 || !env.SESSION_SECRET || env.SESSION_SECRET.length < 32) {
    return json({ error: "not_configured" }, 503);
  }
  await ensureSchema(env.DB);
  const hash = await ipHash(request, env, "login");
  const since = new Date(Date.now() - LOGIN_WINDOW_MIN * 60000).toISOString();
  const tries = await env.DB.prepare("SELECT COUNT(*) AS n FROM login_attempts WHERE ip_hash = ? AND at > ?").bind(hash, since).first();
  if (tries && tries.n >= LOGIN_ATTEMPTS) return json({ error: "rate" }, 429);
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  const ok = timingSafeEqual(await sha256(String(data.password || "")), await sha256(env.ADMIN_PASSWORD));
  if (!ok) {
    await env.DB.prepare("INSERT INTO login_attempts (ip_hash, at) VALUES (?, ?)").bind(hash, new Date().toISOString()).run();
    return json({ error: "unauthorized" }, 401);
  }
  await env.DB.prepare("DELETE FROM login_attempts WHERE ip_hash = ?").bind(hash).run();
  const res = json({ ok: true });
  res.headers.append("Set-Cookie", cookie("tp_admin", await signToken(env.SESSION_SECRET, "admin", ADMIN_SESSION_S), ADMIN_SESSION_S, "/api/admin"));
  return res;
}

function adminLogout() {
  const res = json({ ok: true });
  res.headers.append("Set-Cookie", cookie("tp_admin", "", 0, "/api/admin"));
  return res;
}

async function purgeOldIps(env) {
  await env.DB.prepare("UPDATE comments SET ip = NULL WHERE ip IS NOT NULL AND created_at < ?")
    .bind(new Date(Date.now() - IP_RETENTION_DAYS * 86400000).toISOString()).run();
}

async function adminComments(request, env, url) {
  if (request.method === "GET") {
    await purgeOldIps(env);
    const status = url.searchParams.get("status");
    const where = ["pending", "approved", "hidden"].includes(status) ? "WHERE c.status = ?" : "";
    const stmt = env.DB.prepare(
      `SELECT c.id, c.thread, c.created_at, c.name, c.message, c.lang, c.status, c.ip, c.country,
         (SELECT COUNT(*) FROM comment_likes l WHERE l.comment_id = c.id) AS likes
       FROM comments c ${where} ORDER BY c.id DESC LIMIT 500`);
    const { results } = await (where ? stmt.bind(status) : stmt).all();
    return json({ comments: results });
  }
  if (!sameOrigin(request, url)) return json({ error: "origin" }, 403);
  let data;
  try { data = await readJson(request); } catch { return json({ error: "invalid" }, 400); }
  const id = Number(data.id);
  if (!Number.isInteger(id) || id < 1) return json({ error: "invalid" }, 400);
  if (request.method === "POST") {
    const status = { approve: "approved", hide: "hidden" }[data.action];
    if (!status) return json({ error: "invalid" }, 400);
    await env.DB.prepare("UPDATE comments SET status = ? WHERE id = ?").bind(status, id).run();
    return json({ ok: true });
  }
  if (request.method === "DELETE") {
    await env.DB.batch([
      env.DB.prepare("DELETE FROM comment_likes WHERE comment_id = ?").bind(id),
      env.DB.prepare("DELETE FROM comments WHERE id = ?").bind(id),
    ]);
    return json({ ok: true });
  }
  return json({ error: "method" }, 405);
}

async function adminStats(env, url) {
  const days = Math.min(400, Math.max(1, Number(url.searchParams.get("days")) || 30));
  const since = daysAgo(days - 1);
  const { results: daily } = await env.DB.prepare(
    "SELECT day, kind, SUM(n) AS n FROM visit_stats WHERE day >= ? AND kind IN ('views', 'visitors', 'new') GROUP BY day, kind ORDER BY day"
  ).bind(since).all();
  const top = {};
  for (const kind of ["country", "referrer", "page", "device", "lang"]) {
    const { results } = await env.DB.prepare(
      "SELECT key, SUM(n) AS n FROM visit_stats WHERE day >= ? AND kind = ? GROUP BY key ORDER BY n DESC LIMIT 25"
    ).bind(since, kind).all();
    top[kind] = results;
  }
  const all = await env.DB.prepare("SELECT value FROM counters WHERE name = 'visitors'").first();
  return json({ days, since, daily, top, allTime: all ? all.value : 0 });
}

export function summariseVitals(rows) {
  const out = {};
  for (const metric of Object.keys(VITALS)) {
    for (const device of ["mobile", "desktop"]) {
      const v = VITALS[metric];
      const counts = new Array(v.edges.length + 1).fill(0);
      for (const r of rows) if (r.metric === metric && r.device === device) counts[r.bucket] += r.n;
      const total = counts.reduce((a, b) => a + b, 0);
      if (!total) continue;
      let cum = 0, p75 = null;
      for (let i = 0; i < counts.length; i++) {
        cum += counts[i];
        if (p75 === null && cum >= 0.75 * total) p75 = i < v.edges.length ? v.edges[i] : null;
      }
      let good = 0, poor = 0;
      for (let i = 0; i < counts.length; i++) {
        const upper = i < v.edges.length ? v.edges[i] : Infinity;
        if (upper <= v.good) good += counts[i];
        else if (upper > v.poor) poor += counts[i];
      }
      out[`${metric}.${device}`] = { metric, device, samples: total, p75, p75_over_max: p75 === null,
        good: good / total, poor: poor / total, threshold_good: v.good, threshold_poor: v.poor };
    }
  }
  return out;
}

async function adminVitals(env, url) {
  const days = Math.min(400, Math.max(1, Number(url.searchParams.get("days")) || 28));
  const { results } = await env.DB.prepare(
    "SELECT metric, device, bucket, SUM(n) AS n FROM vitals WHERE day >= ? GROUP BY metric, device, bucket").bind(daysAgo(days - 1)).all();
  return json({ days, vitals: summariseVitals(results) });
}

async function adminSummary(env) {
  const pending = await env.DB.prepare("SELECT COUNT(*) AS n FROM comments WHERE status = 'pending'").first();
  const day = today(), month = day.slice(0, 7);
  const t = await env.DB.prepare("SELECT SUM(n) AS n FROM visit_stats WHERE kind = 'visitors' AND day = ?").bind(day).first();
  const m = await env.DB.prepare("SELECT SUM(n) AS n FROM visit_stats WHERE kind = 'visitors' AND day >= ?").bind(month + "-01").first();
  const { results: countries } = await env.DB.prepare(
    "SELECT key, SUM(n) AS n FROM visit_stats WHERE kind = 'country' AND day >= ? GROUP BY key ORDER BY n DESC LIMIT 5").bind(daysAgo(29)).all();
  const { results: refs } = await env.DB.prepare(
    "SELECT key, SUM(n) AS n FROM visit_stats WHERE kind = 'referrer' AND day >= ? GROUP BY key ORDER BY n DESC LIMIT 5").bind(daysAgo(29)).all();
  const { results: vit } = await env.DB.prepare(
    "SELECT metric, device, bucket, SUM(n) AS n FROM vitals WHERE day >= ? GROUP BY metric, device, bucket").bind(daysAgo(27)).all();
  return json({ pending: pending ? pending.n : 0, visitorsToday: t && t.n ? t.n : 0, visitorsMonth: m && m.n ? m.n : 0,
    countries, referrers: refs, vitals: summariseVitals(vit) });
}

async function handleAdmin(request, env, url, path) {
  if (path === "/api/admin/login" && request.method === "POST") return adminLogin(request, env, url);
  if (path === "/api/admin/logout" && request.method === "POST") return adminLogout();
  if (!(await isAdmin(request, env))) return json({ error: "unauthorized" }, 401);
  await ensureSchema(env.DB);
  if (path === "/api/admin/me") return json({ ok: true });
  if (path === "/api/admin/summary" && request.method === "GET") return adminSummary(env);
  if (path === "/api/admin/comments") return adminComments(request, env, url);
  if (path === "/api/admin/stats" && request.method === "GET") return adminStats(env, url);
  if (path === "/api/admin/vitals" && request.method === "GET") return adminVitals(env, url);
  return json({ error: "not_found" }, 404);
}

// ---------------------------------------------------------------- maintenance
async function maintenance(env) {
  await ensureSchema(env.DB);
  await purgeOldIps(env);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM visit_stats WHERE day < ?").bind(daysAgo(STATS_RETENTION_DAYS)),
    env.DB.prepare("DELETE FROM vitals WHERE day < ?").bind(daysAgo(STATS_RETENTION_DAYS)),
    env.DB.prepare("DELETE FROM login_attempts WHERE at < ?").bind(new Date(Date.now() - 86400000).toISOString()),
  ]);
}

// ---------------------------------------------------------------- router
export default {
  async scheduled(event, env, ctx) {
    if (env.DB) ctx.waitUntil(maintenance(env));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/") {
      return new Response(null, { status: 302, headers: {
        Location: `/${pickLang(request)}/`, Vary: "Accept-Language, Cookie", "Cache-Control": "private, no-store" } });
    }

    if (path.startsWith("/api/")) {
      if (path === "/api/weather" && request.method === "GET") {
        try { return await handleWeather(ctx); } catch { return json({ error: "upstream" }, 502); }
      }
      if (!env.DB) return json({ error: "not_configured" }, 503);
      try {
        if (path === "/api/visit" && request.method === "POST") return await handleVisit(request, env, url);
        if (path === "/api/visitors" && request.method === "GET") return await handleVisitors(env);
        if (path === "/api/vitals" && request.method === "POST") return await handleVitals(request, env, url);
        if (path === "/api/human" && request.method === "POST") return await handleHuman(request, env, url);
        if (path === "/api/comments" && request.method === "GET") return await listComments(request, env, url);
        if (path === "/api/comments" && request.method === "POST") return await postComment(request, env, url);
        if (path === "/api/comments/like" && request.method === "POST") return await toggleLike(request, env, url);
        if (path.startsWith("/api/admin/")) return await handleAdmin(request, env, url, path);
        return json({ error: "not_found" }, 404);
      } catch (e) {
        console.log("api error", path, e && e.message);
        return json({ error: "server" }, 500);
      }
    }

    // Old French URLs from the first version: permanent redirect, keeps any shared link working.
    for (const [from, to] of Object.entries(LEGACY)) {
      if (path === from || (path.startsWith(from) && from === "/bulletin/")) {
        return Response.redirect(new URL(to + path.slice(from.length) + url.search, url).toString(), 301);
      }
    }

    // Static files (most requests never reach this Worker: assets are served first).
    const res = await env.ASSETS.fetch(request);
    if (res.status !== 404) return res;
    const m = path.match(/^\/(fr|de|it|en)\//);
    const lang = m ? m[1] : pickLang(request);
    // "404.html" is served at "/<lang>/404" because of html_handling.
  const notFound = await env.ASSETS.fetch(new Request(new URL(`/${lang}/404`, url), { headers: request.headers }));
    const headers = new Headers(notFound.headers);
    for (const [k, v] of Object.entries(PAGE_SECURITY)) headers.set(k, v);
    return new Response(notFound.body, { status: 404, headers });
  },
};
