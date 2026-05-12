# config.py — shared configuration for all four scraper architectures

# ── Sources ──────────────────────────────────────────────────────────────────

RSS_SOURCES = [
    {
        "name": "KYMA",
        "url": "https://kyma.com/category/news/imperial-county/feed/",
        "type": "wordpress",
    },
    {
        "name": "IV Press",
        "url": "https://www.ivpressonline.com/search/?f=rss&t=article&l=25",
        "type": "townnews",
    },
    {
        "name": "Desert Review",
        "url": "https://www.thedesertreview.com/search/?f=rss&t=article&l=25",
        "type": "townnews",
    },
]

SITEMAP_SOURCES = [
    {
        "name": "IV Press",
        "url": "https://www.ivpressonline.com/tncms/sitemap/news.xml",
    },
    {
        "name": "Desert Review",
        "url": "https://www.thedesertreview.com/tncms/sitemap/news.xml",
    },
]

# KYMA sitemap is JS-protected; fall back to RSS for LLM arm
KYMA_RSS = "https://kyma.com/category/news/imperial-county/feed/"

# Google News RSS search queries (alerts arm + LLM broad sweep)
GOOGLE_NEWS_QUERIES = [
    "heat illness imperial valley",
    "heat death imperial county california",
    "heat stroke el centro brawley calexico",
    "heat exhaustion imperial valley",
    "golpe de calor valle imperial",           # Spanish
    "muerte por calor condado imperial",       # Spanish
    "excessive heat warning imperial county",
    "heat related death california desert",
]

# Sites for headless arm (captcha-blocked to normal requests)
HEADLESS_TARGETS = [
    {
        "name": "Calexico Chronicle",
        "section_url": "https://calexicochronicle.com/category/local/",
        "base_url": "https://calexicochronicle.com",
    },
    {
        "name": "Holtville Tribune",
        "section_url": "https://holtvilletribune.com/category/local/",
        "base_url": "https://holtvilletribune.com",
    },
    # Also sweep main news sections of RSS sources for articles outside the feed window
    {
        "name": "KYMA",
        "section_url": "https://kyma.com/category/news/imperial-county/",
        "base_url": "https://kyma.com",
    },
    {
        "name": "IV Press",
        "section_url": "https://www.ivpressonline.com/news/",
        "base_url": "https://www.ivpressonline.com",
    },
]

# ── Keywords ─────────────────────────────────────────────────────────────────

PRIMARY_HEAT_TERMS = [
    "heat stroke", "heatstroke", "heat death", "heat-related death",
    "heat exhaustion", "heat illness", "heat emergency", "heat fatality",
    "hyperthermia", "heat casualty", "died from heat", "died of heat",
    "killed by heat", "heat victim",
    # Spanish
    "golpe de calor", "muerte por calor", "enfermedad por calor",
    "agotamiento por calor", "víctima del calor",
]

SECONDARY_HEAT_TERMS = [
    "extreme heat", "excessive heat", "dangerous heat", "deadly heat",
    "record heat", "heat wave", "heatwave", "heat advisory",
    "excessive heat warning", "excessive heat watch",
    "heat index", "heat emergency", "cooling center",
    # Spanish
    "calor extremo", "calor peligroso", "ola de calor", "aviso de calor",
    "centro de enfriamiento",
]

OCCUPATIONAL_TERMS = [
    "farmworker", "farm worker", "agricultural worker", "field worker",
    "outdoor worker", "construction worker", "trabajador agrícola",
    "campesino", "jornalero",
]

DEATH_TERMS = [
    "death", "died", "fatal", "fatality", "killed", "coroner",
    "autopsy", "deceased", "muerte", "muerto", "fallecido", "falleció",
]

IV_LOCATIONS = [
    "imperial valley", "imperial county", "el centro", "brawley",
    "calexico", "holtville", "imperial", "westmorland", "niland",
    "calipatria", "seeley", "bard", "winterhaven", "ocotillo",
    "valle imperial", "condado imperial",
]

EXCLUSION_TERMS = [
    "heat pump", "heat map", "heat check", "heating system",
    "heating bill", "heat treatment", "heat therapy", "heated debate",
    "heating costs", "heat game",  # sports
]

# ── Scoring weights (rule-based arms only) ────────────────────────────────────

WEIGHTS = {
    "primary_heat_title": 20,
    "primary_heat_body": 15,
    "death_co_occurrence": 10,
    "occupational_term": 10,
    "title_boost": 10,
    "secondary_heat_term": 5,
    "location_match": 3,          # capped — see LOCATION_CAP
    "death_term": 3,
    "exclusion_penalty": -20,
}

LOCATION_CAP = 6                  # max points from location matching
RELEVANCE_THRESHOLD = 15          # minimum score to include article

# ── Output paths ──────────────────────────────────────────────────────────────

DATA_DIR = "data"
RSS_OUTPUT = f"{DATA_DIR}/rss_scored.csv"
HEADLESS_OUTPUT = f"{DATA_DIR}/headless_scored.csv"
LLM_OUTPUT = f"{DATA_DIR}/llm_scored.csv"
ALERTS_OUTPUT = f"{DATA_DIR}/alerts_scored.csv"
MASTER_OUTPUT = f"{DATA_DIR}/master_comparison.csv"

# ── Anthropic ─────────────────────────────────────────────────────────────────

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_MAX_TOKENS = 512
ARTICLE_CHAR_LIMIT = 8000         # truncate full article text before sending to Claude

# ── Request headers ───────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; IVHeatMonitor/2.0; "
        "+https://github.com/your-org/iv-heat-scraper)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY = 2.0               # seconds between requests (polite scraping)
REQUEST_TIMEOUT = 15
