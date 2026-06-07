#!/usr/bin/env python3
"""
test_token_budget.py
Misura token budget (BEFORE vs AFTER) e qualita' delle risposte tramite LLM-as-judge.
4 query x 2 varianti = 8 chiamate, poi 4 chiamate judge = 12 totali. 5s tra l'una e l'altra.
"""

import os, sys, json, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

from google import genai
from google.genai import types
from db.queries import get_events_limited

# ── Configurazione ────────────────────────────────────────────────────────────

SYSTEM = (
    "Sei un assistente specializzato in sicurezza sul lavoro. "
    "Rispondi in italiano basandoti esclusivamente sui dati forniti."
)

LEAN_FIELDS = {"event_id", "event_datetime", "camera_name", "event_type", "severity"}

TEST_CASES = [
    {"n": 10, "query": "Elenca le ultime 10 violazioni con camera e severity"},
    {"n": 20, "query": "Fammi una panoramica delle ultime 20 violazioni"},
    {"n": 30, "query": "Quali telecamere compaiono di piu' tra le ultime 30 violazioni?"},
    {"n": 15, "query": "Riassumi gli ultimi 15 eventi di sicurezza per tipologia"},
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def to_full(events: list[dict]) -> str:
    return json.dumps(events, ensure_ascii=False, indent=2)

def to_lean(events: list[dict]) -> str:
    slimmed = [{k: v for k, v in e.items() if k in LEAN_FIELDS} for e in events]
    return json.dumps(slimmed, ensure_ascii=False, separators=(",", ":"))

# Prova prima 2.5-flash (3 volte), poi fallback su 2.0-flash (3 volte)
_CALL_MODELS = ["gemini-2.5-flash"] * 3 + ["gemini-2.0-flash"] * 3

def call_gemini(client: genai.Client, query: str, payload: str) -> dict:
    prompt = (
        f'L\'utente chiede: "{query}"\n\n'
        f"Dati dal database:\n{payload}\n\n"
        "Rispondi in italiano."
    )
    for attempt, model in enumerate(_CALL_MODELS, start=1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=SYSTEM),  # type: ignore[call-arg]
            )
            u = resp.usage_metadata
            return {
                "input_tok":     u.prompt_token_count if u else 0,
                "output_tok":    u.candidates_token_count if u else 0,
                "total_tok":     u.total_token_count if u else 0,
                "payload_bytes": len(payload.encode()),
                "text":          resp.text,
                "model":         model,
            }
        except Exception as e:
            wait = 20 * attempt
            print(f"  [tentativo {attempt} ({model}) fallito: {e.__class__.__name__} - riprovo tra {wait}s]")
            time.sleep(wait)
    raise RuntimeError("Gemini non risponde dopo 6 tentativi.")


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "A": {
            "type": "object",
            "properties": {
                "completezza":  {"type": "integer"},
                "accuratezza":  {"type": "integer"},
                "espressivita": {"type": "integer"},
                "note":         {"type": "string"},
            },
            "required": ["completezza", "accuratezza", "espressivita", "note"],
        },
        "B": {
            "type": "object",
            "properties": {
                "completezza":  {"type": "integer"},
                "accuratezza":  {"type": "integer"},
                "espressivita": {"type": "integer"},
                "note":         {"type": "string"},
            },
            "required": ["completezza", "accuratezza", "espressivita", "note"],
        },
    },
    "required": ["A", "B"],
}

def judge(client: genai.Client, query: str, resp_before: str, resp_after: str) -> dict:
    """LLM-as-judge: confronta le due risposte su scala 1-5."""
    prompt = (
        f'Domanda: "{query}"\n\n'
        f"Risposta A (payload completo con tutti i campi):\n{resp_before}\n\n"
        f"Risposta B (payload ridotto, solo campi chiave):\n{resp_after}\n\n"
        "Valuta da 1 (pessimo) a 5 (ottimo):\n"
        "- completezza: risponde pienamente alla domanda?\n"
        "- accuratezza: informazioni corrette, nessuna invenzione?\n"
        "- espressivita: linguaggio chiaro, strutturato, utile?\n"
        "Aggiungi una nota concisa per ciascuna."
    )
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(  # type: ignore[call-arg]
                    system_instruction="Sei un valutatore imparziale di risposte AI. Rispondi solo con JSON.",
                    response_mime_type="application/json",
                    response_schema=JUDGE_SCHEMA,
                ),
            )
            if not resp.text:
                raise ValueError("risposta judge vuota")
            return json.loads(resp.text)
        except Exception as e:
            wait = 15 * attempt
            print(f"  [judge tentativo {attempt} fallito: {e.__class__.__name__} - riprovo tra {wait}s]")
            time.sleep(wait)
    return {}


# ── Main ──────────────────────────────────────────────────────────────────────

CACHE_FILE = ROOT / "benchmark_results.json"

def _save(rows: list, judges: list) -> None:
    CACHE_FILE.write_text(json.dumps({"rows": rows, "judges": judges}, ensure_ascii=False, indent=2), encoding="utf-8")

def _load() -> tuple[list, list]:
    if CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("rows", []), data.get("judges", [])
    return [], []

def main():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    rows, judges = _load()

    already_done = {(r["query"], r["variant"].strip()) for r in rows}
    if already_done:
        print(f"[ripreso da cache: {len(rows)} risultati gia' presenti]")

    # ── Fase 1: raccolta risposte ─────────────────────────────────────────────
    for i, tc in enumerate(TEST_CASES):
        print(f"\n{'-'*64}")
        print(f"Query {i+1}/{len(TEST_CASES)}: {tc['query']}")
        events = get_events_limited(tc["n"])

        full_payload = to_full(events)
        if (tc["query"], "BEFORE") not in already_done:
            print(f"  BEFORE  {len(full_payload.encode()):>7,} bytes")
            before = call_gemini(client, tc["query"], full_payload)
            before.update({"variant": "BEFORE", "query": tc["query"], "n": tc["n"]})
            rows.append(before)
            _save(rows, judges)
            print(f"          input:{before['input_tok']:>5}  output:{before['output_tok']:>5}  tot:{before['total_tok']:>6}  [{before['model']}]")
            print("  [5s]")
            time.sleep(5)
        else:
            print(f"  BEFORE  [gia' in cache, saltato]")

        lean_payload = to_lean(events)
        if (tc["query"], "AFTER") not in already_done:
            print(f"  AFTER   {len(lean_payload.encode()):>7,} bytes")
            after = call_gemini(client, tc["query"], lean_payload)
            after.update({"variant": "AFTER ", "query": tc["query"], "n": tc["n"]})
            rows.append(after)
            _save(rows, judges)
            print(f"          input:{after['input_tok']:>5}  output:{after['output_tok']:>5}  tot:{after['total_tok']:>6}  [{after['model']}]")
        else:
            print(f"  AFTER   [gia' in cache, saltato]")

        if i < len(TEST_CASES) - 1:
            print("  [5s]")
            time.sleep(5)

    # ── Fase 2: judge ─────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("FASE 2: LLM-as-judge (confronto qualita' risposte)")
    print(f"{'='*64}")

    befores = [r for r in rows if r["variant"] == "BEFORE"]
    afters  = [r for r in rows if r["variant"] == "AFTER "]

    already_judged = {j["query"] for j in judges}

    for i, (b, a) in enumerate(zip(befores, afters)):
        print(f"\n[{i+1}] {b['query']}")

        print(f"\n  --- RISPOSTA A (BEFORE) ---")
        for line in b["text"].strip().splitlines():
            print(f"  {line}")
        print(f"\n  --- RISPOSTA B (AFTER) ---")
        for line in a["text"].strip().splitlines():
            print(f"  {line}")

        if b["query"] in already_judged:
            scores = next(j for j in judges if j["query"] == b["query"])
            print("  [judge gia' in cache]")
        else:
            print("\n  [5s - chiamata judge]")
            time.sleep(5)
            scores = judge(client, b["query"], b["text"], a["text"])
            judges.append({"query": b["query"], **scores})
            _save(rows, judges)

        if scores:
            sa, sb = scores.get("A", {}), scores.get("B", {})
            print(f"\n  SCORE  {'Metrica':<15} {'A (BEFORE)':>12} {'B (AFTER)':>12}")
            print(f"  {'':5} {'-'*40}")
            for m in ["completezza", "accuratezza", "espressivita"]:
                print(f"  {'':5} {m:<15} {sa.get(m,'?'):>12} {sb.get(m,'?'):>12}")
            print(f"\n  Note A: {sa.get('note','')}")
            print(f"  Note B: {sb.get('note','')}")

        if i < len(befores) - 1:
            print("\n  [5s]")
            time.sleep(5)

    # ── Riepilogo token ───────────────────────────────────────────────────────
    print(f"\n{'='*82}")
    print("RIEPILOGO TOKEN BUDGET")
    print(f"{'='*82}")
    print(f"{'N':>4}  {'Query':<44}  {'Var':6}  {'Bytes':>8}  {'In':>6}  {'Out':>6}  {'Tot':>7}")
    print("-" * 82)
    for r in rows:
        print(
            f"{r['n']:>4}  {r['query'][:44]:<44}  {r['variant']:6}  "
            f"{r['payload_bytes']:>8,}  {r['input_tok']:>6}  {r['output_tok']:>6}  {r['total_tok']:>7}"
        )

    total_b = sum(r["input_tok"] for r in befores)
    total_a = sum(r["input_tok"] for r in afters)
    print(f"\n  Risparmio input tokens: {total_b - total_a:,} ({(total_b-total_a)/total_b*100:.1f}%)")

    # ── Riepilogo qualita' ────────────────────────────────────────────────────
    if judges:
        print(f"\n{'='*64}")
        print("RIEPILOGO QUALITA' (media score 1-5)")
        print(f"{'='*64}")
        metrics = ["completezza", "accuratezza", "espressivita"]
        for m in metrics:
            avg_a = sum(j["A"].get(m, 0) for j in judges) / len(judges)
            avg_b = sum(j["B"].get(m, 0) for j in judges) / len(judges)
            diff  = avg_b - avg_a
            arrow = "+" if diff >= 0 else ""
            print(f"  {m:<15}  A(BEFORE):{avg_a:.2f}  B(AFTER):{avg_b:.2f}  diff:{arrow}{diff:.2f}")


if __name__ == "__main__":
    main()
