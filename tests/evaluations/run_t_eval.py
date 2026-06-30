#!/usr/bin/env python3
"""
run_t_eval.py
Runs the T-Eval test set against the live agent and produces t_eval_results.json.

Dimensions evaluated for each question:
  R  — Retrieve:            was the correct tool selected?
  U  — Understand/Instruct: are the passed parameters correct?
  V  — Review:              is the final answer correct? (programmatic + LLM judge)

Resume-safe: saves after each question; rerun and it picks up where it stopped.
"""

import os
import sys
import json
import time
import re
import asyncio
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

from src.core import Agent
from google import genai
from google.genai import types

# ── Paths ─────────────────────────────────────────────────────────────────────
TEST_SET_PATH = Path(__file__).parent / "t_eval_test_set.json"
RESULTS_PATH  = Path(__file__).parent / "t_eval_results.json"

# Seconds between one API call and the next to avoid rate limits
API_DELAY = 5


# ══════════════════════════════════════════════════════════════════════════════
# Cache / persistence
# ══════════════════════════════════════════════════════════════════════════════

def load_test_set() -> list[dict]:
    return json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))["test_cases"]


def load_results() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {"started": datetime.now().isoformat(), "results": []}


def save_results(data: dict) -> None:
    RESULTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Dimensione R — Tool selection
# ══════════════════════════════════════════════════════════════════════════════

def score_R(expected_tool: str, actual_tools: list[dict]) -> dict:
    """
    Score 0.0 / 0.5 / 1.0.

    expected_tool can be:
      "count_events"                  → single tool
      "rank_by_count + percentage"    → tool sequence
      "REFUSAL"                       → no tool expected
    """
    actual_names = [t["tool"] for t in actual_tools]

    if expected_tool == "REFUSAL":
        if not actual_tools:
            return {"score": 1.0, "detail": "no tool called (correct)"}
        return {"score": 0.0, "detail": f"tools called even though it should have refused: {actual_names}"}

    parts = [p.strip() for p in expected_tool.split("+")]

    if not actual_tools:
        return {"score": 0.0, "detail": f"no tool called; expected: {parts}"}

    # A "part" can list equivalent tools separated by "|" — for questions
    # solvable via different paths (e.g. "count_events|rank_by_count"): it is
    # enough that one of the alternatives appears.
    def _alts(part: str) -> list[str]:
        return [a.strip() for a in part.split("|")]

    if len(parts) == 1:
        alts = _alts(parts[0])
        if actual_names[0] in alts:
            return {"score": 1.0, "detail": f"correct: {actual_names[0]}"}
        if any(a in actual_names for a in alts):
            return {"score": 0.5, "detail": f"tool present but not first — expected={parts[0]}, sequence={actual_names}"}
        return {"score": 0.0, "detail": f"wrong tool — expected={parts[0]}, got={actual_names}"}

    # Multi-tool: each expected part must appear (in any order)
    hits = sum(1 for p in parts if any(a in actual_names for a in _alts(p)))
    score = round(hits / len(parts), 2)
    return {
        "score": score,
        "detail": f"{hits}/{len(parts)} expected tools present; actual sequence: {actual_names}",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Dimensione U — Parameter accuracy
# ══════════════════════════════════════════════════════════════════════════════

def _match_arg(expected, actual) -> bool:
    """Loose comparison: handles ISO 8601 dates, bool, int, str."""
    if expected is None:
        return True
    if isinstance(expected, bool):
        return actual is not None and bool(actual) == expected
    if isinstance(expected, int):
        try:
            return int(actual) == expected
        except (TypeError, ValueError):
            return False
    if isinstance(expected, float):
        try:
            return abs(float(actual) - expected) < 0.01
        except (TypeError, ValueError):
            return False
    if isinstance(expected, str):
        # For dates, compare only the YYYY-MM-DD part
        if "T" in expected:
            exp_date = expected[:10]
            act_date = str(actual)[:10] if actual else ""
            return exp_date == act_date
        return str(actual) == expected
    return actual == expected


def score_U(
    expected_args: dict | list | None,
    actual_tools: list[dict],
    expected_tool: str,
) -> dict:
    if expected_tool == "REFUSAL":
        if not actual_tools:
            return {"score": 1.0, "detail": "no arg expected (refusal)"}
        return {"score": 0.0, "detail": "tools called when it should have refused"}

    if not actual_tools:
        return {"score": 0.0, "detail": "no tool called"}

    # Multi-tool: evaluate only the first tool of the sequence
    if isinstance(expected_args, list):
        first_expected = expected_args[0] if expected_args else {}
        first_tool_name = expected_tool.split("+")[0].strip()
        return score_U(first_expected, actual_tools[:1], first_tool_name)

    # No filter expected
    if not expected_args:
        return {"score": 1.0, "detail": "no arg expected"}

    actual_args = actual_tools[0].get("args", {})
    total   = len(expected_args)
    correct = 0
    wrong   = []

    for key, exp_val in expected_args.items():
        act_val = actual_args.get(key)
        if _match_arg(exp_val, act_val):
            correct += 1
        else:
            wrong.append(f"{key}: expected={exp_val!r} got={act_val!r}")

    score = round(correct / total, 2)
    detail = f"{correct}/{total} arguments correct"
    if wrong:
        detail += " | wrong: " + "; ".join(wrong)
    return {"score": score, "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# Dimensione V — Response quality
# ══════════════════════════════════════════════════════════════════════════════

_REFUSAL_KW = [
    "i can't", "i cannot", "not relevant", "out of scope",
    "i'm not able", "i am not able", "i only handle", "i can only",
    "i'm only", "outside my scope", "not my area", "i don't have access",
    "only about events", "i'm not specialized",
]
_NOT_FOUND_KW = [
    "not found", "does not exist", "doesn't exist", "couldn't find",
    "could not find", "no event", "no such event", "non-existent",
]


def _label_in_text(label: str, text: str) -> bool:
    """Match of a text label tolerant to the short form.
    Agents abbreviate camera names: 'Uscita Pedane Bottom Extended' → 'Uscita Pedane'."""
    low = text.lower()
    lab = label.lower().strip()
    if lab and lab in low:
        return True
    short = lab.replace(" bottom extended", "").strip()
    return bool(short) and short != lab and short in low


def _parse_number(tok: str) -> float | None:
    """Parses a numeric token handling both IT and EN styles.

    The crux is the dot: in "1.250" it is a thousands separator (=1250), in "5.33" it
    is a decimal. Deterministic rule: the dot is thousands only if every group that
    follows it is exactly 3 digits; otherwise it is a decimal point.
    """
    tok = tok.strip(".,")  # drop any trailing punctuation ("165." → "165")
    has_dot, has_comma = "." in tok, "," in tok

    if has_dot and has_comma:
        # The last separator that appears is the decimal (1.250,33 IT / 1,250.33 EN)
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif has_comma:
        tok = tok.replace(",", ".")                       # decimal comma: 7,01
    elif has_dot:
        groups = tok.split(".")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            tok = tok.replace(".", "")                     # thousands: 1.250 → 1250
        # otherwise the dot stays decimal: 5.33, 7.01

    try:
        return float(tok)
    except ValueError:
        return None


def _extract_numbers(text: str) -> list[float]:
    """Extracts all numbers from the text (IT and EN separators, see _parse_number)."""
    return [n for tok in re.findall(r"\d[\d.,]*", text)
            if (n := _parse_number(tok)) is not None]


def score_V_programmatic(tc: dict, response_text: str) -> dict | None:
    """
    Attempts a programmatic evaluation.
    Returns None if the LLM judge is needed.
    """
    gt_type = tc.get("ground_truth_type")
    gt      = tc.get("ground_truth")

    # Refusal
    if gt_type == "refusal":
        low = response_text.lower()
        for kw in _REFUSAL_KW:
            if kw in low:
                return {"score": 1.0, "method": "keyword",
                        "detail": f"refusal keyword found: '{kw}'"}
        # It may have refused without exact keywords — leave it to the judge
        return None

    # Not-found (non-existent event_id)
    if gt_type == "not_found":
        low = response_text.lower()
        # Regex for verbal forms ("was not found", "couldn't find …")
        if re.search(r"\b(?:not|n't|couldn't|could not)\b.{0,25}(?:found|find)", low):
            return {"score": 1.0, "method": "keyword",
                    "detail": "response indicates a non-existent event"}
        for kw in _NOT_FOUND_KW:
            if kw in low:
                return {"score": 1.0, "method": "keyword",
                        "detail": f"not-found keyword found: '{kw}'"}
        return {"score": 0.0, "method": "keyword",
                "detail": "no 'not found' indication in the response"}

    # Exact numbers
    if gt_type in ("exact_integer", "exact_float") and isinstance(gt, (int, float)):
        target = float(gt)
        nums   = _extract_numbers(response_text)
        if any(abs(n - target) < 0.05 for n in nums):
            return {"score": 1.0, "method": "numeric",
                    "detail": f"value {gt} found in the response"}
        if nums:
            # The number is in the response but does not match: leave it to the judge
            return None
        # No number: definitely missing
        return {"score": 0.0, "method": "numeric",
                "detail": f"no number in the response; expected {gt}"}

    # Top/bottom value as text (e.g. "Uscita Pedane with 630 events")
    if gt_type in ("top_value", "peak_value", "bottom_value") and isinstance(gt, str):
        gtn = tc.get("ground_truth_numeric", {})
        hits = 0
        label = (gtn.get("top_value") or gtn.get("bottom_value")
                 or gtn.get("peak_date") or gtn.get("peak_weekday"))
        if label and _label_in_text(str(label), response_text):
            hits += 1
        count_key = (gtn.get("top_count") or gtn.get("peak_count")
                     or gtn.get("bottom_count"))
        if count_key:
            nums = _extract_numbers(response_text)
            if any(abs(n - float(count_key)) < 0.5 for n in nums):
                hits += 1
        if hits == 2:
            return {"score": 1.0, "method": "text+numeric",
                    "detail": "label and count correct in the response"}
        return None  # partial or without anchors: leave it to the judge

    # summary_dict / chart_summary: if the GT exposes strong counts, verify them
    # directly instead of going through the judge (deterministic and free).
    if gt_type in ("summary_dict", "chart_summary") and isinstance(gt, dict):
        counts = [gt[k] for k in ("top_count", "peak_count", "total_events")
                  if isinstance(gt.get(k), (int, float))]
        if counts:
            nums = _extract_numbers(response_text)
            counts_ok = all(any(abs(n - float(c)) < 0.5 for n in nums) for c in counts)
            label = gt.get("top_value") or gt.get("peak_weekday")
            label_ok = (label is None) or _label_in_text(str(label), response_text)
            if counts_ok and label_ok:
                return {"score": 1.0, "method": "text+numeric",
                        "detail": "key summary values found in the response"}
        return None

    # For everything else (ranked_list, exact_record, derived, etc.)
    return None


# ── LLM Judge ─────────────────────────────────────────────────────────────────

# How many times to retry the judge (2s each) before giving up. Kept low
# on purpose: if the quota is exhausted (429) there is no point insisting and
# burning calls — better to fail early, save the rest, and resume later.
_JUDGE_MAX_ATTEMPTS = 8

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "score":        {"type": "integer"},
        "correctness":  {"type": "integer"},
        "completeness": {"type": "integer"},
        "note":         {"type": "string"},
    },
    "required": ["score", "correctness", "completeness", "note"],
}


def score_V_judge(gemini_client, tc: dict, response_text: str) -> dict:
    """LLM-as-judge for cases that the programmatic evaluation does not cover."""
    gt = tc.get("ground_truth")
    gt_str = json.dumps(gt, ensure_ascii=False) if gt is not None else "not specified"

    prompt = (
        f'Question asked to the agent:\n"{tc["question"]}"\n\n'
        f"Expected ground truth:\n{gt_str}\n\n"
        f"Agent's answer:\n{response_text}\n\n"
        "Evaluate the agent's answer on a 1-5 scale:\n"
        "  score (1-5): overall quality of the answer\n"
        "  correctness (1-5): do the numeric/factual data match the ground truth?\n"
        "  completeness (1-5): does it address every aspect of the question?\n"
        "  note: brief rationale (max 2 lines)\n"
        "If the ground truth is 'not specified', evaluate only coherence and completeness relative to the question."
    )

    # Simple retry at a fixed 2s interval: the judge runs on the same model
    # as the agent, and during load spikes (503) you just need to retry calmly.
    for attempt in range(1, _JUDGE_MAX_ATTEMPTS + 1):
        try:
            resp = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an impartial evaluator of AI agents. Reply only with valid JSON.",
                    response_mime_type="application/json",
                    response_schema=_JUDGE_SCHEMA,
                ),
            )
            if not resp.text:
                raise ValueError("empty judge response")
            parsed = json.loads(resp.text)
            return {
                "score":        round(parsed["score"] / 5.0, 2),
                "score_raw":    parsed["score"],
                "correctness":  parsed["correctness"],
                "completeness": parsed["completeness"],
                "note":         parsed.get("note", ""),
                "method":       "llm_judge",
            }
        except Exception as e:
            print(f"    [judge attempt {attempt} failed: {e.__class__.__name__} – retry in 2s]")
            time.sleep(2)

    return {"score": -1.0, "method": "llm_judge",
            "note": f"judge failed after {_JUDGE_MAX_ATTEMPTS} attempts"}


# ══════════════════════════════════════════════════════════════════════════════
# Summary finale
# ══════════════════════════════════════════════════════════════════════════════

def _safe_avg(values: list[float]) -> float | None:
    valid = [v for v in values if v >= 0]
    return round(sum(valid) / len(valid), 3) if valid else None


def compute_summary(results: list[dict]) -> dict:
    # Cases that render a chart (ground_truth_type=chart_summary) are excluded
    # from V: the judge only sees the text, not the chart, so it would penalize
    # them unfairly. They are still counted on R and U (the tool choice is valid).
    chart_ids = {tc["id"] for tc in load_test_set()
                 if tc.get("ground_truth_type") == "chart_summary"}

    in_scope = [r for r in results if r.get("tool") != "out_of_scope"]
    oos      = [r for r in results if r.get("tool") == "out_of_scope"]

    def dim_scores(subset: list[dict], dim: str) -> list[float]:
        return [r["scores"][dim]["score"] for r in subset
                if r.get("scores", {}).get(dim)
                and not (dim == "V" and r["id"] in chart_ids)]

    # Per tool
    by_tool: dict[str, dict] = {}
    for r in in_scope:
        tool = r.get("tool", "unknown")
        if tool not in by_tool:
            by_tool[tool] = {"n": 0, "R": [], "U": [], "V": []}
        by_tool[tool]["n"] += 1
        for dim in ("R", "U", "V"):
            if dim == "V" and r["id"] in chart_ids:
                continue
            s = r.get("scores", {}).get(dim, {}).get("score", -1)
            if s >= 0:
                by_tool[tool][dim].append(s)

    by_tool_summary = {
        t: {
            "n": d["n"],
            "R": _safe_avg(d["R"]),
            "U": _safe_avg(d["U"]),
            "V": _safe_avg(d["V"]),
        }
        for t, d in by_tool.items()
    }

    # Per difficulty
    by_diff: dict[str, dict] = {}
    for r in results:
        diff = r.get("difficulty", "unknown")
        if diff not in by_diff:
            by_diff[diff] = {"n": 0, "R": [], "U": [], "V": []}
        by_diff[diff]["n"] += 1
        for dim in ("R", "U", "V"):
            if dim == "V" and r["id"] in chart_ids:
                continue
            s = r.get("scores", {}).get(dim, {}).get("score", -1)
            if s >= 0:
                by_diff[diff][dim].append(s)

    by_difficulty = {
        d: {"n": v["n"], "R": _safe_avg(v["R"]), "U": _safe_avg(v["U"]), "V": _safe_avg(v["V"])}
        for d, v in by_diff.items()
    }

    return {
        "total":           len(results),
        "in_scope":        len(in_scope),
        "out_of_scope":    len(oos),
        "R_accuracy":      _safe_avg(dim_scores(in_scope, "R")),
        "U_accuracy":      _safe_avg(dim_scores(in_scope, "U")),
        "V_score":         _safe_avg(dim_scores(results, "V")),
        "V_charts_excluded": sorted(chart_ids),
        "refusal_rate":    _safe_avg(dim_scores(oos, "R")),
        "by_tool":         by_tool_summary,
        "by_difficulty":   by_difficulty,
        "token_totals": {
            "prompt":   sum(r.get("usage", {}).get("prompt_tokens", 0) for r in results),
            "output":   sum(r.get("usage", {}).get("output_tokens", 0) for r in results),
            "total":    sum(r.get("usage", {}).get("total_tokens", 0) for r in results),
            "thinking": sum(r.get("usage", {}).get("thinking_tokens", 0) for r in results),
            "cached":   sum(r.get("usage", {}).get("cached_tokens", 0) for r in results),
        },
    }


def print_summary(s: dict) -> None:
    print(f"\n{'='*64}")
    print("T-EVAL RESULTS SUMMARY")
    print(f"{'='*64}")
    print(f"  Total tests:        {s['total']}")
    print(f"  In-scope:           {s['in_scope']}")
    print(f"  Out-of-scope:       {s['out_of_scope']}")
    print(f"  R  Tool selection:  {s['R_accuracy']:.3f}")
    print(f"  U  Param accuracy:  {s['U_accuracy']:.3f}")
    print(f"  V  Answer quality:  {s['V_score']:.3f}  ({len(s.get('V_charts_excluded', []))} chart cases excluded)")
    print(f"  Refusal rate:       {s['refusal_rate']:.3f}")
    print()
    print(f"  {'Tool':<40} {'n':>3}  {'R':>6}  {'U':>6}  {'V':>6}")
    print(f"  {'-'*40} {'---':>3}  {'------':>6}  {'------':>6}  {'------':>6}")
    for tool, m in sorted(s["by_tool"].items()):
        R = f"{m['R']:.2f}" if m["R"] is not None else "  —  "
        U = f"{m['U']:.2f}" if m["U"] is not None else "  —  "
        V = f"{m['V']:.2f}" if m["V"] is not None else "  —  "
        print(f"  {tool:<40} {m['n']:>3}  {R:>6}  {U:>6}  {V:>6}")
    print()
    print(f"  {'Difficulty':<15} {'n':>3}  {'R':>6}  {'U':>6}  {'V':>6}")
    for diff in ("easy", "medium", "hard"):
        m = s["by_difficulty"].get(diff, {})
        if not m:
            continue
        R = f"{m['R']:.2f}" if m.get("R") is not None else "  —  "
        U = f"{m['U']:.2f}" if m.get("U") is not None else "  —  "
        V = f"{m['V']:.2f}" if m.get("V") is not None else "  —  "
        print(f"  {diff:<15} {m['n']:>3}  {R:>6}  {U:>6}  {V:>6}")
    tk = s["token_totals"]
    print(f"\n  Total tokens — prompt: {tk['prompt']:,}  output: {tk['output']:,}  "
          f"thinking: {tk['thinking']:,}  cached: {tk['cached']:,}")


# ══════════════════════════════════════════════════════════════════════════════
# Main runner
# ══════════════════════════════════════════════════════════════════════════════

async def run() -> None:
    test_cases = load_test_set()
    data       = load_results()
    done_ids   = {r["id"] for r in data["results"]}

    if done_ids:
        print(f"[resume] {len(done_ids)}/{len(test_cases)} already completed\n")

    gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY_CREDIT"])
    agent  = Agent()

    async with agent.connect() as (mcp_session, system_instruction):

        for i, tc in enumerate(test_cases):
            if tc["id"] in done_ids:
                print(f"  [{tc['id']}] skip")
                continue

            is_oos = tc["tool"] == "out_of_scope"
            tag    = "OOS" if is_oos else tc["tool"]
            print(f"\n[{i+1:02d}/{len(test_cases)}] {tc['id']} | {tag} | dim={tc['t_eval']} | {tc['difficulty']}")
            print(f"  Q: {tc['question'][:90]}")

            # Fresh Gemini session for each question (independent tests)
            chat_session = agent.new_session(mcp_session, system_instruction)

            # ── Agent call (infinite retry on 503, abort on other errors) ──
            response_text, tool_calls, usage = None, None, None
            retry_wait = 2
            while True:
                chat_session = agent.new_session(mcp_session, system_instruction)
                try:
                    response_text, tool_calls, usage = await agent.send(
                        chat_session, tc["question"]
                    )
                    break
                except Exception as e:
                    err_str = str(e)
                    is_503 = (
                        "503" in err_str
                        or "unavailable" in err_str.lower()
                        or "service unavailable" in err_str.lower()
                        or getattr(e, "code", None) == 503
                        or getattr(getattr(e, "response", None), "status_code", None) == 503
                    )
                    if is_503:
                        print(f"  [503 – retry in {retry_wait}s]")
                        await asyncio.sleep(retry_wait)
                        retry_wait = min(retry_wait * 2, 300)  # backoff up to 5 min
                        continue
                    # Unrecoverable error: save and move on
                    print(f"  [ERROR agent.send: {e.__class__.__name__}: {err_str[:120]}]")
                    data["results"].append({
                        "id": tc["id"], "tool": tc["tool"], "t_eval": tc["t_eval"],
                        "difficulty": tc["difficulty"], "question": tc["question"],
                        "error": err_str,
                        "scores": {d: {"score": 0.0, "detail": "agent error"} for d in "RUV"},
                    })
                    save_results(data)
                    break
            if response_text is None:
                time.sleep(API_DELAY)
                continue

            print(f"  tools called: {[t['tool'] for t in tool_calls] or '(none)'}")
            preview = response_text[:110].replace("\n", " ")
            print(f"  answer: {preview}{'…' if len(response_text) > 110 else ''}")

            # ── Dimension R ────────────────────────────────────────────────────
            r_score = score_R(tc["expected_tool"], tool_calls)
            print(f"  R={r_score['score']:.2f}  {r_score['detail']}")

            # ── Dimension U ────────────────────────────────────────────────────
            u_score = score_U(tc.get("expected_args"), tool_calls, tc["expected_tool"])
            print(f"  U={u_score['score']:.2f}  {u_score['detail']}")

            # ── Dimension V ────────────────────────────────────────────────────
            v_score = score_V_programmatic(tc, response_text)
            if v_score is None:
                print(f"  V → LLM judge…", end=" ", flush=True)
                time.sleep(API_DELAY)
                v_score = score_V_judge(gemini, tc, response_text)
                raw = v_score.get("score_raw", "?")
                print(f"score={raw}/5")
            print(f"  V={v_score['score']:.2f}  [{v_score.get('method','?')}]  "
                  f"{str(v_score.get('note') or v_score.get('detail',''))[:80]}")

            data["results"].append({
                "id":             tc["id"],
                "tool":           tc["tool"],
                "t_eval":         tc["t_eval"],
                "difficulty":     tc["difficulty"],
                "question":       tc["question"],
                "expected_tool":  tc["expected_tool"],
                "expected_args":  tc.get("expected_args"),
                "ground_truth":   tc.get("ground_truth"),
                "actual_tools":   tool_calls,
                "response_text":  response_text,
                "scores":         {"R": r_score, "U": u_score, "V": v_score},
                "usage":          usage,
            })
            save_results(data)
            time.sleep(API_DELAY)

    # ── Summary ────────────────────────────────────────────────────────────────
    data["summary"]   = compute_summary(data["results"])
    data["completed"] = datetime.now().isoformat()
    save_results(data)
    print_summary(data["summary"])
    print(f"\nResults saved to: {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
