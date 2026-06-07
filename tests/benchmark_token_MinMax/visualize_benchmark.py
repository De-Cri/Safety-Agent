#!/usr/bin/env python3
"""
visualize_benchmark.py
Mostra: (1) campione del payload "prima" (output inutile), (2) plot confronto token.
Risultati hardcoded dall'ultimo run di test_token_budget.py.
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

import matplotlib.pyplot as plt
import numpy as np
from db.queries import get_events_limited

# ── Risultati dall'ultimo run di test_token_budget.py ────────────────────────

LABELS       = ["10 eventi\n(elenca)", "20 eventi\n(panoramica)", "30 eventi\n(telecamere)", "15 eventi\n(riassunto)"]
BEFORE_INPUT = [1366, 2654, 3929, 1996]
AFTER_INPUT  = [614,  1179, 1735, 884]
BEFORE_BYTES = [3153, 6309, 9344, 4651]
AFTER_BYTES  = [1357, 2793, 4128, 2005]

# ── Campione payload "PRIMA" ──────────────────────────────────────────────────

sample = get_events_limited(1)[0]
full_json = json.dumps(sample, ensure_ascii=False, indent=2)

print("=" * 70)
print("PAYLOAD 'PRIMA' - un singolo evento mandato al LLM:")
print("=" * 70)
print(full_json)
print()
print(f"  => {len(full_json.encode())} bytes per UN evento")
print(f"  => 'reviewed' e 'detections' vengono mandati sempre,")
print(f"     anche quando la query chiede solo camera e severity.")

lean_fields = {"event_id", "event_datetime", "camera_name", "event_type", "severity"}
lean = {k: v for k, v in sample.items() if k in lean_fields}
lean_json = json.dumps(lean, ensure_ascii=False, separators=(",", ":"))
print()
print("PAYLOAD 'DOPO' - stesso evento, solo campi utili:")
print(lean_json)
print(f"\n  => {len(lean_json.encode())} bytes  ({(1 - len(lean_json)/len(full_json))*100:.0f}% piu' compatto)")
print("=" * 70)

# ── Plot ──────────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(13, 5))
fig.suptitle(
    "Token Budget: PRIMA (full payload) vs DOPO (lean fields)",
    fontsize=13, fontweight="bold"
)

x = np.arange(len(LABELS))
w = 0.35
C_BEFORE = "#e74c3c"
C_AFTER  = "#2ecc71"

def add_pct_labels(ax, x_pos, befores, afters, offset):
    for i, (b, a) in enumerate(zip(befores, afters)):
        pct = (b - a) / b * 100
        ax.annotate(
            f"-{pct:.0f}%",
            xy=(x_pos[i], max(b, a) + offset),
            ha="center", fontsize=9, color="#333", fontweight="bold"
        )

# --- Subplot 1: Input Tokens ---
ax = axes[0]
ax.bar(x - w/2, BEFORE_INPUT, w, label="PRIMA (full)", color=C_BEFORE, alpha=0.85)
ax.bar(x + w/2, AFTER_INPUT,  w, label="DOPO (lean)",  color=C_AFTER,  alpha=0.85)
add_pct_labels(ax, x, BEFORE_INPUT, AFTER_INPUT, offset=100)
ax.set_title("Input Tokens inviati a Gemini")
ax.set_ylabel("Tokens")
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=9)
ax.legend()
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0, max(BEFORE_INPUT) * 1.2)

# --- Subplot 2: Payload Bytes ---
ax = axes[1]
ax.bar(x - w/2, BEFORE_BYTES, w, label="PRIMA (full)", color=C_BEFORE, alpha=0.85)
ax.bar(x + w/2, AFTER_BYTES,  w, label="DOPO (lean)",  color=C_AFTER,  alpha=0.85)
add_pct_labels(ax, x, BEFORE_BYTES, AFTER_BYTES, offset=300)
ax.set_title("Bytes payload (JSON serializzato)")
ax.set_ylabel("Bytes")
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=9)
ax.legend()
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0, max(BEFORE_BYTES) * 1.2)

plt.tight_layout()
out_path = ROOT / "benchmark_token_budget.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"\nPlot salvato in: {out_path}")
plt.show()
