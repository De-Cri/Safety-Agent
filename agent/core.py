import os
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).parent.parent  # agent/ → Safety-Agent/
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextResourceContents
from pydantic import AnyUrl
from google import genai
from google.genai import types
from agent import prompts

load_dotenv(ROOT / ".env.local")

SERVER_SCRIPT = str(ROOT / "src" / "mcp-server.py")
# Fields that FIELDS_RULES is aware of. If the DB adds new fields, the startup check warns.
# Keep this set in sync with FIELDS_RULES below whenever the schema changes.
KNOWN_FIELDS = {"event_id", "event_datetime", "camera_name", "event_type", "severity", "reviewed", "detections"}

def _build_system_instruction(schema_text: str) -> str:
    return "\n".join([
        "Sei un assistente specializzato nell'analisi di eventi di sicurezza sul lavoro rilevati da telecamere CCTV.",
        "Regola di base: Per ogni richiesta, rispondi in modo naturale e discorsivo come se fossi un essere umano.\n",
        schema_text,
        prompts.FIELDS_RULES,
        prompts.GENERAL_RULES,
    ])


class Agent:
    def __init__(self) -> None:
        self.gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY_FALLBACK1"])
        self.server_params = StdioServerParameters(command="python", args=[SERVER_SCRIPT])

    @asynccontextmanager
    async def connect(self):
        """Keeps the MCP server alive and yields (mcp_session, system_instruction).
        Use this in API lifespan — one process, shared across requests."""
        _check_schema_drift()
        async with stdio_client(self.server_params) as (read, write):  # type: ignore[attr-defined]
            async with ClientSession(read, write) as session:
                await session.initialize()
                resource = await session.read_resource(AnyUrl("db://schema"))
                content = resource.contents[0]
                schema_text = content.text if isinstance(content, TextResourceContents) else ""
                yield session, _build_system_instruction(schema_text)

    def new_session(self, mcp_session, system_instruction: str):
        """Creates a fresh Gemini chat session. Call this at startup and on reset."""
        return self.gemini.aio.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                tools=[mcp_session],             # type: ignore[call-arg]
                system_instruction=system_instruction,  # type: ignore[call-arg]
            ),
        )

    async def send(self, chat_session, user_input: str) -> tuple[str, list[dict], dict]:
        """Send a message to an existing chat session. Only the last 2 user turns are kept in context."""
        _trim_history(chat_session, keep_turns=2)
        history_before = len(chat_session.get_history() or [])
        response = await chat_session.send_message(user_input)

        tool_calls = []
        new_history = (chat_session.get_history() or [])[history_before:]
        for content in new_history:
            for part in (content.parts or []):
                fc = getattr(part, "function_call", None)
                if fc:
                    tool_calls.append({"tool": fc.name, "args": dict(fc.args or {})})

        # Raw tool payloads are huge and already processed — drop them from history
        # so they don't inflate the next request's prompt tokens.
        _strip_tool_responses(chat_session, history_before)

        return response.text or "", tool_calls, _extract_usage(response)

    @asynccontextmanager
    async def start(self):
        """CLI: keeps MCP alive and yields a stateful chat_session (history preserved)."""
        async with self.connect() as (session, system_instruction):
            chat_session = self.gemini.aio.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    tools=[session],             # type: ignore[call-arg]
                    system_instruction=system_instruction,  # type: ignore[call-arg]
                ),
            )
            yield chat_session


def _extract_usage(response) -> dict:
    u = getattr(response, "usage_metadata", None)
    if not u:
        return {}
    return {
        "prompt_tokens":   getattr(u, "prompt_token_count",     0) or 0,
        "output_tokens":   getattr(u, "candidates_token_count", 0) or 0,
        "total_tokens":    getattr(u, "total_token_count",       0) or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count",    0) or 0,
        # Prefisso riconosciuto dal caching implicito di Gemini: già contato
        # in prompt_tokens, ma fatturato a -75%. Se resta a 0, niente cache.
        "cached_tokens":   getattr(u, "cached_content_token_count", 0) or 0,
    }


def _strip_tool_responses(chat_session, from_index: int) -> None:
    """Replace function_response payloads added in this turn with an empty dict.
    The model already used the data; keeping the raw JSON only inflates future prompts."""
    for content in (chat_session._curated_history or [])[from_index:]:
        for part in (content.parts or []):
            fr = getattr(part, "function_response", None)
            if fr and hasattr(fr, "response"):
                fr.response = {}


def _trim_history(chat_session, keep_turns: int) -> None:
    history = chat_session._curated_history
    # Gemini marks tool responses as role="user" too — filter to only real text turns
    real_user_indices = [
        i for i, c in enumerate(history)
        if getattr(c, "role", None) == "user"
        and any(getattr(p, "text", None) for p in (c.parts or []))
    ]
    if len(real_user_indices) > keep_turns:
        chat_session._curated_history = history[real_user_indices[-keep_turns]:]


#Keeping the agent always updated on any schema drift, it has alywas the current state of the schema
def _check_schema_drift() -> None:
    from db.queries import get_event_fields
    actual = get_event_fields()
    added   = actual - KNOWN_FIELDS
    removed = KNOWN_FIELDS - actual
    if added:
        print(f"\n[WARNING] New DB fields not covered by the rules: {added}")
        print("          → Update KNOWN_FIELDS and FIELDS_RULES in client.py\n")
    if removed:
        print(f"\n[WARNING] Fields in the rules no longer present in the DB: {removed}")
        print("          → Update KNOWN_FIELDS and FIELDS_RULES in client.py\n")