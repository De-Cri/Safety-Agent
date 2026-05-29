import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai
from google.genai import types

load_dotenv(Path(__file__).parent.parent / ".env.local")

SERVER_SCRIPT = str(Path(__file__).parent / "server.py")


async def chat():
    gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    server_params = StdioServerParameters(command="python", args=[SERVER_SCRIPT])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            chat_session = gemini.aio.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    tools=[session],
                    system_instruction=(
                        "Sei un assistente specializzato esclusivamente nell'analisi di eventi di sicurezza sul lavoro. "
                        "Rispondi solo a domande relative agli eventi nel database (query, filtri, statistiche, severity, ecc.). "
                        "Se l'utente lo richiede puoi fare delle operazioni matematiche sui dati ottenuti dagli eventi, dopo aver cercato se un tool fa già o meno quell'operazione, in caso di esito negativo, se è una piccola operazione falla tu, manda in output il risultato nel formato 'ecco la [nome operazione] è [numero]' senza nessun'altra informazione aggiuntiva riguardo all'operazione svolta"
                        "Se fai un operazione matematica che non è coperta da un tool dell'mcp, comunica all'utente che l'operazione la stai svolgendo tu e non esiste un tool interno per farla a cui ti appoggi"
                        "Se l'utente chiede qualcosa di non pertinente, rifiuta educatamente e ricordagli di cosa ti occupi."
                    ),
                ),
            )

            print("Safety Agent pronto. Scrivi 'exit' per uscire.\n")

            while True:
                user_input = input("Tu: ").strip()
                if user_input.lower() == "exit":
                    break

                response = await chat_session.send_message(user_input)
                print(f"\nGemini: {response.text}\n")


if __name__ == "__main__":
    asyncio.run(chat())
