#!/usr/bin/env python3
"""
test_mcp_live.py
Battery test for the Safety-Agent MCP server via Gemini.

Phase 1 - Smoke tests: ogni tool deve rispondere senza errori.
Phase 2 - Tricky tests: logica aggregazione, filtri combinati, edge cases.

Output: PASS / FAIL per ogni test case.
"""

import os
import sys
import asyncio
import re
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextResourceContents
from pydantic import AnyUrl
from google import genai
from google.genai import types

# force UTF-8 output so arrows/symbols don't crash on cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SERVER_SCRIPT = str(ROOT / "mcp" / "server.py")

# ── Test case definition ──────────────────────────────────────────────────────

@dataclass
class TestCase:
    id: str
    phase: int
    query: str
    description: str
    check: Callable[[str], tuple[bool, str]] = field(default=lambda t: (True, ""))


def _has_number(text: str) -> tuple[bool, str]:
    if re.search(r"\d", text):
        return True, "contiene un numero"
    return False, "nessun numero nella risposta"


def _not_error(text: str) -> tuple[bool, str]:
    low = text.lower()
    for kw in ("errore", "error", "eccezione", "exception", "traceback", "failed"):
        if kw in low:
            return False, f"contiene '{kw}'"
    if len(text.strip()) < 10:
        return False, "risposta troppo corta"
    return True, "OK"


def _refuses(text: str) -> tuple[bool, str]:
    low = text.lower()
    for kw in ("non posso", "non e' pertinente", "non riguarda", "fuori ambito",
               "non sono in grado", "mi occupo solo", "non posso rispondere",
               "rifiuto", "non rientra", "non e' pertinente", "non e pertinente",
               "non mi occupo", "non sono specializzato"):
        if kw in low:
            return True, f"rifiuto rilevato: '{kw}'"
    return False, "non ha rifiutato la domanda off-topic"


def _mentions_not_found(text: str) -> tuple[bool, str]:
    low = text.lower()
    for kw in ("non trovato", "non esiste", "inesistente", "not found", "nessun evento",
               "non ho trovato", "non e' presente", "non e' stato trovato",
               "non e' disponibile", "non risulta"):
        if kw in low:
            return True, f"segnala assenza: '{kw}'"
    return False, "non segnala che l'evento non esiste"


def _mentions_confidence(text: str) -> tuple[bool, str]:
    low = text.lower()
    for kw in ("confidence", "confidenza", "%", "rilevaz"):
        if kw in low:
            return True, f"menziona confidence: '{kw}'"
    return False, "non menziona confidence/detections"


# ── Test cases ────────────────────────────────────────────────────────────────

PHASE_1 = [
    TestCase(
        id="P1-01", phase=1,
        query="Dammi tutti i dettagli dell'evento con ID 1.",
        description="get_event_by_id - evento reale",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P1-02", phase=1,
        query="Elenca gli ultimi 3 eventi di sicurezza.",
        description="list_events - default params",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P1-03", phase=1,
        query="Quanti eventi ci sono in totale nel database?",
        description="count_events - no filters",
        check=lambda t: _has_number(t),
    ),
    TestCase(
        id="P1-04", phase=1,
        query="Qual e' la telecamera che ha registrato piu' eventi in assoluto?",
        description="group_by_count(camera_name)",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P1-05", phase=1,
        query="Qual e' la severity media di tutti gli eventi nel database?",
        description="average_severity - no filters",
        check=lambda t: _has_number(t),
    ),
    TestCase(
        id="P1-06", phase=1,
        query="Mostrami quanti eventi di sicurezza ci sono stati ogni giorno (trend giornaliero).",
        description="events_per_day - full dataset",
        check=lambda t: _not_error(t),
    ),
]

PHASE_2 = [
    TestCase(
        id="P2-01", phase=2,
        query="Quanti eventi con severity 7 o superiore (critici) ci sono nel database?",
        description="count_events(min_severity=7) - range filter",
        check=lambda t: _has_number(t),
    ),
    TestCase(
        id="P2-02", phase=2,
        query="Mostrami gli ultimi 5 eventi che non sono ancora stati revisionati.",
        description="list_events(reviewed=False) - boolean filter",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P2-03", phase=2,
        query="Qual e' il tipo di violazione DPI piu' frequente in tutto il dataset?",
        description="group_by_count(event_type) - ranking",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P2-04", phase=2,
        query="Dimmi i dettagli completi dell'evento 1, incluse le rilevazioni CV con la loro confidence.",
        description="get_event_by_id fields=['*'] - detections",
        check=lambda t: _mentions_confidence(t),
    ),
    TestCase(
        id="P2-05", phase=2,
        query=(
            "Elenca per ogni telecamera quanti eventi ha registrato in totale, "
            "ordinati dal piu' al meno attivo."
        ),
        description="group_by_count - NON deve scaricare raw per contare",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P2-06", phase=2,
        query=(
            "Qual e' la severity media degli eventi registrati dalla telecamera "
            "piu' attiva del dataset?"
        ),
        description="two-step: group_by_count -> average_severity(camera_name=...)",
        check=lambda t: _has_number(t),
    ),
    TestCase(
        id="P2-07", phase=2,
        query="Quanti eventi critici (severity >= 7) ci sono stati per ogni tipo di violazione?",
        description="group_by_count(event_type, min_severity=7) - combined filters",
        check=lambda t: _not_error(t),
    ),
    TestCase(
        id="P2-08", phase=2,
        query="Mostrami l'evento con ID 9999999.",
        description="get_event_by_id - ID inesistente, deve segnalarlo",
        check=lambda t: _mentions_not_found(t),
    ),
    TestCase(
        id="P2-09", phase=2,
        query="Qual e' la capitale della Francia?",
        description="OFF-TOPIC - deve rifiutare educatamente",
        check=lambda t: _refuses(t),
    ),
    TestCase(
        id="P2-10", phase=2,
        query=(
            "Qual e' il giorno con il maggior numero di eventi di sicurezza "
            "in tutto il dataset?"
        ),
        description="events_per_day -> reasoning per trovare il picco",
        check=lambda t: _not_error(t),
    ),
]

ALL_TESTS = PHASE_1 + PHASE_2

# ── Runner ────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# seconds to wait between API calls — free tier: 5 RPM
INTER_TEST_SLEEP = 15


def _color(ok: bool, text: str) -> str:
    return f"{GREEN}{text}{RESET}" if ok else f"{RED}{text}{RESET}"


def _is_daily_quota(msg: str) -> bool:
    return "PerDay" in msg or ("429" in msg and "RESOURCE_EXHAUSTED" in msg)

def _is_transient(msg: str) -> bool:
    return "503" in msg or "UNAVAILABLE" in msg or ("429" in msg and "PerMinute" in msg)


async def _call_with_retry(
    gemini: genai.Client,
    system_instruction: str,
    session,
    query: str,
    keys: list[str],
    current_key_idx: list[int],   # mutable box so caller sees the updated index
) -> str:
    """Send message; on daily-quota 429 rotate to next key; on transient 429/503 back off."""
    MAX_KEY_ROTATIONS = len(keys)
    MAX_TRANSIENT_RETRIES = 3

    transient_attempts = 0
    key_rotations = 0

    while True:
        key = keys[current_key_idx[0]]
        client = genai.Client(api_key=key)
        chat = client.aio.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                tools=[session],               # type: ignore[call-arg]
                system_instruction=system_instruction,  # type: ignore[call-arg]
            ),
        )
        try:
            response = await chat.send_message(query)
            return response.text or ""
        except Exception as e:
            msg = str(e)
            if _is_daily_quota(msg):
                key_rotations += 1
                if key_rotations > MAX_KEY_ROTATIONS:
                    raise RuntimeError("Tutte le API key hanno la quota giornaliera esaurita.") from e
                next_idx = (current_key_idx[0] + 1) % len(keys)
                print(f"    [quota giornaliera su key[{current_key_idx[0]}] - passo a key[{next_idx}]]")
                current_key_idx[0] = next_idx
                await asyncio.sleep(5)
            elif _is_transient(msg):
                transient_attempts += 1
                m = re.search(r"retryDelay.*?(\d+)s", msg)
                wait = int(m.group(1)) + 5 if m else (20 * transient_attempts)
                if transient_attempts > MAX_TRANSIENT_RETRIES:
                    raise
                print(f"    [transient {type(e).__name__} - attendo {wait}s, tentativo {transient_attempts}/{MAX_TRANSIENT_RETRIES}]")
                await asyncio.sleep(wait)
            else:
                raise


async def run_tests(phases: list[int] | None = None):
    # collect all available keys, primary first
    key_names = ["GEMINI_API_KEY", "GEMINI_API_KEY_FALLBACK1", "GEMINI_API_KEY_FALLBACK2"]
    keys = [os.environ[k] for k in key_names if os.environ.get(k)]
    if not keys:
        print(f"{RED}ERRORE: nessuna GEMINI_API_KEY trovata in .env.local{RESET}")
        sys.exit(1)
    print(f"  Chiavi disponibili: {len(keys)} ({', '.join(key_names[:len(keys)])})\n")

    current_key_idx = [0]   # mutable so _call_with_retry can rotate it
    gemini = genai.Client(api_key=keys[0])  # kept for compatibility, not used in calls
    server_params = StdioServerParameters(command="python", args=[SERVER_SCRIPT])

    async with stdio_client(server_params) as (read, write):  # type: ignore[attr-defined]
        async with ClientSession(read, write) as session:
            await session.initialize()

            resource = await session.read_resource(AnyUrl("db://schema"))
            content = resource.contents[0]
            schema_text = content.text if isinstance(content, TextResourceContents) else ""

            # load rules from client.py via importlib to avoid mcp package name clash
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("safety_client", ROOT / "mcp" / "client.py")
            _mod = _ilu.module_from_spec(_spec)       # type: ignore[arg-type]
            _spec.loader.exec_module(_mod)             # type: ignore[union-attr]
            FIELDS_RULES = _mod.FIELDS_RULES
            GENERAL_RULES = _mod.GENERAL_RULES

            system_instruction = "\n".join([
                "Sei un assistente specializzato nell'analisi di eventi di sicurezza sul lavoro rilevati da telecamere CCTV.",
                "Regola di base: Per ogni richiesta, rispondi in modo naturale e discorsivo come se fossi un essere umano.\n",
                schema_text,
                FIELDS_RULES,
                GENERAL_RULES,
            ])

            tests_to_run = [tc for tc in ALL_TESTS if phases is None or tc.phase in phases]
            results: list[tuple[TestCase, bool, str, str]] = []
            current_phase = 0

            for i, tc in enumerate(tests_to_run):
                if tc.phase != current_phase:
                    current_phase = tc.phase
                    label = (
                        "SMOKE TESTS - ogni tool deve rispondere correttamente"
                        if tc.phase == 1 else
                        "TRICKY TESTS - logica, filtri combinati, edge cases"
                    )
                    print(f"\n{BOLD}{'='*70}{RESET}")
                    print(f"{BOLD}{CYAN}  PHASE {tc.phase}: {label}{RESET}")
                    print(f"{BOLD}{'='*70}{RESET}\n")

                print(f"{BOLD}[{tc.id}]{RESET} {tc.description}")
                print(f"  Query: {CYAN}{tc.query}{RESET}")

                try:
                    text = await _call_with_retry(
                        gemini, system_instruction, session, tc.query,
                        keys, current_key_idx,
                    )
                    passed, note = tc.check(text)

                    status = "PASS" if passed else "FAIL"
                    print(f"  Status: {_color(passed, status)} - {note}")
                    preview = text.replace("\n", " ").strip()[:220]
                    print(f"  Risposta: {preview}{'...' if len(text) > 220 else ''}\n")
                    results.append((tc, passed, note, text))

                except Exception as e:
                    print(f"  Status: {_color(False, 'FAIL')} - eccezione: {type(e).__name__}: {e}\n")
                    results.append((tc, False, str(e), ""))

                # sleep between tests to respect per-minute rate limits
                if i < len(tests_to_run) - 1:
                    await asyncio.sleep(INTER_TEST_SLEEP)

            # ── Summary ───────────────────────────────────────────────────────
            print(f"\n{BOLD}{'='*70}{RESET}")
            print(f"{BOLD}  RIEPILOGO FINALE{RESET}")
            print(f"{BOLD}{'='*70}{RESET}\n")

            passed_count = sum(1 for _, p, _, _ in results if p)
            failed = [(tc, note) for tc, p, note, _ in results if not p]

            print(f"  {GREEN}PASS{RESET}: {passed_count}/{len(results)}")
            if failed:
                print(f"  {RED}FAIL{RESET}: {len(failed)}")
                for tc, note in failed:
                    print(f"    * [{tc.id}] {tc.description}")
                    print(f"           motivo: {note}")
            else:
                print(f"  {GREEN}Tutti i test superati!{RESET}")
            print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, nargs="*", help="Fasi da eseguire (es. 1 2). Default: tutte")
    args = parser.parse_args()
    asyncio.run(run_tests(phases=args.phase))
