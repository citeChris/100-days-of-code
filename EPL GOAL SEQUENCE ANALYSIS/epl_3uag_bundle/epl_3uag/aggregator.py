"""
aggregator.py
─────────────
Aggregates match records into the fixture-level (head-to-head) dataset
and exports all three output CSVs.

Fixture definition
──────────────────
A "fixture" is the UNORDERED pair of two clubs.  Every EPL meeting between
Arsenal and Chelsea — regardless of which ground it was played at — counts
toward the same fixture record.  This mirrors how football analysts refer to
a "head-to-head record" between two sides.

Three output datasets
─────────────────────
1. match_level_dataset.csv       – one row per match, all fields
2. fixture_level_dataset.csv     – one row per club pair, H2H aggregates
3. qualifying_fixtures.csv       – subset of (2) where qualifies == 1

"Qualifies" means: across ALL historical meetings in the dataset, not a
single match contained a 3UAG event.

Public API
──────────
  build_match_df(conn)       → pd.DataFrame
  build_fixture_df(conn)     → pd.DataFrame
  qualifying_fixtures(df)    → filtered pd.DataFrame
  export(conn, output_dir)   → writes CSVs + prints summary banner
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from config import FIXTURES_CSV, MATCHES_CSV, QUALIFYING_CSV

logger = logging.getLogger(__name__)

# Columns surfaced in the match-level CSV (order matters for readability)
MATCH_EXPORT_COLS = [
    "match_id", "season", "date",
    "home_team", "away_team", "home_goals", "away_goals",
    "goal_sequence", "has_three_uag", "three_uag_details",
]

FIXTURE_EXPORT_COLS = [
    "team1", "team2",
    "total_matches",
    "matches_with_three_uag", "matches_without_three_uag",
    "qualifies",
]


# ── DataFrame builders ────────────────────────────────────────────────────────

def build_match_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load the full matches table, de-serialising JSON columns."""
    rows = conn.execute(
        """
        SELECT match_id, season, date,
               home_team, away_team, home_goals, away_goals,
               goal_sequence, has_three_uag, three_uag_details
        FROM matches
        ORDER BY season, date
        """
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=MATCH_EXPORT_COLS)

    df = pd.DataFrame([dict(r) for r in rows])
    df["goal_sequence"]     = df["goal_sequence"].apply(json.loads)
    df["three_uag_details"] = df["three_uag_details"].apply(json.loads)
    return df


def build_fixture_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load the pre-aggregated fixtures table."""
    rows = conn.execute(
        """
        SELECT team1, team2,
               total_matches,
               matches_with_three_uag, matches_without_three_uag,
               qualifies
        FROM fixtures
        ORDER BY qualifies DESC, total_matches DESC, team1, team2
        """
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=FIXTURE_EXPORT_COLS)

    return pd.DataFrame([dict(r) for r in rows])


def qualifying_fixtures(fixture_df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns the subset of fixtures where qualifies == 1.
    These are club pairs where ZERO matches ever contained a 3UAG event.
    """
    return fixture_df[fixture_df["qualifies"] == 1].copy().reset_index(drop=True)


# ── CSV export ────────────────────────────────────────────────────────────────

def export(conn: sqlite3.Connection, output_dir: Path | None = None) -> None:
    """
    1. Build both DataFrames from the DB.
    2. Write three CSVs to output_dir (defaults to config.OUTPUT_DIR).
    3. Print a summary banner.
    """
    out = output_dir or MATCHES_CSV.parent
    out.mkdir(parents=True, exist_ok=True)

    # ── Match-level CSV ───────────────────────────────────────────────────────
    match_df = build_match_df(conn)
    if match_df.empty:
        logger.warning("No matches in database — skipping export.")
        return

    # Convert list columns to readable strings for the CSV
    csv_match_df = match_df.copy()
    csv_match_df["goal_sequence"] = csv_match_df["goal_sequence"].apply(
        lambda s: "→".join(s) if s else ""
    )
    csv_match_df["three_uag_details"] = csv_match_df["three_uag_details"].apply(
        json.dumps
    )

    match_csv = out / MATCHES_CSV.name
    csv_match_df.to_csv(match_csv, index=False)
    logger.info("Match-level dataset  → %s  (%d rows)", match_csv, len(csv_match_df))

    # ── Fixture-level CSV ─────────────────────────────────────────────────────
    fixture_df  = build_fixture_df(conn)
    fixture_csv = out / FIXTURES_CSV.name
    fixture_df.to_csv(fixture_csv, index=False)
    logger.info("Fixture-level dataset → %s  (%d rows)", fixture_csv, len(fixture_df))

    # ── Qualifying-fixtures CSV ───────────────────────────────────────────────
    qual_df  = qualifying_fixtures(fixture_df)
    qual_csv = out / QUALIFYING_CSV.name
    qual_df.to_csv(qual_csv, index=False)
    logger.info("Qualifying fixtures  → %s  (%d rows)", qual_csv, len(qual_df))

    # ── Summary banner ────────────────────────────────────────────────────────
    total   = len(match_df)
    with_3  = int(match_df["has_three_uag"].sum())
    pct_3   = 100 * with_3 / total if total else 0.0
    n_fix   = len(fixture_df)
    n_qual  = len(qual_df)
    pct_q   = 100 * n_qual / n_fix if n_fix else 0.0

    print()
    print("═" * 58)
    print("  EPL 3UAG PIPELINE  —  ANALYSIS SUMMARY")
    print("═" * 58)
    print(f"  Matches analysed         : {total:>6,}")
    print(f"  Matches WITH  3UAG       : {with_3:>6,}  ({pct_3:.1f} %)")
    print(f"  Matches WITHOUT 3UAG     : {total - with_3:>6,}  ({100 - pct_3:.1f} %)")
    print(f"  Unique H2H fixtures      : {n_fix:>6,}")
    print(f"  Qualifying fixtures      : {n_qual:>6,}  ({pct_q:.1f} % — zero 3UAG ever)")
    print("═" * 58)
    print()
