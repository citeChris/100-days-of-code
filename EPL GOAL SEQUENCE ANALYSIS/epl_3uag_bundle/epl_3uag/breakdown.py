"""
breakdown.py
────────────
Exact breakdown of every match across all E0*.csv seasons.

Run from the folder that contains your E0*.csv files:

    python breakdown.py                        # looks in current directory
    python breakdown.py --csv-dir ./data/raw   # explicit directory
    python breakdown.py --season 2023          # single season only

Outputs (no internet required for this part):
  • Per-season team list + match count
  • Full match list with normalised names + FT scores
  • Score-distribution summary
  • Fixture pair counts (how many times each pair has met)

Note: 3UAG flags need goal-event timelines from Understat.
      To add those, run:  python main.py --csv-dir <dir>
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# ── make pipeline imports work whether run from project root or anywhere ──────
sys.path.insert(0, str(Path(__file__).parent))
from csv_loader import load_directory, load_csv
from processor import normalize_team, get_canonical_fixture


def breakdown(csv_dir: Path) -> None:
    season_map = load_directory(csv_dir)
    if not season_map:
        print(f"No E0*.csv files found in {csv_dir}")
        return

    all_matches: list[dict] = []

    for season in sorted(season_map):
        rows   = season_map[season]
        teams  = sorted({r["home_team"] for r in rows} | {r["away_team"] for r in rows})
        scores = Counter(f"{r['home_goals']}-{r['away_goals']}" for r in rows)
        total  = len(rows)
        with_goals = sum(1 for r in rows if r["home_goals"] + r["away_goals"] > 0)

        print(f"\n{'═' * 66}")
        print(f"  SEASON {season}/{str(season+1)[-2:]}  —  {total} matches  —  {len(teams)} teams")
        print(f"{'═' * 66}")
        print(f"  Teams: {', '.join(teams)}")

        print(f"\n  Score distribution (top 10):")
        for score, n in scores.most_common(10):
            bar = "█" * n
            print(f"    {score:>5}  {bar:<40}  {n:>3}")

        print(f"\n  Goals scored    : {sum(r['home_goals']+r['away_goals'] for r in rows)} total")
        print(f"  Avg goals/match : {sum(r['home_goals']+r['away_goals'] for r in rows)/total:.2f}")
        print(f"  Home wins       : {sum(1 for r in rows if r['home_goals'] > r['away_goals'])}")
        print(f"  Draws           : {sum(1 for r in rows if r['home_goals'] == r['away_goals'])}")
        print(f"  Away wins       : {sum(1 for r in rows if r['home_goals'] < r['away_goals'])}")
        print(f"  Goalless draws  : {sum(1 for r in rows if r['home_goals'] == 0 and r['away_goals'] == 0)}")

        all_matches.extend(rows)

    # ── Cross-season fixture counts ────────────────────────────────────────────
    print(f"\n{'═' * 66}")
    print(f"  ALL SEASONS COMBINED  —  {len(all_matches)} matches")
    print(f"{'═' * 66}")

    fixture_counts: Counter = Counter()
    for r in all_matches:
        fix = get_canonical_fixture(r["home_team"], r["away_team"])
        fixture_counts[fix] += 1

    total_pairs = len(fixture_counts)
    print(f"\n  Unique H2H fixture pairs : {total_pairs}")
    print(f"  Meetings per pair        : {len(all_matches) / total_pairs:.1f} avg")

    print(f"\n  Pairs by meeting count:")
    count_of_counts = Counter(fixture_counts.values())
    for n_meetings in sorted(count_of_counts):
        print(f"    {n_meetings} meetings : {count_of_counts[n_meetings]} pairs")

    # ── Full match list ────────────────────────────────────────────────────────
    print(f"\n  Full match list (all seasons):")
    print(f"  {'Season':<10}  {'Date':<12}  {'Home':<28}  {'Score':>5}  {'Away':<28}")
    print(f"  {'─'*10}  {'─'*12}  {'─'*28}  {'─'*5}  {'─'*28}")
    for r in sorted(all_matches, key=lambda x: (x["season"], x["fd_date"])):
        score = f"{r['home_goals']}-{r['away_goals']}"
        print(
            f"  {str(r['season'])+'/'+ str(r['season']+1)[-2:]:<10}  "
            f"{r['fd_date']:<12}  "
            f"{r['home_team']:<28}  "
            f"{score:>5}  "
            f"{r['away_team']:<28}"
        )

    print(f"\n  Total: {len(all_matches)} matches across {len(season_map)} seasons.")
    print(f"\n  To add 3UAG flags (needs Understat):")
    print(f"    python main.py --csv-dir {csv_dir}")


def main() -> None:
    p = argparse.ArgumentParser(description="EPL CSV match breakdown")
    p.add_argument("--csv-dir", default=".", metavar="DIR",
                   help="Directory containing E0*.csv files (default: current dir).")
    p.add_argument("--season",  type=int, default=None, metavar="YEAR",
                   help="Show one season only (start year, e.g. 2022).")
    args = p.parse_args()

    breakdown(Path(args.csv_dir))


if __name__ == "__main__":
    main()
