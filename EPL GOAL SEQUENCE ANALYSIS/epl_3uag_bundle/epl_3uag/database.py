"""
database.py
───────────
SQLite persistence layer.

Schema
──────
  matches      – one row per match; stores goal sequence + 3UAG flag
  goals        – normalised goal-event log (one row per goal)
  fixtures     – one row per unordered club pair; aggregated H2H stats
  season_log   – audit trail: which seasons have been fully ingested

Public surface
──────────────
  get_connection(db_path)  → sqlite3.Connection
  transaction(conn)        → context manager for atomic writes
  create_schema(conn)
  upsert_match(conn, record)
  upsert_goals(conn, match_id, goals)
  rebuild_fixtures(conn)
  log_season(conn, season, match_count)
  ingested_seasons(conn)   → set[int]
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import DB_PATH


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open (or create) the SQLite database with WAL mode and FK enforcement."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row          # column-name indexing
    conn.execute("PRAGMA journal_mode=WAL") # concurrent-read safe
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic write block: commits on exit, rolls back on exception."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── Schema ────────────────────────────────────────────────────────────────────

def create_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema creation (IF NOT EXISTS on every object).
    Safe to call on an existing database — adds missing tables/indexes only.
    """
    statements = [
        # ── season audit log ──────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS season_log (
            season       INTEGER PRIMARY KEY,
            match_count  INTEGER NOT NULL DEFAULT 0,
            ingested_at  TEXT    NOT NULL
        )
        """,

        # ── match-level records ───────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS matches (
            match_id            TEXT    PRIMARY KEY,
            season              INTEGER NOT NULL,
            date                TEXT    NOT NULL,
            home_team           TEXT    NOT NULL,
            away_team           TEXT    NOT NULL,
            home_goals          INTEGER NOT NULL,
            away_goals          INTEGER NOT NULL,
            goal_sequence       TEXT    NOT NULL,           -- JSON ['H','A',…]
            has_three_uag       INTEGER NOT NULL DEFAULT 0, -- 0 | 1
            three_uag_details   TEXT    NOT NULL DEFAULT '[]' -- JSON run list
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(season)",
        "CREATE INDEX IF NOT EXISTS idx_matches_teams  ON matches(home_team, away_team)",

        # ── normalised goal events ────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS goals (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id  TEXT    NOT NULL REFERENCES matches(match_id),
            minute    INTEGER NOT NULL,
            team      TEXT    NOT NULL CHECK(team IN ('H','A')),
            player    TEXT    NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_goals_match ON goals(match_id)",

        # ── fixture-level H2H aggregates ─────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS fixtures (
            team1                      TEXT    NOT NULL,  -- alphabetically first
            team2                      TEXT    NOT NULL,  -- alphabetically second
            total_matches              INTEGER NOT NULL DEFAULT 0,
            matches_with_three_uag     INTEGER NOT NULL DEFAULT 0,
            matches_without_three_uag  INTEGER NOT NULL DEFAULT 0,
            qualifies                  INTEGER NOT NULL DEFAULT 0, -- 1 = never had 3UAG
            PRIMARY KEY (team1, team2)
        )
        """,
    ]

    for stmt in statements:
        conn.execute(stmt)
    conn.commit()


# ── Match persistence ─────────────────────────────────────────────────────────

def upsert_match(conn: sqlite3.Connection, record: dict) -> None:
    """
    Insert or replace a match record.
    `record` must contain all columns; goal_sequence and three_uag_details
    can be Python objects — they are JSON-serialised here.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO matches
            (match_id, season, date, home_team, away_team,
             home_goals, away_goals, goal_sequence,
             has_three_uag, three_uag_details)
        VALUES
            (:match_id, :season, :date, :home_team, :away_team,
             :home_goals, :away_goals, :goal_sequence,
             :has_three_uag, :three_uag_details)
        """,
        {
            **record,
            "goal_sequence":     json.dumps(record["goal_sequence"]),
            "three_uag_details": json.dumps(record.get("three_uag_details", [])),
        },
    )


def upsert_goals(conn: sqlite3.Connection, match_id: str, goals: list[dict]) -> None:
    """
    Replace all goal events for a match (delete + bulk insert).
    Each goal dict: {match_id?, minute, team, player}.
    """
    conn.execute("DELETE FROM goals WHERE match_id = ?", (match_id,))
    conn.executemany(
        "INSERT INTO goals (match_id, minute, team, player) VALUES (?,?,?,?)",
        [(match_id, g["minute"], g["team"], g["player"]) for g in goals],
    )


# ── Fixture aggregation ───────────────────────────────────────────────────────

def rebuild_fixtures(conn: sqlite3.Connection) -> None:
    """
    Recomputes the fixtures table entirely from the matches table.
    Fast O(n) SQL aggregation — safe to call after every season ingest.

    The unordered pair (team1, team2) is created by putting the
    alphabetically earlier name in team1, so each pair appears exactly once.
    """
    conn.execute("DELETE FROM fixtures")

    pair_expr   = "CASE WHEN home_team < away_team THEN home_team ELSE away_team END"
    other_expr  = "CASE WHEN home_team < away_team THEN away_team ELSE home_team END"

    conn.execute(
        f"""
        INSERT INTO fixtures
            (team1, team2, total_matches,
             matches_with_three_uag, matches_without_three_uag, qualifies)
        SELECT
            {pair_expr}  AS team1,
            {other_expr} AS team2,
            COUNT(*)                                          AS total_matches,
            SUM(has_three_uag)                                AS matches_with_three_uag,
            SUM(1 - has_three_uag)                            AS matches_without_three_uag,
            CASE WHEN SUM(has_three_uag) = 0 THEN 1 ELSE 0 END AS qualifies
        FROM matches
        GROUP BY {pair_expr}, {other_expr}
        """
    )
    conn.commit()


# ── Season audit log ──────────────────────────────────────────────────────────

def log_season(conn: sqlite3.Connection, season: int, match_count: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO season_log (season, match_count, ingested_at) VALUES (?,?,?)",
        (season, match_count, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def ingested_seasons(conn: sqlite3.Connection) -> set[int]:
    """Returns the set of seasons already fully committed to the DB."""
    rows = conn.execute("SELECT season FROM season_log").fetchall()
    return {r["season"] for r in rows}
