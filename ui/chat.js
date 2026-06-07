const API_URL = "http://127.0.0.1:8000/chat";
const API_KEY = "SAMdk7AqFmdsJRklcJHJSQ5xa3bjTEP6AfH";

const messagesEl = document.getElementById("messages");
const inputEl    = document.getElementById("userInput");
const sendBtn    = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");

function appendMessage(role, text) {
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();

  const row    = document.createElement("div");
  row.className = `message-row ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  row.appendChild(bubble);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function appendChart(base64png) {
  const row = document.createElement("div");
  row.className = "message-row agent";
  const img = document.createElement("img");
  img.src = `data:image/png;base64,${base64png}`;
  img.style.maxWidth = "100%";
  img.style.borderRadius = "8px";
  row.appendChild(img);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showTyping() {
  const row    = document.createElement("div");
  row.className = "message-row agent typing";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("span");
    dot.className = "dot";
    bubble.appendChild(dot);
  }
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return row;
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  appendMessage("user", text);
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendBtn.disabled = true;

  const typingRow = showTyping();

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
      },
      body: JSON.stringify({ message: text }),
    });

    typingRow.remove();

    if (!res.ok) {
      appendMessage("agent", `Errore ${res.status}: impossibile ottenere una risposta.`);
      return;
    }

    const data = await res.json();
    appendMessage("agent", data.response);
    if (data.chart_image) {
      appendChart(data.chart_image);
    }
  } catch {
    typingRow.remove();
    appendMessage("agent", "Errore di rete: assicurati che il server sia avviato.");
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// Auto-resize textarea
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});

// Enter to send, Shift+Enter for newline
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

function buildWelcome() {
  const div = document.createElement("div");
  div.className = "welcome";
  const h2 = document.createElement("h2");
  h2.textContent = "Ciao, come posso aiutarti?";
  const p = document.createElement("p");
  p.textContent = "Chiedimi informazioni sugli eventi di sicurezza registrati dalle telecamere.";
  div.appendChild(h2);
  div.appendChild(p);
  return div;
}

newChatBtn.addEventListener("click", () => {
  messagesEl.replaceChildren(buildWelcome());
  inputEl.focus();
});
