"""
updater.py
──────────
Incremental update engine.  Two ingestion paths:

  PATH A — Understat-native (original)
    python updater.py --season 2023
    Fetches Understat season listing → shot data → analyse → persist.

  PATH B — Football-Data CSV + Understat shots
    python updater.py --csv-dir /path/to/csvs
    Reads E0*.csv files → detects seasons → joins to Understat IDs via
    linker.py → fetches shots for matched IDs → analyse → persist.
    Unmatched rows are logged as warnings (see linker.report_unmatched).

Both paths share the same downstream pipeline:
    fetch_match_shots → extract_goal_timeline → analyse → upsert_match

Design principles (unchanged)
───────────────────────────────
  IDEMPOTENT  – Running twice produces identical results.
  ADDITIVE    – Existing rows are never deleted during normal updates.
  MINIMAL     – Only match IDs not yet in the DB are fetched.
  ATOMIC      – Each season lands in one transaction.
  AUDITABLE   – season_log timestamps every successful ingest.

Usage
─────
  python updater.py                         # all TARGET_SEASONS (Understat native)
  python updater.py --season 2024           # one season (Understat native)
  python updater.py --csv-dir ./data/raw    # CSV path
  python updater.py --all --fresh           # wipe DB, full re-ingest
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
from pathlib import Path

from config import DB_PATH, OUTPUT_DIR, TARGET_SEASONS
from database import (
    create_schema,
    get_connection,
    ingested_seasons,
    log_season,
    rebuild_fixtures,
    transaction,
    upsert_goals,
    upsert_match,
)

logger = logging.getLogger(__name__)


# ── PATH A: Understat-native ingest ──────────────────────────────────────────

async def ingest_season(conn: sqlite3.Connection, season: int) -> int:
    """Fetch one season from Understat API/cache and persist to DB."""
    from fetcher import fetch_matches_for_season
    from processor import build_match_record, extract_goal_timeline, parse_match_summary
    from analyzer import analyse

    existing: set[str] = {
        row[0]
        for row in conn.execute(
            "SELECT match_id FROM matches WHERE season = ?", (season,)
        ).fetchall()
    }

    pairs = await fetch_matches_for_season(season, existing_match_ids=existing)
    if not pairs:
        logger.info("Season %d: no new matches to ingest.", season)
        return 0

    written = 0
    with transaction(conn):
        for raw_summary, shots_payload in pairs:
            meta            = parse_match_summary(raw_summary)
            meta["season"]  = season
            goal_events     = extract_goal_timeline(shots_payload, meta["match_id"])
            analysis        = analyse(goal_events)
            record          = build_match_record(meta, goal_events, analysis)
            upsert_match(conn, record)
            upsert_goals(conn, meta["match_id"], goal_events)
            written += 1

    log_season(conn, season, written)
    logger.info("Season %d: %d new matches committed.", season, written)
    return written


# ── PATH B: Football-Data CSV ingest ─────────────────────────────────────────

async def ingest_from_csvs(
    conn: sqlite3.Connection,
    csv_dir: Path,
) -> dict[int, int]:
    """
    Load all E0*.csv files in csv_dir, link each match to its Understat ID,
    fetch shot data, analyse, and persist.

    Returns {season: new_match_count}.
    """
    import aiohttp
    from csv_loader import load_directory
    from linker import link_season, report_unmatched
    from fetcher import fetch_season, fetch_match_shots
    from processor import build_match_record, extract_goal_timeline
    from analyzer import analyse

    season_map = load_directory(csv_dir)   # {season: [FDMatch, …]}
    if not season_map:
        logger.warning("No CSV data found in %s.", csv_dir)
        return {}

    written_per_season: dict[int, int] = {}

    async with aiohttp.ClientSession() as session:
        for season, fd_matches in sorted(season_map.items()):
            logger.info("CSV ingest — season %d (%d FD matches).", season, len(fd_matches))

            # Fetch Understat season listing for ID lookup
            us_summaries = await fetch_season(session, season)

            # Link FD rows → Understat IDs
            linked, unmatched = link_season(fd_matches, us_summaries)
            if unmatched:
                report_unmatched(unmatched)

            # Skip already-ingested matches
            existing: set[str] = {
                row[0]
                for row in conn.execute(
                    "SELECT match_id FROM matches WHERE season = ?", (season,)
                ).fetchall()
            }
            new_linked = [m for m in linked if m["match_id"] not in existing]
            logger.info(
                "Season %d: %d linked, %d already in DB → %d to fetch.",
                season, len(linked), len(linked) - len(new_linked), len(new_linked),
            )

            written = 0
            with transaction(conn):
                for lm in new_linked:
                    try:
                        shots_payload = await fetch_match_shots(session, lm["match_id"])
                    except Exception as exc:
                        logger.error("Shot fetch failed for %s: %s", lm["match_id"], exc)
                        continue

                    goal_events = extract_goal_timeline(shots_payload, lm["match_id"])
                    analysis    = analyse(goal_events)

                    record = build_match_record(
                        {
                            "match_id":   lm["match_id"],
                            "season":     season,
                            "date":       lm["fd_date"],
                            "home_team":  lm["home_team"],
                            "away_team":  lm["away_team"],
                            "home_goals": lm["home_goals"],
                            "away_goals": lm["away_goals"],
                        },
                        goal_events,
                        analysis,
                    )
                    upsert_match(conn, record)
                    upsert_goals(conn, lm["match_id"], goal_events)
                    written += 1

            log_season(conn, season, written)
            written_per_season[season] = written
            logger.info("Season %d: %d new matches committed.", season, written)

    return written_per_season


# ── Top-level run functions ───────────────────────────────────────────────────

async def run_update(
    seasons: list[int],
    db_path: Path = DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    fresh: bool = False,
) -> None:
    """PATH A: Understat-native update for given seasons."""
    from aggregator import export

    if fresh and db_path.exists():
        logger.info("--fresh: removing %s", db_path)
        db_path.unlink()

    conn = get_connection(db_path)
    create_schema(conn)

    done      = ingested_seasons(conn)
    to_ingest = sorted(s for s in seasons if s not in done)

    if not to_ingest:
        logger.info("All seasons already ingested.")
    else:
        logger.info("Seasons to ingest: %s", to_ingest)
        for season in to_ingest:
            await ingest_season(conn, season)

    rebuild_fixtures(conn)
    export(conn, output_dir)
    conn.close()


async def run_csv_update(
    csv_dir: Path,
    db_path: Path = DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    fresh: bool = False,
) -> None:
    """PATH B: CSV-based update — reads Football-Data files, links to Understat."""
    from aggregator import export

    if fresh and db_path.exists():
        logger.info("--fresh: removing %s", db_path)
        db_path.unlink()

    conn = get_connection(db_path)
    create_schema(conn)

    await ingest_from_csvs(conn, csv_dir)
    rebuild_fixtures(conn)
    export(conn, output_dir)
    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EPL 3UAG Database Updater")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--season",  type=int, metavar="YEAR",
                     help="Single season start-year (Understat native path).")
    src.add_argument("--all",     dest="all_seasons", action="store_true",
                     help="All seasons in config.TARGET_SEASONS (Understat native).")
    src.add_argument("--csv-dir", metavar="DIR",
                     help="Directory containing E0*.csv files (Football-Data path).")
    p.add_argument("--fresh", action="store_true",
                   help="Wipe the database before ingesting.")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        datefmt="%H:%M:%S",
    )
    args = _parse_args()

    if args.csv_dir:
        asyncio.run(run_csv_update(Path(args.csv_dir), fresh=args.fresh))
    else:
        seasons = [args.season] if args.season else TARGET_SEASONS
        asyncio.run(run_update(seasons, fresh=args.fresh))


if __name__ == "__main__":
    main()
