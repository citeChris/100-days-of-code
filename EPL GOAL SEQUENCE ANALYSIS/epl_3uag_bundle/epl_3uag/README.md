# EPL Three-Unanswered-Goals (3UAG) Analysis Pipeline

End-to-end Python pipeline that fetches Premier League match data from
**Understat**, detects *three unanswered goals* events in every match,
and produces three analysis-ready CSV datasets.

---

## What is a "three unanswered goals" (3UAG) event?

A match contains a **3UAG event** when, at any point in the chronological
goal sequence, one team scores **three or more consecutive goals** without
the opposition scoring in between.

| Goal sequence       | 3UAG? | Why                                 |
|---------------------|-------|-------------------------------------|
| H H H               | ✓ YES | Home scores 3 on the trot           |
| H H A H H H         | ✓ YES | Home scores 3 unanswered at the end |
| H H A A H A         | ✗ NO  | Max consecutive run = 2             |
| A A A H A A         | ✓ YES | Away opens with 3 straight          |
| (0–0 draw)          | ✗ NO  | No goals                            |

---

## Project structure

```
epl_3uag/
├── config.py        # All constants (seasons, paths, threshold)
├── database.py      # SQLite schema + CRUD + fixture aggregation
├── fetcher.py       # Async Understat API with disk-based caching
├── processor.py     # Raw payload → structured GoalEvent records
├── analyzer.py      # 3UAG detection algorithm (O(n), single scan)
├── aggregator.py    # H2H fixture rollup + CSV export
├── updater.py       # Incremental season ingestion engine
├── main.py          # CLI entry-point for live pipeline
├── demo.py          # Fully offline demo with synthetic data
├── requirements.txt
└── data/
    ├── epl_3uag.db          # SQLite database
    ├── cache/seasons/       # Cached Understat season listings
    ├── cache/shots/         # Cached per-match shot payloads
    └── output/
        ├── match_level_dataset.csv
        ├── fixture_level_dataset.csv
        └── qualifying_fixtures.csv
```

---

## Installation

```bash
pip install -r requirements.txt
```

The demo needs only `pandas` and `tqdm`.
The live pipeline additionally needs `understat` and `aiohttp`.

---

## Quick start — offline demo

No internet connection required:

```bash
python demo.py
```

Generates 270 synthetic matches across 3 seasons, runs every pipeline
stage, prints annotated results, and writes the three output CSVs to
`data/demo_output/`.

---

## Live pipeline — real Understat data

```bash
# All seasons in config.TARGET_SEASONS (2014/15 → 2023/24)
python main.py

# Specific seasons only
python main.py --seasons 2021 2022 2023

# Wipe and rebuild from scratch
python main.py --fresh
```

The first run fetches from Understat and populates the disk cache.
Subsequent runs (or after a crash) use the cache and skip already-ingested
matches — making re-runs safe and fast.

---

## The 3UAG algorithm

**File:** `analyzer.py` → `analyse(goal_events)`

```
Input:  goal_events  – list of {minute, team ("H"/"A"), player}, sorted asc
Output: {flag: bool, runs: list[RunDict]}
```

```
Algorithm (single linear scan — O(n) time, O(1) auxiliary space):

  i = 0
  while i < n:
      mark run_start = i,  run_team = goal_events[i].team
      advance i while goal_events[i].team == run_team     ← extend run
      run_length = i - run_start
      if run_length >= THREE_UAG_THRESHOLD (default 3):
          record qualifying run with start/trigger/length details
```

Each `RunDict` carries:

| Field            | Description                              |
|------------------|------------------------------------------|
| `team`           | `"H"` or `"A"`                          |
| `start_minute`   | Minute of the run's first goal           |
| `trigger_minute` | Minute when the 3rd consecutive goal hit |
| `run_length`     | Total goals in the run (may exceed 3)    |
| `goals`          | `[{minute, player}, …]` for every goal   |

---

## Output datasets

### 1. `match_level_dataset.csv`

One row per match.

| Column             | Type    | Description                                      |
|--------------------|---------|--------------------------------------------------|
| `match_id`         | str     | Understat match identifier                       |
| `season`           | int     | Season start year (2014 = 2014/15)               |
| `date`             | str     | Match date-time                                  |
| `home_team`        | str     |                                                  |
| `away_team`        | str     |                                                  |
| `home_goals`       | int     |                                                  |
| `away_goals`       | int     |                                                  |
| `goal_sequence`    | str     | Ordered labels, e.g. `H→A→H→H→H`               |
| `has_three_uag`    | int     | `1` if any 3UAG run occurred, else `0`           |
| `three_uag_details`| JSON    | List of RunDicts (empty `[]` if no event)        |

### 2. `fixture_level_dataset.csv`

One row per unordered club pair (head-to-head record).

| Column                       | Type | Description                           |
|------------------------------|------|---------------------------------------|
| `team1`                      | str  | Alphabetically earlier club name      |
| `team2`                      | str  | Alphabetically later club name        |
| `total_matches`              | int  | All EPL meetings in the dataset       |
| `matches_with_three_uag`     | int  | Count with at least one 3UAG event    |
| `matches_without_three_uag`  | int  | Count with zero 3UAG events           |
| `qualifies`                  | int  | `1` if `matches_with_three_uag == 0`  |

### 3. `qualifying_fixtures.csv`

Filtered subset of (2): only rows where `qualifies == 1`.
These are fixtures where **no historical meeting** ever contained a 3UAG event.

---

## Database schema

```sql
-- Audit trail: which seasons are fully committed
CREATE TABLE season_log (
    season       INTEGER PRIMARY KEY,
    match_count  INTEGER,
    ingested_at  TEXT      -- UTC ISO-8601
);

-- One row per match
CREATE TABLE matches (
    match_id            TEXT PRIMARY KEY,
    season              INTEGER,
    date                TEXT,
    home_team           TEXT,
    away_team           TEXT,
    home_goals          INTEGER,
    away_goals          INTEGER,
    goal_sequence       TEXT,   -- JSON ['H','A','H',…]
    has_three_uag       INTEGER, -- 0 | 1
    three_uag_details   TEXT    -- JSON list of RunDicts
);

-- Normalised goal events (one row per goal)
CREATE TABLE goals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id  TEXT REFERENCES matches(match_id),
    minute    INTEGER,
    team      TEXT CHECK(team IN ('H','A')),
    player    TEXT
);

-- Pre-aggregated H2H stats
CREATE TABLE fixtures (
    team1                      TEXT,
    team2                      TEXT,
    total_matches              INTEGER,
    matches_with_three_uag     INTEGER,
    matches_without_three_uag  INTEGER,
    qualifies                  INTEGER,
    PRIMARY KEY (team1, team2)
);
```

---

## Stage 7 — Update methodology

The updater is designed around five principles:

| Principle   | Implementation                                                      |
|-------------|---------------------------------------------------------------------|
| Idempotent  | `season_log` guards re-ingestion; calling twice is safe             |
| Additive    | `INSERT OR REPLACE` never deletes existing rows                     |
| Minimal     | Existing `match_id` values are excluded before fetching shots       |
| Atomic      | Each season lands in a single `BEGIN … COMMIT` transaction          |
| Auditable   | `season_log` timestamps every successful ingest                     |

### Adding a new season

```bash
# When 2024/25 completes:
python updater.py --season 2024
```

What happens internally:

```
1. season_log query  →  2024 not present → proceed
2. fetch_season(2024) → match summaries (from API or cache)
3. diff vs matches table → identify new match_ids
4. for each new match_id:
     fetch_match_shots → extract_goal_timeline → analyse → build_record
5. single transaction: upsert_match + upsert_goals for all new matches
6. log_season(2024, n)
7. rebuild_fixtures()   ← fast SQL aggregation, always idempotent
8. export CSVs
```

### Changing the threshold

To rerun with `THREE_UAG_THRESHOLD = 4`:

1. Edit `config.py` → `THREE_UAG_THRESHOLD = 4`
2. Run `python updater.py --all --fresh`

The `--fresh` flag wipes the DB but **keeps the disk cache**, so no
network calls are made — all shot data is replayed from `data/cache/`.

### Partial-season ingestion (mid-season update)

Understat updates completed fixtures continuously. Running the updater
mid-season is safe:

```bash
python updater.py --season 2024
```

Only matches not yet in the DB are fetched. Run it weekly to stay current.

---

## Caching behaviour

| Cache file                       | Invalidated by              |
|----------------------------------|-----------------------------|
| `data/cache/seasons/<year>.json` | Delete to re-fetch          |
| `data/cache/shots/<id>.json`     | Never (shots are immutable) |

Season cache is intentionally not auto-expired — delete it manually to
pick up any Understat data corrections for a completed season.
