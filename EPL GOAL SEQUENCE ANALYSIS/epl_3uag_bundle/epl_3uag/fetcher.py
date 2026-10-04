"""
fetcher.py
──────────
Async data retrieval from Understat with disk-based JSON caching.

Two-level cache
───────────────
  data/cache/seasons/<season>.json   – match listing for the full season
  data/cache/shots/<match_id>.json   – shot payload for one match

If a cache file exists it is returned immediately; the Understat API is
only hit on a cache miss.  Delete a cache file to force a refresh.

Public API
──────────
  fetch_season(session, season)                 → list[dict]
  fetch_match_shots(session, match_id)          → dict
  fetch_matches_for_season(season, skip_ids)    → list[(summary, shots)]

Dependencies (install via requirements.txt):
  understat>=0.3.0
  aiohttp>=3.9.0
  tqdm>=4.66.0
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

# understat is imported lazily inside coroutines so the rest of the
# codebase (including demo.py) can import this module without the package.

from config import (
    API_DELAY_SECONDS,
    CACHE_DIR,
    LEAGUE,
    MAX_RETRIES,
    RETRY_BACKOFF,
    SEASONS_CACHE_DIR,
)

logger = logging.getLogger(__name__)


# ── Disk cache helpers ────────────────────────────────────────────────────────

def _cache_path(cache_dir: Path, key: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.json"


def _load(path: Path) -> Any | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt cache file %s (%s) — will re-fetch.", path, exc)
    return None


def _save(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ── Retry wrapper ─────────────────────────────────────────────────────────────

async def _with_retry(coro_fn, *args, retries: int = MAX_RETRIES, backoff: float = RETRY_BACKOFF):
    delay = 1.0
    for attempt in range(retries):
        try:
            return await coro_fn(*args)
        except Exception as exc:
            if attempt == retries - 1:
                raise
            logger.warning(
                "Attempt %d/%d failed: %s  – retrying in %.1fs",
                attempt + 1, retries, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= backoff


# ── Season-level fetch ────────────────────────────────────────────────────────

async def fetch_season(session: aiohttp.ClientSession, season: int) -> list[dict]:
    """
    Return the complete match listing for one EPL season.
    Only *completed* fixtures (isResult == True) are included.
    Results are cached; delete the cache file to force a re-fetch.
    """
    cache_path = _cache_path(SEASONS_CACHE_DIR, str(season))
    cached = _load(cache_path)
    if cached is not None:
        logger.debug("Season %d loaded from disk cache.", season)
        return [m for m in cached if m.get("isResult")]

    from understat import Understat

    logger.info("Fetching season %d from Understat API…", season)
    understat = Understat(session)
    results = await _with_retry(understat.get_league_results, LEAGUE, season)
    _save(cache_path, results)
    await asyncio.sleep(API_DELAY_SECONDS)
    return [m for m in results if m.get("isResult")]


# ── Match-level shot fetch ────────────────────────────────────────────────────

async def fetch_match_shots(session: aiohttp.ClientSession, match_id: str) -> dict:
    """
    Return the shot payload {h: [...], a: [...]} for a single match.
    Results are cached; delete the file to force a re-fetch.
    """
    cache_path = _cache_path(CACHE_DIR, match_id)
    cached = _load(cache_path)
    if cached is not None:
        return cached

    from understat import Understat

    logger.info("Fetching shots for match %s…", match_id)
    understat = Understat(session)
    shots = await _with_retry(understat.get_match_shots, match_id)
    _save(cache_path, shots)
    await asyncio.sleep(API_DELAY_SECONDS)
    return shots


# ── Bulk season fetch (used by updater) ──────────────────────────────────────

async def fetch_matches_for_season(
    season: int,
    existing_match_ids: set[str] | None = None,
) -> list[tuple[dict, dict]]:
    """
    Fetch all (or new) matches for a season.

    Parameters
    ----------
    season             : Understat start-year (e.g. 2023 for 2023/24)
    existing_match_ids : match IDs already in the DB — they are skipped

    Returns
    -------
    list of (match_summary_dict, shots_payload_dict) tuples
    """
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # graceful degradation if tqdm not installed

    async with aiohttp.ClientSession() as session:
        summaries = await fetch_season(session, season)

        if existing_match_ids:
            before = len(summaries)
            summaries = [m for m in summaries if str(m["id"]) not in existing_match_ids]
            logger.info(
                "Season %d: %d total matches, %d new (skipping %d already ingested).",
                season, before, len(summaries), before - len(summaries),
            )

        iterator = tqdm(summaries, desc=f"Season {season}", unit="match") \
                   if tqdm else summaries

        pairs: list[tuple[dict, dict]] = []
        for summary in iterator:
            try:
                shots = await fetch_match_shots(session, str(summary["id"]))
                pairs.append((summary, shots))
            except Exception as exc:
                logger.error("Failed to fetch match %s: %s", summary.get("id"), exc)

        return pairs


# ── Direct BS4 scraper (fallback / alternative to async understat lib) ────────
#
# Used when:
#   • the understat library is not installed
#   • get_match_shots() returns empty data for a specific match
#   • a caller prefers the synchronous requests-based path
#
# Based on the approach in the original prototype script.
# Requires: requests, beautifulsoup4  (pip install requests beautifulsoup4)

def fetch_goals_direct(match_id: str) -> list[dict]:
    """
    Synchronous fallback: scrape goal events directly from the Understat
    match page using requests + BeautifulSoup.

    Returns a list of {minute, team ("H"/"A"), player} dicts sorted by minute.
    Returns [] on any error (network, parse, or missing data).

    Parameters
    ----------
    match_id : Understat numeric match ID (as string or int)
    """
    import json as _json
    import re as _re

    try:
        import requests as _req
        from bs4 import BeautifulSoup as _BS
    except ImportError:
        logger.warning(
            "fetch_goals_direct requires 'requests' and 'beautifulsoup4'. "
            "Install with:  pip install requests beautifulsoup4"
        )
        return []

    url = f"https://understat.com/match/{match_id}"
    try:
        resp = _req.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("fetch_goals_direct(%s): request failed — %s", match_id, exc)
        return []

    soup = _BS(resp.content, "html.parser")

    # Understat embeds shot data as JSON.parse('…') inside a <script> block
    shots_data = None
    for script in soup.find_all("script"):
        if script.string and "shotsData" in script.string:
            m = _re.search(r"JSON\.parse\('([^']+)'\)", script.string)
            if m:
                try:
                    raw_json   = m.group(1).encode("utf-8").decode("unicode_escape")
                    shots_data = _json.loads(raw_json)
                    break
                except Exception as exc:
                    logger.warning("fetch_goals_direct(%s): JSON parse error — %s", match_id, exc)

    if not shots_data:
        logger.warning("fetch_goals_direct(%s): shotsData not found in page.", match_id)
        return []

    goals: list[dict] = []
    for side, label in (("h", "H"), ("a", "A")):
        for shot in shots_data.get(side, []):
            if shot.get("result") != "Goal":
                continue
            try:
                minute = int(shot["minute"])
            except (KeyError, ValueError, TypeError):
                minute = 0
            goals.append({
                "minute": minute,
                "team":   label,
                "player": shot.get("player", "Unknown"),
            })

    goals.sort(key=lambda g: g["minute"])
    logger.debug("fetch_goals_direct(%s): %d goals scraped.", match_id, len(goals))
    return goals


def shots_payload_from_goals(goals: list[dict]) -> dict:
    """
    Convert the flat goal list returned by fetch_goals_direct() into the
    standard {h: [...], a: [...]} shots payload expected by
    processor.extract_goal_timeline().

    Each goal is wrapped in a minimal shot-like dict so the rest of the
    pipeline doesn't need to know which fetcher was used.
    """
    payload: dict[str, list] = {"h": [], "a": []}
    for g in goals:
        side = "h" if g["team"] == "H" else "a"
        payload[side].append({
            "result": "Goal",
            "minute": str(g["minute"]),
            "player": g.get("player", "Unknown"),
        })
    return payload
