#!/usr/bin/env python3
"""
rescore.py
Re-evaluates R, U, V from the data already saved in t_eval_results.json, without
contacting the agent again: it reuses the persisted actual_tools and response_text
and re-reads them against the updated test set.

For V: it first attempts programmatic scoring (deterministic and free),
then — only if needed — the LLM judge, which now retries on its own every 2 seconds.

It is used to recover the V dimension after a run where the judge failed due to
load spikes (503), and to apply test-set corrections to the results.
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# The project root must be on the path: run_t_eval imports `src.core`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The Windows console is cp1252: force UTF-8 so accented characters don't crash it
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from run_t_eval import (
    load_test_set, load_results, save_results,
    score_R, score_U, score_V_programmatic, score_V_judge,
    compute_summary, print_summary, RESULTS_PATH,
)
from google import genai

# Separate progress file: {id: {"R":…, "U":…, "V":…}}. Every successful outcome
# is written here immediately, so nothing is lost and a rerun resumes from
# where we were — without re-calling the judge on already-judged cases.
PROGRESS_PATH = Path(__file__).parent / "t_eval_rescore_progress.json"

# Items whose ground truth was modified: the old saved V is stale,
# they must be re-judged even if they already have a valid score.
FORCE_REJUDGE = {"T005"}


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    tc_by_id = {tc["id"]: tc for tc in load_test_set()}
    data = load_results()
    progress = load_progress()
    # Same "credit" key used by the judge in run_t_eval.
    gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY_CREDIT"])

    if progress:
        print(f"[resume] {len(progress)} cases already in the progress file\n")

    judged = 0
    for r in data["results"]:
        tc = tc_by_id.get(r["id"])
        # Entries without a transcript (e.g. agent error) stay as they were
        if tc is None or "response_text" not in r or r.get("actual_tools") is None:
            print(f"  [{r['id']}] skip (no transcript)")
            continue

        rid = r["id"]
        tools = r["actual_tools"]
        # R and U are deterministic and free: always recompute them
        scores = {
            "R": score_R(tc["expected_tool"], tools),
            "U": score_U(tc.get("expected_args"), tools, tc["expected_tool"]),
        }

        # V already judged in a previous run (valid): reuse it, no call
        prev_v = (progress.get(rid) or {}).get("V")
        if prev_v and prev_v.get("score", -1) >= 0 and rid not in FORCE_REJUDGE:
            scores["V"] = prev_v
            tag = f"V={prev_v['score']:.2f} [progress]"
        else:
            v = score_V_programmatic(tc, r["response_text"])
            if v is not None:
                scores["V"] = v
                tag = f"V={v['score']:.2f} [{v.get('method')}]"
            else:
                v = score_V_judge(gemini, tc, r["response_text"])
                judged += 1
                tag = f"V=judge {v.get('score_raw', '?')}/5 ({v['score']})"
                time.sleep(2)
                # Persist only successful judgments: the -1.0s stay to be retried
                scores["V"] = v if v.get("score", -1) >= 0 else \
                    (prev_v if prev_v else v)

        print(f"  [{rid}] R={scores['R']['score']:.2f} U={scores['U']['score']:.2f} {tag}")

        # Write the progress file on every successful case
        progress[rid] = scores
        save_progress(progress)

    # ── Final merge into the main file ──────────────────────────────────────
    for r in data["results"]:
        if r["id"] in progress:
            r["scores"] = progress[r["id"]]
    data["summary"] = compute_summary(data["results"])
    data["rescored"] = datetime.now().isoformat()  # when the last re-score was done
    save_results(data)
    print(f"\n{judged} cases went through the judge in this run.")
    print(f"Progress: {PROGRESS_PATH}\nMain merge: {RESULTS_PATH}")
    print_summary(data["summary"])


if __name__ == "__main__":
    main()
