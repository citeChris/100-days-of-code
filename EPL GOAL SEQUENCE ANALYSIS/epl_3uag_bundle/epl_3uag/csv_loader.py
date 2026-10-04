"""
csv_loader.py
─────────────
Reads Football-Data.co.uk season CSV files and produces structured match
records compatible with the rest of the pipeline.

Football-Data column conventions
─────────────────────────────────
  Date       DD/MM/YY  (dayfirst=True)
  HomeTeam   abbreviated names — normalised via processor.TEAM_NAME_MAP
  AwayTeam   same
  FTHG       Full-Time Home Goals
  FTAG       Full-Time Away Goals

Season auto-detection
──────────────────────
The CSV files don't contain an explicit season column.  We infer the
Understat start-year (e.g. 2023 for 2023/24) from the median match date:
  median month Aug–Dec → start year = that calendar year
  median month Jan–May → start year = previous calendar year

Public API
──────────
  load_csv(path)          → list[FDMatch]  (single file)
  load_directory(dir)     → dict[int, list[FDMatch]]  (season → rows)
  detect_season(df)       → int  (Understat start-year)

FDMatch dict keys
─────────────────
  fd_date     str   "YYYY-MM-DD" (normalised)
  season      int   Understat start-year
  home_team   str   canonical (post-normalisation)
  away_team   str   canonical
  home_goals  int
  away_goals  int
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from processor import normalize_team

logger = logging.getLogger(__name__)

# Columns we need; others are ignored (odds, stats, etc.)
_REQUIRED_COLS = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"}


def detect_season(df: pd.DataFrame) -> int:
    """
    Infer the Understat season start-year from match dates in the DataFrame.

    Understat season key convention:
      2023  →  2023/24  (matches from Aug 2023 – May 2024)

    Strategy: take the median match date; if it falls in Aug-Dec use that
    calendar year, if Jan-May use year - 1.
    """
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dropna()
    if dates.empty:
        raise ValueError("No parseable dates found in CSV.")

    median_date = dates.sort_values().iloc[len(dates) // 2]
    year  = median_date.year
    month = median_date.month

    # Aug–Dec: season started this year;  Jan–May: season started last year
    season = year if month >= 8 else year - 1
    logger.debug("detect_season: median date %s → season %d", median_date.date(), season)
    return season


def _normalise_date(raw: str) -> str:
    """Convert Football-Data date (DD/MM/YY or DD/MM/YYYY) to YYYY-MM-DD."""
    try:
        return pd.to_datetime(raw, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return raw  # leave as-is if unparseable


def load_csv(path: str | Path) -> list[dict]:
    """
    Load a single Football-Data season CSV.

    Returns list of FDMatch dicts (one per completed match row).
    Rows with missing HomeTeam / AwayTeam are silently skipped.
    """
    path = Path(path)
    df = pd.read_csv(path, encoding="utf-8-sig")   # utf-8-sig strips BOM

    # Validate required columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    season = detect_season(df)

    records: list[dict] = []
    for _, row in df.iterrows():
        home_raw = row.get("HomeTeam")
        away_raw = row.get("AwayTeam")

        if pd.isna(home_raw) or pd.isna(away_raw):
            continue   # skip blank rows

        try:
            home_goals = int(row["FTHG"])
            away_goals = int(row["FTAG"])
        except (ValueError, TypeError):
            continue   # skip rows with non-numeric scores

        records.append({
            "fd_date":    _normalise_date(str(row["Date"])),
            "season":     season,
            "home_team":  normalize_team(str(home_raw)),
            "away_team":  normalize_team(str(away_raw)),
            "home_goals": home_goals,
            "away_goals": away_goals,
        })

    logger.info("Loaded %d matches from %s  (season %d)", len(records), path.name, season)
    return records


def load_directory(directory: str | Path) -> dict[int, list[dict]]:
    """
    Load all E0*.csv files found in `directory`.

    Returns {season_start_year: [FDMatch, …]} — seasons with duplicate
    inferred years are merged (shouldn't happen with standard FD naming,
    but handled gracefully).
    """
    directory = Path(directory)
    csv_files = sorted(directory.glob("E0*.csv"))

    if not csv_files:
        logger.warning("No E0*.csv files found in %s", directory)
        return {}

    season_map: dict[int, list[dict]] = {}
    for f in csv_files:
        try:
            rows = load_csv(f)
            if not rows:
                continue
            season = rows[0]["season"]
            if season in season_map:
                logger.warning(
                    "Season %d already loaded — merging %s (possible duplicate files).",
                    season, f.name,
                )
                season_map[season].extend(rows)
            else:
                season_map[season] = rows
        except Exception as exc:
            logger.error("Failed to load %s: %s", f.name, exc)

    logger.info(
        "Loaded %d seasons from %s: %s",
        len(season_map), directory, sorted(season_map.keys()),
    )
    return season_map
