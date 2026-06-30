import json
import time
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

from google import genai
from google.genai import types
from src.core import Agent

TEST_SET_PATH = Path(__file__).parent / "t_eval_test_set.json"
RESULTS_PATH  = Path(__file__).parent / "t_eval_results.json"
API_DELAY     = 5


def _match_value(expected, actual) -> bool:
    if isinstance(expected, bool):
        return actual is not None and bool(actual) == expected
    if isinstance(expected, int):
        try: return int(actual) == expected
        except: return False
    if isinstance(expected, float):
        try: return abs(float(actual) - expected) < 0.01
        except: return False
    if isinstance(expected, str):
        if "T" in expected:  # ISO date — compare only YYYY-MM-DD
            return str(expected)[:10] == str(actual)[:10]
        return str(actual) == expected
    return actual == expected


def score_R(expected_tools: list[str], actual_tool_calls: list[dict]) -> dict:
    actual_names = [t["tool"] for t in actual_tool_calls]

    if expected_tools == ["REFUSAL"]:
        if not actual_names:
            return {"score": 1.0, "detail": "correct refusal — no tool called"}
        return {"score": 0.0, "detail": f"expected refusal but agent called: {actual_names}"}

    if not actual_names:
        return {"score": 0.0, "detail": f"no tool called — expected: {expected_tools}"}

    if set(expected_tools) == set(actual_names):
        return {"score": 1.0, "detail": "exact match — all expected tools called"}

    actual_set   = set(actual_names)
    expected_set = set(expected_tools)
    matched = sum(1 for t in expected_tools if t in actual_set)
    score   = round(matched / max(len(expected_tools), len(actual_names)), 2)

    missing = [t for t in expected_tools if t not in actual_set]
    extra   = [t for t in actual_names if t not in expected_set]

    detail_parts = [f"{matched}/{len(expected_tools)} tools correct"]
    if missing:
        detail_parts.append(f"missing: {missing}")
    if extra:
        detail_parts.append(f"extra: {extra}")

    return {"score": score, "detail": " | ".join(detail_parts)}


def score_U(expected_args: dict, actual_tool_calls: list[dict]) -> dict:
    actual_args = actual_tool_calls[0]["args"] if actual_tool_calls else None

    if expected_args is None or actual_args is None:
        return {"score": None, "detail": "cannot evaluate — args unavailable"}

    if expected_args == {} and actual_args == {}:
        return {"score": 1.0, "detail": "no args expected and none passed"}

    if expected_args == {} or actual_args == {}:
        return {"score": 0.0, "detail": f"expected {expected_args} but got {actual_args}"}

    matched = sum(1 for k, v in expected_args.items() if _match_value(v, actual_args.get(k)))
    missing = [f"{k}: expected={v!r} got={actual_args.get(k)!r}"
               for k, v in expected_args.items() if not _match_value(v, actual_args.get(k))]
    extra   = [k for k in actual_args if k not in expected_args]
    score   = round(matched / max(len(expected_args), len(actual_args)), 2)

    detail_parts = [f"{matched}/{len(expected_args)} args correct"]
    if missing:
        detail_parts.append(f"wrong: {missing}")
    if extra:
        detail_parts.append(f"extra args: {extra}")

    return {"score": score, "detail": " | ".join(detail_parts)}

def score_V_programmatic(ground_truth_type: str, ground_truth, tool_results: list[dict]) -> dict | None:

    if not tool_results:
        return None

    result = tool_results[0]["result"]

    if ground_truth_type == "exact_integer":
        actual = result if isinstance(result, int) else None
        if actual is None:
            return None
        if actual == ground_truth:
            return {"score": 1.0, "detail": f"exact match: {actual}"}
        return {"score": 0.0, "detail": f"expected {ground_truth}, got {actual}"}

    if ground_truth_type == "exact_float":
        try:
            actual = float(result)
        except (TypeError, ValueError):
            return None
        if abs(actual - float(ground_truth)) < 0.05:
            return {"score": 1.0, "detail": f"match within tolerance: {actual}"}
        return {"score": 0.0, "detail": f"expected {ground_truth}, got {actual}"}

    if ground_truth_type in ("top_value", "peak_value"):
        if not isinstance(ground_truth, dict) or not isinstance(result, dict):
            return None
        matched = sum(1 for k, v in ground_truth.items() if _match_value(v, result.get(k)))
        score = round(matched / len(ground_truth), 2)
        wrong = [f"{k}: expected={v!r} got={result.get(k)!r}"
                 for k, v in ground_truth.items() if not _match_value(v, result.get(k))]
        detail = f"{matched}/{len(ground_truth)} fields correct"
        if wrong:
            detail += " | wrong: " + ", ".join(wrong)
        return {"score": score, "detail": detail}

    if ground_truth_type == "summary_dict":
        if not isinstance(ground_truth, dict) or not isinstance(result, dict):
            return None
        matched = sum(1 for k, v in ground_truth.items() if _match_value(v, result.get(k)))
        score = round(matched / len(ground_truth), 2)
        wrong = [f"{k}: expected={v!r} got={result.get(k)!r}"
                 for k, v in ground_truth.items() if not _match_value(v, result.get(k))]
        detail = f"{matched}/{len(ground_truth)} fields correct"
        if wrong:
            detail += " | wrong: " + ", ".join(wrong)
        return {"score": score, "detail": detail}

    # ranked_list, exact_record, refusal, not_found → judge
    return None


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


def score_V_judge(question: str, ground_truth, response_text: str, gemini_client) -> dict:
    """LLM-as-judge for cases that programmatic evaluation cannot handle."""
    gt_str = json.dumps(ground_truth, ensure_ascii=False) if ground_truth is not None else "not specified"

    prompt = (
        f'Question asked to the agent:\n"{question}"\n\n'
        f"Expected ground truth:\n{gt_str}\n\n"
        f"Agent response:\n{response_text}\n\n"
        "Rate the agent response on a 1-5 scale:\n"
        "  score (1-5): overall quality\n"
        "  correctness (1-5): factual correctness vs ground truth\n"
        "  completeness (1-5): does it fully answer the question?\n"
        "  note: brief motivation (max 2 lines)\n"
    )

    for attempt in range(1, 4):
        try:
            resp = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an impartial AI evaluator. Reply only with valid JSON.",
                    response_mime_type="application/json",
                    response_schema=_JUDGE_SCHEMA,
                ),
            )
            parsed = json.loads(resp.text)
            return {
                "score":       round(parsed["score"] / 5.0, 2),
                "score_raw":    parsed["score"],
                "correctness":  parsed["correctness"],
                "completeness": parsed["completeness"],
                "note":         parsed.get("note", ""),
                "method":      "llm_judge",
            }
        except Exception as e:
            time.sleep(attempt * 2)

    return {"score": None, "method": "llm_judge", "note": "judge failed after 3 attempts"}


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_test_set() -> list[dict]:
    return json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))["test_cases"]

def load_results() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {"started": datetime.now().isoformat(), "results": []}

def save_results(data: dict) -> None:
    RESULTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(s: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  T-EVAL SUMMARY")
    print(f"{'='*60}")
    print(f"  Total: {s['total']}  in-scope: {s['in_scope']}  out-of-scope: {s['out_of_scope']}")
    print(f"  R  tool selection : {s['R_accuracy']}")
    print(f"  U  param accuracy : {s['U_accuracy']}")
    print(f"  V  answer quality : {s['V_score']}")
    print(f"  Refusal rate      : {s['refusal_rate']}")
    print(f"\n  {'Tool':<40} {'n':>3}  {'R':>6}  {'U':>6}  {'V':>6}")
    print(f"  {'-'*60}")
    for tool, m in sorted(s["by_tool"].items()):
        R = f"{m['R']:.2f}" if m["R"] is not None else "  —  "
        U = f"{m['U']:.2f}" if m["U"] is not None else "  —  "
        V = f"{m['V']:.2f}" if m["V"] is not None else "  —  "
        print(f"  {tool:<40} {m['n']:>3}  {R:>6}  {U:>6}  {V:>6}")
    print(f"\n  {'Difficulty':<12} {'n':>3}  {'R':>6}  {'U':>6}  {'V':>6}")
    for diff in ("easy", "medium", "hard"):
        m = s["by_difficulty"].get(diff)
        if not m:
            continue
        R = f"{m['R']:.2f}" if m["R"] is not None else "  —  "
        U = f"{m['U']:.2f}" if m["U"] is not None else "  —  "
        V = f"{m['V']:.2f}" if m["V"] is not None else "  —  "
        print(f"  {diff:<12} {m['n']:>3}  {R:>6}  {U:>6}  {V:>6}")
    tk = s["token_totals"]
    print(f"\n  Tokens — prompt: {tk['prompt']:,}  output: {tk['output']:,}  "
          f"thinking: {tk['thinking']:,}  cached: {tk['cached']:,}")


# ── Runner ────────────────────────────────────────────────────────────────────

async def run() -> None:
    test_cases = load_test_set()
    data       = load_results()
    done_ids   = {r["id"] for r in data["results"]}

    if done_ids:
        print(f"[resume] {len(done_ids)}/{len(test_cases)} already done\n")

    gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    agent  = Agent()

    async with agent.connect() as (mcp_session, system_instruction):
        for i, tc in enumerate(test_cases):
            if tc["id"] in done_ids:
                print(f"  [{tc['id']}] skip")
                continue

            print(f"\n[{i+1:02d}/{len(test_cases)}] {tc['id']} | {tc['tool']} | {tc['difficulty']}")
            print(f"  Q: {tc['question'][:90]}")

            # parse expected_tools: "count_events" or "a + b" or "REFUSAL"
            raw = tc["expected_tool"]
            expected_tools = ["REFUSAL"] if raw == "REFUSAL" else [t.strip() for t in raw.split("+")]

            # fresh session per test — independent evaluations
            chat = agent.new_session(mcp_session, system_instruction)

            try:
                response_text, tool_calls, usage = await agent.send(chat, tc["question"])
            except Exception as e:
                print(f"  [ERROR] {type(e).__name__}: {e}")
                data["results"].append({
                    "id": tc["id"], "tool": tc["tool"], "difficulty": tc["difficulty"],
                    "question": tc["question"], "error": str(e),
                    "scores": {d: {"score": 0.0, "detail": "agent error"} for d in "RUV"},
                })
                save_results(data)
                continue

            # extract tool return values from history
            tool_results = []
            for content in chat.get_history() or []:
                for part in (content.parts or []):
                    fr = getattr(part, "function_response", None)
                    if fr:
                        tool_results.append({"tool": fr.name, "result": dict(fr.response or {})})

            print(f"  tools: {[t['tool'] for t in tool_calls] or '(none)'}")
            print(f"  reply: {response_text[:100].replace(chr(10), ' ')}{'…' if len(response_text) > 100 else ''}")

            r_score = score_R(expected_tools, tool_calls)
            u_score = score_U(tc.get("expected_args") or {}, tool_calls)
            v_score = score_V_programmatic(tc["ground_truth_type"], tc.get("ground_truth"), tool_results)
            if v_score is None:
                print(f"  V → judge…", end=" ", flush=True)
                time.sleep(API_DELAY)
                v_score = score_V_judge(tc["question"], tc.get("ground_truth"), response_text, gemini)
                print(f"score={v_score.get('score_raw', '?')}/5")

            print(f"  R={r_score['score']}  U={u_score['score']}  V={v_score['score']}")

            data["results"].append({
                "id":            tc["id"],
                "tool":          tc["tool"],
                "difficulty":    tc["difficulty"],
                "question":      tc["question"],
                "expected_tool": tc["expected_tool"],
                "expected_args": tc.get("expected_args"),
                "ground_truth":  tc.get("ground_truth"),
                "actual_tools":  tool_calls,
                "tool_results":  tool_results,
                "response_text": response_text,
                "scores":        {"R": r_score, "U": u_score, "V": v_score},
                "usage":         usage,
            })
            save_results(data)
            time.sleep(API_DELAY)

    #data["summary"]   = compute_summary(data["results"])
    data["completed"] = datetime.now().isoformat()
    save_results(data)
    print_summary(data["summary"])


if __name__ == "__main__":
    asyncio.run(run())