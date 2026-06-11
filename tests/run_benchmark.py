#!/usr/bin/env python3
"""
run_benchmark.py
Testa 4 query con Gemini usando GEMINI_API_KEY_FALLBACK.
Per ogni query: payload FULL (nessun filtro) + payload LEAN (filtro server).
Salva risultati in benchmark_results.json dopo ogni chiamata (resume-safe).
5s tra ogni chiamata API.
"""

import os, sys, json, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

from google import genai
from google.genai import types

import importlib.util
spec = importlib.util.spec_from_file_location("server", ROOT / "mcp/server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

# ── Test cases ────────────────────────────────────────────────────────────────
# fields_lean: campi che il LLM sceglierebbe in base al system prompt
TEST_CASES = [
    {
        "id":         "q1",
        "query":      "Elenca le ultime 10 violazioni con camera e severity",
        "fetch_full": lambda: srv.get_events_limited(10, fields=["*"]),
        "fetch_lean": lambda: srv.get_events_limited(10, fields=["event_id","event_datetime","camera_name","severity"]),
        "fields_lean": ["event_id","event_datetime","camera_name","severity"],
    },
    {
        "id":         "q2",
        "query":      "Fammi una panoramica delle ultime 20 violazioni",
        "fetch_full": lambda: srv.get_events_limited(20, fields=["*"]),
        # Regola 5: panoramica → 5 campi fissi, NO reviewed (causa listing mode)
        "fetch_lean": lambda: srv.get_events_limited(20, fields=["event_id","event_datetime","camera_name","event_type","severity"]),
        "fields_lean": ["event_id","event_datetime","camera_name","event_type","severity"],
    },
    {
        "id":         "q3",
        "query":      "Quali telecamere compaiono di piu' tra le ultime 30 violazioni?",
        "fetch_full": lambda: srv.get_events_limited(30, fields=["*"]),
        # Regola 4: conteggio/ranking → event_id obbligatorio + campo target
        "fetch_lean": lambda: srv.get_events_limited(30, fields=["event_id","camera_name"]),
        "fields_lean": ["event_id","camera_name"],
    },
    {
        "id":         "q4",
        "query":      "Riassumi gli ultimi 15 eventi di sicurezza per tipologia",
        "fetch_full": lambda: srv.get_events_limited(15, fields=["*"]),
        "fetch_lean": lambda: srv.get_events_limited(15, fields=["event_type","severity"]),
        "fields_lean": ["event_type","severity"],
    },
]

SYSTEM = (
    "Sei un assistente specializzato in sicurezza sul lavoro. "
    "Rispondi in italiano basandoti esclusivamente sui dati forniti."
)

CACHE = ROOT / "benchmark_results.json"
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}

def save_cache(data):
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def call_gemini(client, query, payload_str):
    prompt = f'L\'utente chiede: "{query}"\n\nDati dal database:\n{payload_str}\n\nRispondi in italiano.'
    for attempt, model in enumerate(MODELS * 3, start=1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=SYSTEM),  # type: ignore[call-arg]
            )
            u = resp.usage_metadata
            return {
                "text":         resp.text,
                "input_tok":    u.prompt_token_count,
                "output_tok":   u.candidates_token_count,
                "total_tok":    u.total_token_count,
                "payload_bytes": len(payload_str.encode()),
                "model":        model,
            }
        except Exception as e:
            wait = 20 * ((attempt - 1) // len(MODELS) + 1)
            print(f"    [tentativo {attempt} ({model}) fallito: {e.__class__.__name__} - riprovo tra {wait}s]")
            time.sleep(wait)
    raise RuntimeError("Gemini non risponde.")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("GEMINI_API_KEY_FALLBACK") or os.environ["GEMINI_API_KEY"]
    client  = genai.Client(api_key=api_key)
    results = load_cache()

    if results:
        done = sum(1 for tc in TEST_CASES for v in ("full","lean") if f"{tc['id']}_{v}" in results)
        print(f"[ripreso da cache: {done}/8 chiamate gia' completate]")

    for tc in TEST_CASES:
        print(f"\n--- {tc['id'].upper()}: {tc['query']}")

        # ── FULL ──────────────────────────────────────────────────────────────
        key_full = f"{tc['id']}_full"
        if key_full not in results:
            data = tc["fetch_full"]()
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            print(f"  FULL  {len(payload.encode()):,} bytes")
            r = call_gemini(client, tc["query"], payload)
            results[key_full] = {**r, "query": tc["query"], "variant": "full", "fields": ["*"]}
            save_cache(results)
            print(f"    in:{r['input_tok']} out:{r['output_tok']} [{r['model']}]")
            print("  [5s]"); time.sleep(5)
        else:
            print(f"  FULL  [cache]  in:{results[key_full]['input_tok']}")

        # ── LEAN ──────────────────────────────────────────────────────────────
        key_lean = f"{tc['id']}_lean"
        if key_lean not in results:
            data = tc["fetch_lean"]()
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            print(f"  LEAN  {len(payload.encode()):,} bytes  fields={tc['fields_lean']}")
            r = call_gemini(client, tc["query"], payload)
            results[key_lean] = {**r, "query": tc["query"], "variant": "lean", "fields": tc["fields_lean"]}
            save_cache(results)
            print(f"    in:{r['input_tok']} out:{r['output_tok']} [{r['model']}]")
            print("  [5s]"); time.sleep(5)
        else:
            print(f"  LEAN  [cache]  in:{results[key_lean]['input_tok']}")

    print("\nFatto. Risultati in benchmark_results.json")
    for tc in TEST_CASES:
        f = results[f"{tc['id']}_full"]
        l = results[f"{tc['id']}_lean"]
        saved = f["input_tok"] - l["input_tok"]
        pct   = saved / f["input_tok"] * 100 if f["input_tok"] else 0
        print(f"  {tc['id']}: -{saved} input tok ({pct:.0f}%)")

if __name__ == "__main__":
    main()
