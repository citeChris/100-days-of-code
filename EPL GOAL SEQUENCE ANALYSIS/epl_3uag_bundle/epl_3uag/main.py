"""
main.py
───────
Pipeline entry-point.  Supports two modes:

  Understat-native (default):
    python main.py
    python main.py --seasons 2021 2022 2023
    python main.py --fresh

  Football-Data CSV path:
    python main.py --csv-dir ./data/raw
    python main.py --csv-dir ./data/raw --fresh

The CSV path reads your E0*.csv files, detects the season year from match
dates, links each match to its Understat ID via date + normalised team name,
then fetches shot data and runs the full 3UAG pipeline.

For a fully offline demo with synthetic data run:  python demo.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from config import TARGET_SEASONS
from updater import run_csv_update, run_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    p = argparse.ArgumentParser(description="EPL 3UAG Pipeline")
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--seasons", nargs="+", type=int, metavar="YEAR",
        help="Season start-years to ingest via Understat (default: all in config).",
    )
    src.add_argument(
        "--csv-dir", metavar="DIR",
        help="Load Football-Data E0*.csv files from this directory.",
    )
    p.add_argument("--fresh", action="store_true",
                   help="Wipe database and rebuild from scratch.")
    args = p.parse_args()

    if args.csv_dir:
        asyncio.run(run_csv_update(Path(args.csv_dir), fresh=args.fresh))
    else:
        seasons = args.seasons or TARGET_SEASONS
        asyncio.run(run_update(seasons=seasons, fresh=args.fresh))


if __name__ == "__main__":
    main()
