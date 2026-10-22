"""Central settings for Transit Pulse (Lausanne POC)."""
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DAILY_DIR = DATA / "daily"
BULLETIN_DIR = DATA / "bulletins"
DISRUPTION_FILE = DATA / "disruptions" / "latest.json"
RUN_LOG = DATA / "runs.jsonl"
PROMPTS = ROOT / "prompts"
PUBLIC = ROOT / "public"
STATIC = ROOT / "site_static"

TZ = ZoneInfo("Europe/Zurich")

# --- Scope of the proof of concept -------------------------------------
AREA_NAME = "Lausanne"
# A stop belongs to the POC when its name starts with one of these prefixes
# (covers "Lausanne", "Lausanne, Flon", "Lausanne-Ouchy", ...).
STOP_PREFIXES = ("Lausanne",)

# --- Punctuality rules ---------------------------------------------------
# Same convention as Swiss customer punctuality: on time = less than 3 min late.
PUNCTUAL_LIMIT_MIN = 3.0
# Delays above this are treated as data errors and left out of the statistics.
MAX_PLAUSIBLE_DELAY_MIN = 300.0
MIN_EVENTS_FOR_RANKING = 40

# --- Data sources --------------------------------------------------------
# The catalogue API answers 403 to automated calls; the dataset page lists the files.
IST_DATEN_PAGE = "https://data.opentransportdata.swiss/en/dataset/ist-daten-v2"
SIRI_SX_URL = "https://api.opentransportdata.swiss/la/siri-sx"
USER_AGENT = "transit-pulse-poc/1.0 (+https://github.com/thomasa413-max/transit-pulse)"
# Provider guidance: call the full SIRI-SX feed only a few times a day.
# Quota: 48 calls/day, 10/hour. The job runs every 3 hours (8 calls).
SIRI_MAX_CALLS_PER_DAY = 40

# --- AI models and prices (USD per million tokens, Claude API) -----------
MODEL_DAILY = "claude-haiku-5-5"
PRICES = {
    # model: (input, output) for prompts up to 100k tokens
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
MONTHLY_BUDGET_USD = 10.0

PROMPT_VERSION = "v1"
LANGS = {"fr": "Français", "de": "Deutsch", "it": "Italiano", "en": "English"}

# --- Operations ----------------------------------------------------------
# Alert if no successful daily run for this long.
DAILY_STALE_HOURS = 30
SITE_TITLE = "Transit Pulse Lausanne"
REPO_URL = "https://github.com/thomasa413-max/transit-pulse"
