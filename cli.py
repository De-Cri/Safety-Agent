import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.core import Agent


async def main():
    agent = Agent()
    async with agent.start() as chat_session:
        print("Safety Agent ready. Type 'exit' to quit.\n")
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() == "exit":
                break
            response = await chat_session.send_message(user_input)
            print(f"\nGemini: {response.text}\n")
            u = getattr(response, "usage_metadata", None)
            if u:
                print(f"[tokens] prompt={u.prompt_token_count} output={u.candidates_token_count} total={u.total_token_count}\n")


if __name__ == "__main__":
    asyncio.run(main())
