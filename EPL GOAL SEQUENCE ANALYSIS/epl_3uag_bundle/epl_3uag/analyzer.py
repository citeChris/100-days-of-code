"""
analyzer.py
───────────
Three-Unanswered-Goals (3UAG) detection algorithm.

Definition
──────────
A match contains a 3UAG event when, at any contiguous point in the
chronological goal sequence, one team scores THREE or more consecutive
goals without the opposition scoring in between.

Example sequences
─────────────────
  [H, H, H, A]        → 3UAG (H scores 3 on the trot)
  [H, H, A, H, H, H]  → 3UAG (H scores 3 unanswered at the end)
  [H, H, A, A, H, A]  → no 3UAG (max run = 2)
  [A, A, A, H, A, A]  → 3UAG (A opens with 3, then scores 2 more later
                              — but the later run of 2 doesn't qualify)
  []                   → no 3UAG (scoreless draw)

Algorithm: single linear scan   O(n) time, O(1) auxiliary space
──────────────────────────────────────────────────────────────────
Walk the sorted goal list. Whenever the scoring team changes, check
whether the just-finished run is long enough (≥ THREE_UAG_THRESHOLD).
If yes, record it as a qualifying run.

Public API
──────────
  analyse(goal_events)  →  {"flag": bool, "runs": list[dict]}

RunDict keys
────────────
  team            "H" or "A"
  start_minute    minute of the run's first goal
  trigger_minute  minute when the count reached the threshold (3rd goal)
  run_length      total consecutive goals in this run (may exceed 3)
  goals           [{"minute": int, "player": str}, …]  full run detail
"""
from __future__ import annotations

from config import THREE_UAG_THRESHOLD


def analyse(goal_events: list[dict]) -> dict:
    """
    Parameters
    ----------
    goal_events : list of dicts, each with keys:
                    minute  (int)   – chronological order assumed
                    team    (str)   – "H" or "A"
                    player  (str)

    Returns
    -------
    dict
        {
          "flag" : bool,       True  if ≥1 qualifying run exists
          "runs" : list[dict]  details for every run that hit the threshold
        }
    """
    if len(goal_events) < THREE_UAG_THRESHOLD:
        return {"flag": False, "runs": []}

    qualifying_runs: list[dict] = []
    i = 0
    n = len(goal_events)

    while i < n:
        run_team  = goal_events[i]["team"]
        run_start = i

        # Advance i until the scoring team changes or we exhaust the list
        while i < n and goal_events[i]["team"] == run_team:
            i += 1

        run_goals  = goal_events[run_start:i]   # slice is a copy
        run_length = len(run_goals)

        if run_length >= THREE_UAG_THRESHOLD:
            qualifying_runs.append({
                "team":           run_team,
                "start_minute":   run_goals[0]["minute"],
                # Minute at which the threshold was exactly hit:
                "trigger_minute": run_goals[THREE_UAG_THRESHOLD - 1]["minute"],
                "run_length":     run_length,
                "goals": [
                    {"minute": g["minute"], "player": g["player"]}
                    for g in run_goals
                ],
            })

    return {
        "flag": len(qualifying_runs) > 0,
        "runs": qualifying_runs,
    }


# ── Convenience helpers ───────────────────────────────────────────────────────

def sequence_labels(goal_events: list[dict]) -> list[str]:
    """['H','A','H',…]  – the raw team-label sequence from event list."""
    return [e["team"] for e in goal_events]


def match_summary_line(record: dict) -> str:
    """Compact one-liner for logging / CLI display."""
    h  = record["home_team"]
    a  = record["away_team"]
    hg = record["home_goals"]
    ag = record["away_goals"]
    flag = "⚑ 3UAG" if record.get("has_three_uag") else "✓ clean"
    return f"[{record['season']}]  {h} {hg}–{ag} {a}   {flag}"


# ── Self-test ─────────────────────────────────────────────────────────────────

def _run_self_tests() -> None:
    """Verify the algorithm against hand-crafted cases."""
    def events(seq: list[str]) -> list[dict]:
        return [{"minute": i * 10 + 5, "team": t, "player": f"P{i}"}
                for i, t in enumerate(seq)]

    CASES: list[tuple[list[str], bool]] = [
        # Sequence                   Expected flag
        (["H", "H", "H"],              True),   # 3 straight home goals
        (["H", "H", "A", "H"],         False),  # max run = 2
        (["A", "A", "A", "H", "H"],    True),   # 3 consecutive away
        (["H", "H", "A", "A", "H", "H", "H"], True),  # 3 at the end
        (["H", "A", "H", "A", "H"],    False),  # alternating
        ([],                           False),  # scoreless
        (["H"],                        False),  # single goal
        (["H", "H"],                   False),  # two goals, same team
        (["H", "H", "H", "H"],         True),   # run of 4
        (["H", "H", "A", "A", "A"],    True),   # away 3UAG
    ]

    print("── Analyzer self-tests ──────────────────────────────────────")
    all_pass = True
    for seq, expected in CASES:
        result  = analyse(events(seq))
        passed  = result["flag"] == expected
        all_pass = all_pass and passed
        status  = "PASS" if passed else "FAIL ✗"
        run_len = result["runs"][0]["run_length"] if result["runs"] else 0
        print(f"  [{status}]  {str(seq):<45s}  expected={expected}  "
              f"got={result['flag']}  max_run={run_len}")

    verdict = "All tests PASSED ✓" if all_pass else "Some tests FAILED ✗"
    print(f"  → {verdict}")
    print()


if __name__ == "__main__":
    _run_self_tests()
