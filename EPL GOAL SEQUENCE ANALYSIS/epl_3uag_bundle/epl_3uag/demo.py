"""
demo.py
───────
Full end-to-end pipeline demonstration using SYNTHETIC match data.

No internet connection, no understat/aiohttp install required.
Generates three realistic EPL seasons, runs every pipeline stage,
prints annotated results to stdout, and writes the three output CSVs.

Run:
    python demo.py

Synthetic data spec
───────────────────
  Teams  : 10 (abbreviated Premier League)
  Seasons: 2021, 2022, 2023
  Matches: full home-and-away round-robin per season
           → 90 matches per season × 3 = 270 total

  Goal distribution: independent Poisson per team per match
    λ_home ≈ 1.5,  λ_away ≈ 1.2  (home-advantage baked in)
  Minutes: uniform U[1, 97] (includes added time)

  Guaranteed 3UAG fixtures (injected so the demo always shows both cases):
    Arsenal vs Chelsea  (all three seasons — H sequence 12′, 25′, 38′)
"""
from __future__ import annotations

import json
import logging
import math
import random
import sqlite3
from itertools import combinations
from pathlib import Path

import pandas as pd

from analyzer import analyse, _run_self_tests
from aggregator import build_fixture_df, build_match_df, export, qualifying_fixtures
from config import THREE_UAG_THRESHOLD
from database import (
    create_schema,
    get_connection,
    log_season,
    rebuild_fixtures,
    transaction,
    upsert_goals,
    upsert_match,
)
from processor import build_match_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Demo paths (separate from production DB) ──────────────────────────────────
_HERE    = Path(__file__).parent
DEMO_DB  = _HERE / "data" / "demo.db"
DEMO_OUT = _HERE / "data" / "demo_output"

# ── Synthetic league config ───────────────────────────────────────────────────
DEMO_TEAMS = [
    "Arsenal", "Chelsea", "Liverpool", "Man City",
    "Man United", "Tottenham", "Newcastle", "West Ham",
    "Brighton", "Brentford",
]
DEMO_SEASONS    = [2021, 2022, 2023]
RANDOM_SEED     = 42          # reproducible output
LAMBDA_HOME     = 1.5         # expected home goals per match
LAMBDA_AWAY     = 1.2         # expected away goals per match

# Pairs deliberately injected with a 3UAG event every season
INJECTED_3UAG_PAIRS = [
    ("Arsenal",    "Chelsea"),
    ("Man City",   "Brentford"),
]


# ── Tiny pure-Python Poisson draw (no numpy needed) ──────────────────────────

def _poisson(lam: float, rng: random.Random) -> int:
    """Knuth's algorithm — O(λ) expected iterations, fine for small λ."""
    L, k, p = math.exp(-lam), 0, 1.0
    while p > L:
        p *= rng.random()
        k += 1
    return k - 1


# ── Synthetic match generator ─────────────────────────────────────────────────

def _make_goal_events(
    match_id: str,
    home: str,
    away: str,
    rng: random.Random,
) -> list[dict]:
    """Generate a random goal timeline for one match."""
    h_goals = _poisson(LAMBDA_HOME, rng)
    a_goals = _poisson(LAMBDA_AWAY, rng)

    events: list[dict] = []
    for _ in range(h_goals):
        events.append({
            "match_id": match_id,
            "minute":   rng.randint(1, 97),
            "team":     "H",
            "player":   f"{home[:3].upper()}_{rng.randint(1, 11):02d}",
        })
    for _ in range(a_goals):
        events.append({
            "match_id": match_id,
            "minute":   rng.randint(1, 97),
            "team":     "A",
            "player":   f"{away[:3].upper()}_{rng.randint(1, 11):02d}",
        })

    events.sort(key=lambda e: e["minute"])
    return events


def _make_three_uag_events(match_id: str, home: str, away: str) -> list[dict]:
    """
    Manufacture a deterministic goal sequence that always triggers a 3UAG.
    Home team scores three consecutive goals (12′, 25′, 38′) before the
    away side replies (55′, 80′).
    """
    return [
        {"match_id": match_id, "minute": 12, "team": "H", "player": f"{home[:3].upper()}_07"},
        {"match_id": match_id, "minute": 25, "team": "H", "player": f"{home[:3].upper()}_09"},
        {"match_id": match_id, "minute": 38, "team": "H", "player": f"{home[:3].upper()}_11"},
        {"match_id": match_id, "minute": 55, "team": "A", "player": f"{away[:3].upper()}_10"},
        {"match_id": match_id, "minute": 80, "team": "A", "player": f"{away[:3].upper()}_09"},
    ]


def _build_season(
    season: int,
    rng: random.Random,
) -> list[tuple[dict, list[dict]]]:
    """
    Full home-and-away round-robin for DEMO_TEAMS in one season.
    Returns list of (match_meta, goal_events) tuples.
    """
    pairs = [(h, a) for h, a in combinations(DEMO_TEAMS, 2)]
    pairs += [(a, h) for h, a in pairs]   # both home/away legs
    rng.shuffle(pairs)

    records: list[tuple[dict, list[dict]]] = []
    injected = set(map(frozenset, INJECTED_3UAG_PAIRS))  # unordered pair check

    for idx, (home, away) in enumerate(pairs):
        match_id = f"{season}_{idx:04d}"

        if frozenset([home, away]) in injected:
            goal_events = _make_three_uag_events(match_id, home, away)
        else:
            goal_events = _make_goal_events(match_id, home, away, rng)

        meta = {
            "match_id":   match_id,
            "season":     season,
            "date":       f"{season}-08-{14 + idx % 28:02d}",  # approximate
            "home_team":  home,
            "away_team":  away,
            "home_goals": sum(1 for e in goal_events if e["team"] == "H"),
            "away_goals": sum(1 for e in goal_events if e["team"] == "A"),
        }
        records.append((meta, goal_events))

    return records


# ── Pipeline stages ───────────────────────────────────────────────────────────

def _stage_ingest(conn: sqlite3.Connection) -> int:
    """Stage 1-4: Generate → analyse → persist all synthetic matches."""
    rng = random.Random(RANDOM_SEED)
    total = 0

    for season in DEMO_SEASONS:
        records = _build_season(season, rng)

        with transaction(conn):
            for meta, goal_events in records:
                analysis = analyse(goal_events)
                record   = build_match_record(meta, goal_events, analysis)
                upsert_match(conn, record)
                upsert_goals(conn, meta["match_id"], goal_events)

        log_season(conn, season, len(records))
        total += len(records)
        logger.info("Season %d ingested — %d matches.", season, len(records))

    return total


# ── Pretty-print helpers ──────────────────────────────────────────────────────

def _hr(char: str = "─", width: int = 66) -> str:
    return char * width


def _print_matches_with_3uag(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT season, home_team, away_team,
               home_goals, away_goals,
               goal_sequence, three_uag_details
        FROM matches
        WHERE has_three_uag = 1
        ORDER BY season, date
        LIMIT 8
        """
    ).fetchall()

    print(f"\n{_hr('═')}")
    print("  STAGE 4 — MATCHES FLAGGED WITH 3UAG")
    print(_hr('═'))
    for r in rows:
        seq     = " → ".join(json.loads(r["goal_sequence"]))
        details = json.loads(r["three_uag_details"])
        run     = details[0] if details else {}
        team_lbl = "Home" if run.get("team") == "H" else "Away"
        print(
            f"  [{r['season']}]  {r['home_team']:15s} "
            f"{r['home_goals']}–{r['away_goals']} "
            f"{r['away_team']:15s}"
        )
        print(f"    sequence : {seq}")
        if run:
            print(
                f"    3UAG run : {team_lbl} scores {run['run_length']} "
                f"straight  (triggered at {run['trigger_minute']}′)"
            )
    print()


def _print_fixture_sample(fixture_df: pd.DataFrame) -> None:
    print(_hr('═'))
    print("  STAGE 5-6 — FIXTURE-LEVEL DATASET  (sample, top 12)")
    print(_hr('─'))
    print(f"  {'Team 1':<20} {'Team 2':<20} {'Matches':>7} {'3UAG':>5} {'Qualifies':>10}")
    print(_hr('─'))
    for _, row in fixture_df.head(12).iterrows():
        q = "YES ✓" if row["qualifies"] else "no"
        print(
            f"  {row['team1']:<20} {row['team2']:<20} "
            f"{row['total_matches']:>7} {row['matches_with_three_uag']:>5} {q:>10}"
        )
    print()


def _print_qualifying(qual_df: pd.DataFrame) -> None:
    print(_hr('═'))
    print("  STAGE 6 — QUALIFYING FIXTURES  (zero 3UAG across all meetings)")
    print(_hr('─'))
    if qual_df.empty:
        print("  (none — every fixture had at least one 3UAG match)")
    else:
        for _, row in qual_df.iterrows():
            print(
                f"  {row['team1']:20s} vs {row['team2']:20s} "
                f"— {row['total_matches']} matches, 0 with 3UAG"
            )
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(_hr('═'))
    print("  EPL THREE-UNANSWERED-GOALS PIPELINE  — DEMO (synthetic data)")
    print(_hr('═'))

    # ── Stage 0: Algorithm self-test ──────────────────────────────────────────
    print("\nSTAGE 0 — ALGORITHM SELF-TESTS")
    print(_hr('─'))
    _run_self_tests()

    # ── Prepare fresh demo database ───────────────────────────────────────────
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    DEMO_OUT.mkdir(parents=True, exist_ok=True)
    if DEMO_DB.exists():
        DEMO_DB.unlink()

    conn = get_connection(DEMO_DB)
    create_schema(conn)

    # ── Stages 1-4: Ingest ────────────────────────────────────────────────────
    print("STAGES 1-4 — PARSE · FETCH TIMELINE · ANALYSE · PERSIST")
    print(_hr('─'))
    total = _stage_ingest(conn)
    logger.info("Total matches ingested: %d", total)

    _print_matches_with_3uag(conn)

    # ── Stage 5: Rebuild fixture aggregates ───────────────────────────────────
    print("STAGE 5 — AGGREGATE HEAD-TO-HEAD FIXTURE HISTORY")
    print(_hr('─'))
    rebuild_fixtures(conn)
    logger.info("Fixture table rebuilt.")

    # ── Stage 6: Export & display ─────────────────────────────────────────────
    print("\nSTAGE 6 — CONSTRUCT FIXTURE DATASET · EXPORT CSVs")
    print(_hr('─'))
    export(conn, DEMO_OUT)

    fixture_df = build_fixture_df(conn)
    qual_df    = qualifying_fixtures(fixture_df)

    _print_fixture_sample(fixture_df)
    _print_qualifying(qual_df)

    # ── Stage 7: Update methodology note ─────────────────────────────────────
    print(_hr('═'))
    print("  STAGE 7 — UPDATE METHODOLOGY (how to add a new season)")
    print(_hr('─'))
    print("""
  To add season 2024 (2024/25) once the season completes:

    python updater.py --season 2024

  The updater will:
    1. Check season_log — if 2024 already present, exit early (idempotent).
    2. Fetch only new match IDs not already in the matches table.
    3. Ingest, analyse, and commit in one atomic transaction.
    4. Rebuild fixtures and re-export CSVs automatically.

  For a full history re-ingest (e.g. after changing the 3UAG threshold):

    python updater.py --all --fresh

  Cache files (data/cache/) are kept — only the DB is wiped — so
  previously fetched match data is reused without hitting Understat again.
""")
    print(_hr('═'))
    print(f"  Output CSVs written to:  {DEMO_OUT}")
    print(_hr('═'))
    conn.close()


if __name__ == "__main__":
    main()
