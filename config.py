import os
from dotenv import load_dotenv

load_dotenv(override=True)

GSC_CREDENTIALS_FILE = os.getenv("GSC_CREDENTIALS_FILE", "client_secret.json")
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "https://eagertobehealthy.com/")
WP_SITE_URL = os.getenv("WP_SITE_URL", "https://www.eagertobehealthy.com")

# ─── Pipeline ────────────────────────────────────────────────────────────────
# 1) Identify worst / most improvable pages (GSC + RankMath + …)
# 2) Enrich those pages only (WP, GSC slices, Bing, Planner, PageSpeed)
# 3) Claude handoff Markdown (keywords + fresh HTML guidance)
# 4) Optional local LLM

LOCAL_LLM_PROVIDER = os.getenv(
    "LOCAL_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "ollama")
).strip().lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "6"))

OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "").rstrip("/")
OPENAI_COMPAT_MODEL = os.getenv("OPENAI_COMPAT_MODEL", "")
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "ollama")

LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))

# Defaults match .env.example so behaviour is the same with or without
# an explicit override in .env.
DATE_RANGE_DAYS = int(
    os.getenv("DATE_RANGE_DAYS", os.getenv("DAYS_BACK", "365"))
)
MIN_IMPRESSIONS = int(os.getenv("MIN_IMPRESSIONS", "1"))
MAX_CTR = float(os.getenv("MAX_CTR", "0.05"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "20"))
MAX_POSTS_TO_ANALYZE = int(os.getenv("MAX_POSTS_TO_ANALYZE", "10"))

COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "60"))
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

# Save each selected page's WordPress HTML to reports/pages_YYYY-MM-DD/.
# The briefing sends the model to the live URL; this is what you paste in
# when it reports that it could not open one.
SAVE_PAGE_SNAPSHOTS = os.getenv("SAVE_PAGE_SNAPSHOTS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# ─── Google Ads Keyword Planner ──────────────────────────────────────────────
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
GOOGLE_ADS_CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").strip()
GOOGLE_ADS_LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip()
GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID", "").strip()
GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "").strip()
GOOGLE_ADS_REFRESH_TOKEN = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
# 2840 = United States; comma-separated geo target constant IDs
GOOGLE_ADS_GEO_TARGET_IDS = os.getenv("GOOGLE_ADS_GEO_TARGET_IDS", "2840").strip()
USE_KEYWORD_PLANNER = os.getenv("USE_KEYWORD_PLANNER", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# ─── Bing Webmaster (free complementary — on by default when key is set) ─────
BING_API_KEY = os.getenv("BING_API_KEY", "").strip()
BING_SITE_URL = os.getenv(
    "BING_SITE_URL", "https://www.eagertobehealthy.com/"
).strip()
USE_BING = os.getenv("USE_BING", "1").strip().lower() in ("1", "true", "yes", "on")

# ─── RankMath prioritization ─────────────────────────────────────────────────
# Prefer most improvable posts: score tiers under 20 / 40 / 60 / 80 first.
PRIORITIZE_BY_RANKMATH = os.getenv("PRIORITIZE_BY_RANKMATH", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Skip pages at/above this score (default 80 = focus energy below "strong")
RANKMATH_SKIP_SCORE = int(os.getenv("RANKMATH_SKIP_SCORE", "80"))
# Optional WP Application Password (only needed if REST is locked down)
WP_APP_USER = os.getenv("WP_APP_USER", "").strip()
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "").strip()

# ─── PageSpeed Insights (only after pages are selected) ──────────────────────
# Free Google API. Scans ONLY the worst-N URLs chosen in stage 1 — not the whole site.
USE_PAGESPEED = os.getenv("USE_PAGESPEED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()
# comma-separated: mobile,desktop — mobile alone is cheaper/faster
PAGESPEED_STRATEGIES = [
    s.strip()
    for s in os.getenv("PAGESPEED_STRATEGIES", "mobile").split(",")
    if s.strip()
]
PAGESPEED_TIMEOUT_SECONDS = int(os.getenv("PAGESPEED_TIMEOUT_SECONDS", "120"))
PAGESPEED_PAUSE_SECONDS = float(os.getenv("PAGESPEED_PAUSE_SECONDS", "1.5"))


def local_llm_label() -> str:
    if not USE_LOCAL_LLM:
        return "none (data handoff → Claude)"
    if LOCAL_LLM_PROVIDER in ("ollama", "local"):
        return f"ollama/{OLLAMA_MODEL}"
    if LOCAL_LLM_PROVIDER in ("openai_compat", "openai", "llamacpp", "llama.cpp"):
        model = OPENAI_COMPAT_MODEL or OLLAMA_MODEL
        base = OPENAI_COMPAT_BASE_URL or OLLAMA_BASE_URL
        return f"openai_compat/{model} @ {base}"
    return LOCAL_LLM_PROVIDER
