"""
processor.py
────────────
Transforms raw Understat API payloads into the structured records
consumed by analyzer.py and database.py.

Also owns team-name normalisation so that Football-Data.co.uk abbreviated
names ("Man United", "Wolves", "Nott'm Forest", …) map reliably to the
canonical Understat names used in goal-event data.  This prevents silent
join failures when matching Football-Data match listings to Understat IDs.

Public API
──────────
  normalize_team(name)                   str  – canonical Understat name
  get_canonical_fixture(team_a, team_b)  str  – alphabetically sorted pair label
  parse_match_summary(raw)               dict – flattened Understat match meta
  extract_goal_timeline(shots, id)       list – chronological GoalEvent dicts
  build_match_record(meta, evts, ana)    dict – DB-ready flat record
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Team-name normalisation ───────────────────────────────────────────────────
# Maps every Football-Data.co.uk abbreviation / variant → Understat canonical.
# Understat uses full official club names; Football-Data often abbreviates.
# Extend this dict whenever a new team is promoted to the Premier League.

TEAM_NAME_MAP: dict[str, str] = {
    # Manchester clubs
    "Man United":               "Manchester United",
    "Man Utd":                  "Manchester United",
    "Manchester Utd":           "Manchester United",
    "Man City":                 "Manchester City",
    # North-East
    "Newcastle":                "Newcastle United",
    # Midlands
    "Wolves":                   "Wolverhampton Wanderers",
    "Wolverhampton":            "Wolverhampton Wanderers",
    "Nott'm Forest":            "Nottingham Forest",
    "Nottm Forest":             "Nottingham Forest",
    "Nottingham":               "Nottingham Forest",
    "Leicester":                "Leicester City",
    # South Coast
    "Bournemouth":              "Bournemouth",
    "AFC Bournemouth":          "Bournemouth",   # Understat uses short form
    "Brighton":                 "Brighton",
    "Brighton & HA":            "Brighton",
    "Brighton & Hove Albion":   "Brighton",
    "Southampton":              "Southampton",
    # London
    "West Ham":                 "West Ham United",
    "Tottenham":                "Tottenham Hotspur",
    "Spurs":                    "Tottenham Hotspur",
    # Yorkshire
    "Leeds":                    "Leeds United",
    "Sheffield United":         "Sheffield United",
    "Sheffield Utd":            "Sheffield United",
    "Sheff Utd":                "Sheffield United",
    # East Anglia
    "Ipswich":                  "Ipswich Town",
    "Norwich":                  "Norwich City",
    # Other
    "Luton":                    "Luton Town",
    # Clubs whose FD name already matches Understat (listed for completeness)
    "Arsenal":                  "Arsenal",
    "Aston Villa":              "Aston Villa",
    "Brentford":                "Brentford",
    "Burnley":                  "Burnley",
    "Chelsea":                  "Chelsea",
    "Crystal Palace":           "Crystal Palace",
    "Everton":                  "Everton",
    "Fulham":                   "Fulham",
    "Liverpool":                "Liverpool",
    "Watford":                  "Watford",
}


def normalize_team(name: str) -> str:
    """
    Return the canonical Understat team name for `name`.
    Falls back to the stripped original if not in the map — this allows
    forward-compatibility with newly promoted clubs before the map is updated.
    """
    stripped = name.strip()
    canonical = TEAM_NAME_MAP.get(stripped, stripped)
    if canonical == stripped and stripped not in TEAM_NAME_MAP:
        logger.debug("normalize_team: '%s' not in TEAM_NAME_MAP — using as-is.", stripped)
    return canonical


def get_canonical_fixture(team_a: str, team_b: str) -> str:
    """
    Produce a stable fixture label for any home/away combination.
    Sorts alphabetically so "Arsenal vs Chelsea" == "Chelsea vs Arsenal".

    Example:  get_canonical_fixture("Man City", "Wolves")
              → "Manchester City vs Wolverhampton Wanderers"
    """
    teams = sorted([normalize_team(team_a), normalize_team(team_b)])
    return f"{teams[0]} vs {teams[1]}"


# ── Understat payload parsing ─────────────────────────────────────────────────

_GOAL_RESULTS = {"Goal", "OwnGoal"}


def parse_match_summary(raw: dict[str, Any]) -> dict:
    """
    Flatten a single entry from Understat get_league_results() into a plain
    dict.  Team names are normalised here so downstream joins use consistent
    labels regardless of source.
    """
    def _goals(side: str) -> int:
        val = raw.get("goals", {}).get(side)
        try:
            return int(val) if val is not None else 0
        except (ValueError, TypeError):
            return 0

    return {
        "match_id":   str(raw["id"]),
        "season":     int(raw.get("season", 0)),   # overridden by updater
        "date":       raw.get("datetime", ""),
        "home_team":  normalize_team(raw["h"]["title"]),
        "away_team":  normalize_team(raw["a"]["title"]),
        "home_goals": _goals("h"),
        "away_goals": _goals("a"),
    }


def extract_goal_timeline(
    shots_payload: dict[str, Any],
    match_id: str,
) -> list[dict]:
    """
    Filter the Understat shot payload to goals only and return them sorted
    chronologically.  Tiebreak within the same minute: home before away.
    """
    events: list[dict] = []

    for side, label in (("h", "H"), ("a", "A")):
        side_order = 0 if label == "H" else 1
        for shot in shots_payload.get(side, []):
            if shot.get("result") not in _GOAL_RESULTS:
                continue
            try:
                minute = int(shot.get("minute", 0))
            except (ValueError, TypeError):
                logger.warning(
                    "match %s: non-numeric minute '%s' — defaulting to 0",
                    match_id, shot.get("minute"),
                )
                minute = 0

            events.append({
                "match_id":    match_id,
                "minute":      minute,
                "_side_order": side_order,
                "team":        label,
                "player":      shot.get("player", "Unknown"),
            })

    events.sort(key=lambda e: (e["minute"], e["_side_order"]))
    for e in events:
        del e["_side_order"]

    return events


def build_match_record(
    meta: dict,
    goal_events: list[dict],
    analysis: dict,
) -> dict:
    """Merge metadata + timeline + analysis into one DB-ready flat record."""
    return {
        **meta,
        "goal_sequence":     [e["team"] for e in goal_events],
        "has_three_uag":     int(analysis["flag"]),
        "three_uag_details": analysis["runs"],
    }
