"""
config.py
─────────
Central configuration for the EPL Three-Unanswered-Goals (3UAG) pipeline.
Adjust TARGET_SEASONS or the algorithm threshold here; every other module
reads from this file so changes propagate automatically.
"""
from pathlib import Path

# ── Directory layout ──────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
CACHE_DIR  = DATA_DIR / "cache" / "shots"     # per-match shot JSON
SEASONS_CACHE_DIR = DATA_DIR / "cache" / "seasons"  # per-season result JSON
DB_PATH    = DATA_DIR / "epl_3uag.db"
OUTPUT_DIR = DATA_DIR / "output"

# ── League & seasons ──────────────────────────────────────────────────────────
# Understat uses the *start* calendar year of each season.
# 2014 → 2014/15, 2015 → 2015/16, …, 2023 → 2023/24
LEAGUE         = "EPL"
TARGET_SEASONS = list(range(2014, 2024))

# ── Algorithm ─────────────────────────────────────────────────────────────────
THREE_UAG_THRESHOLD = 3   # consecutive unanswered goals required

# ── Network / rate-limiting ───────────────────────────────────────────────────
API_DELAY_SECONDS = 0.5   # polite pause between Understat requests
MAX_RETRIES       = 3
RETRY_BACKOFF     = 2.0   # exponential back-off multiplier

# ── Output CSV filenames ──────────────────────────────────────────────────────
MATCHES_CSV    = OUTPUT_DIR / "match_level_dataset.csv"
FIXTURES_CSV   = OUTPUT_DIR / "fixture_level_dataset.csv"
QUALIFYING_CSV = OUTPUT_DIR / "qualifying_fixtures.csv"
