"""
linker.py
─────────
Joins Football-Data match records (which carry no Understat ID) to the
Understat season listing (which carries IDs but uses full club names).

The join key is:
    (YYYY-MM-DD date,  normalised home_team,  normalised away_team)

Both sides are normalised through processor.normalize_team() before
comparison, so abbreviation differences are resolved beforehand.

Why a dedicated module?
───────────────────────
Keeping the join logic separate makes it easy to debug mismatches and swap
in alternative ID-resolution strategies (e.g. fuzzy name matching) later.

Public API
──────────
  link_season(fd_matches, us_summaries)
        → matched:   list[LinkedMatch]
        → unmatched: list[FDMatch]          (logged as warnings)

LinkedMatch dict
────────────────
  match_id    str  — Understat ID (used for shot fetch)
  season      int
  fd_date     str  — YYYY-MM-DD
  home_team   str  — canonical
  away_team   str  — canonical
  home_goals  int
  away_goals  int
"""
from __future__ import annotations

import logging
from datetime import datetime

from processor import normalize_team

logger = logging.getLogger(__name__)


def _us_date(raw_datetime: str) -> str:
    """Extract YYYY-MM-DD from an Understat datetime string like '2023-10-08 16:30:00'."""
    try:
        return datetime.strptime(raw_datetime[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return raw_datetime[:10]


def _us_key(summary: dict) -> tuple[str, str, str]:
    """Build the normalised join key for one Understat summary row."""
    date      = _us_date(summary.get("datetime", ""))
    home_team = normalize_team(summary["h"]["title"])
    away_team = normalize_team(summary["a"]["title"])
    return (date, home_team, away_team)


def _fd_key(fd: dict) -> tuple[str, str, str]:
    """Build the normalised join key for one Football-Data row."""
    # fd_date is already YYYY-MM-DD from csv_loader
    return (fd["fd_date"], fd["home_team"], fd["away_team"])


def link_season(
    fd_matches: list[dict],
    us_summaries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Match Football-Data rows to Understat match IDs.

    Parameters
    ----------
    fd_matches    : output of csv_loader.load_csv()
    us_summaries  : output of fetcher.fetch_season() — completed matches only

    Returns
    -------
    (matched, unmatched)
      matched    : list[LinkedMatch] dicts ready for shot fetching
      unmatched  : list[FDMatch] rows that couldn't be paired (logged as warnings)
    """
    # Build lookup from (date, home, away) → Understat summary
    us_index: dict[tuple, dict] = {}
    for summary in us_summaries:
        key = _us_key(summary)
        if key in us_index:
            logger.warning("Duplicate Understat entry for key %s — keeping first.", key)
        else:
            us_index[key] = summary

    matched:   list[dict] = []
    unmatched: list[dict] = []

    for fd in fd_matches:
        key = _fd_key(fd)
        us  = us_index.get(key)

        if us is None:
            # Try date-only fallback (in case of rare timezone shift on date boundary)
            date_only_hits = [
                v for k, v in us_index.items()
                if k[0] == key[0] and k[1] == key[1] and k[2] == key[2]
            ]
            if date_only_hits:
                us = date_only_hits[0]

        if us is None:
            logger.warning(
                "No Understat match found for FD row: %s %s vs %s",
                fd["fd_date"], fd["home_team"], fd["away_team"],
            )
            unmatched.append(fd)
            continue

        matched.append({
            "match_id":   str(us["id"]),
            "season":     fd["season"],
            "fd_date":    fd["fd_date"],
            "home_team":  fd["home_team"],
            "away_team":  fd["away_team"],
            "home_goals": fd["home_goals"],
            "away_goals": fd["away_goals"],
        })

    pct = 100 * len(matched) / len(fd_matches) if fd_matches else 0
    logger.info(
        "Linking: %d matched, %d unmatched  (%.1f %% success rate)",
        len(matched), len(unmatched), pct,
    )
    return matched, unmatched


def report_unmatched(unmatched: list[dict]) -> None:
    """Print a diagnostic table of rows that couldn't be linked."""
    if not unmatched:
        print("  All matches linked successfully ✓")
        return
    print(f"\n  ⚠  {len(unmatched)} unmatched Football-Data rows:")
    print(f"  {'Date':<12}  {'Home':<30}  {'Away':<30}")
    print("  " + "─" * 74)
    for row in unmatched:
        print(f"  {row['fd_date']:<12}  {row['home_team']:<30}  {row['away_team']:<30}")
    print()
