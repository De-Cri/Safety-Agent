#!/usr/bin/env python3
"""Genera benchmark_report.html dai risultati in benchmark_results.json."""

import json
from pathlib import Path

ROOT    = Path(__file__).parent
RESULTS = json.loads((ROOT / "benchmark_results.json").read_text(encoding="utf-8"))

# ── Giudizi di Claude (LLM-as-judge) ─────────────────────────────────────────
JUDGE_MODEL = "Claude Sonnet 4.6 (claude-sonnet-4-6)"

JUDGES = {
    "q1": {
        "score_full": "✅ Buona",
        "score_lean": "✅ Migliore",
        "verdict":    "🟢 LEAN vince",
        "note": (
            "Entrambe corrette sui dati richiesti (camera + severity). "
            "FULL dichiara erroneamente di ordinare 'dalla più recente' mentre i dati "
            "sono ascending — errore di interpretazione dell'ordinamento. "
            "LEAN usa numerazione esplicita ed è più precisa. "
            "Risparmio: -843 input tok (-62%) con qualità superiore."
        ),
    },
    "q2": {
        "score_full": "✅ Ottima",
        "score_lean": "⚠️ Verbosa (v2 fix parziale)",
        "verdict":    "🔴 FULL vince",
        "note": (
            "FULL: sintesi eccellente in 343 output tok — periodo, tipologie con conteggi, "
            "telecamere, severity, stato revisione, range confidence. "
            "LEAN v1 (con reviewed): listing da 1790 tok. "
            "LEAN v2 (fix — senza reviewed): listing da 1610 tok. "
            "Il fix ha ridotto il verbosity ma non ha risolto il problema strutturale: "
            "la presenza di event_id per ogni riga spinge il modello in 'listing mode' "
            "indipendentemente dai campi inclusi. "
            "Conclusione: per query di panoramica servono tool di aggregazione (COUNT/GROUP BY), "
            "non raw event listing. Il filtro sui campi da solo non è sufficiente."
        ),
    },
    "q3": {
        "score_full": "✅ Corretta",
        "score_lean": "✅ Corretta (v2 fix ok)",
        "verdict":    "🟢 LEAN vince",
        "note": (
            "FULL: classifica corretta delle 5 camere, incluse le due prime a pari merito. "
            "LEAN v1 (solo camera_name, no event_id): riportava solo una delle due prime — pareggio mancato. "
            "LEAN v2 (fix — event_id + camera_name): identifica correttamente entrambi i vincitori a pari merito. "
            "Il fix ha funzionato perfettamente: event_id come anchor di conteggio è sufficiente. "
            "Risparmio: -3316 input tok (-84%) con qualità identica a FULL."
        ),
    },
    "q4": {
        "score_full": "✅ Corretta",
        "score_lean": "✅ Identica",
        "verdict":    "🟢 LEAN vince",
        "note": (
            "Entrambe: Event No Hard Hat 13, Operators without High Vis Vest 1, Operators Event-2 1. "
            "Risparmio: -1735 input tok (-87%) con qualità identica. "
            "Caso ideale per il filtro: event_type + severity bastano per un riepilogo per tipologia."
        ),
    },
}

QUERY_LABELS = {
    "q1": "Elenca le ultime 10 violazioni con camera e severity",
    "q2": "Fammi una panoramica delle ultime 20 violazioni",
    "q3": "Quali telecamere compaiono di più tra le ultime 30 violazioni?",
    "q4": "Riassumi gli ultimi 15 eventi di sicurezza per tipologia",
}

# ── HTML ──────────────────────────────────────────────────────────────────────

def tok_badge(n, cls=""):
    return f'<span class="badge {cls}">{n:,} tok</span>'

def savings_bar(full_in, lean_in):
    pct = (full_in - lean_in) / full_in * 100
    color = "#2ecc71" if pct >= 60 else "#f39c12"
    return (
        f'<div class="savings-bar">'
        f'<div style="width:{pct:.0f}%;background:{color}"></div>'
        f'</div>'
        f'<span class="savings-label">−{pct:.0f}% input token</span>'
    )

def response_cell(r, variant):
    fields_str = ", ".join(r["fields"]) if r["fields"] != ["*"] else "* (tutti)"
    return f"""
        <div class="resp-meta">
            <b>Fields:</b> <code>{fields_str}</code><br>
            {tok_badge(r['input_tok'], 'badge-in')} input &nbsp;
            {tok_badge(r['output_tok'], 'badge-out')} output &nbsp;
            {tok_badge(r['total_tok'], 'badge-tot')} totali<br>
            <small>Payload: {r['payload_bytes']:,} bytes · Modello: {r['model']}</small>
        </div>
        <div class="resp-text">{r['text'].replace(chr(10), '<br>')}</div>
    """

rows_html = ""
for qid, label in QUERY_LABELS.items():
    full  = RESULTS[f"{qid}_full"]
    lean  = RESULTS[f"{qid}_lean"]
    judge = JUDGES[qid]

    rows_html += f"""
    <tr>
        <td class="col-query">
            <div class="query-id">{qid.upper()}</div>
            <div class="query-text">{label}</div>
            <div class="savings-wrap">
                {savings_bar(full['input_tok'], lean['input_tok'])}
            </div>
        </td>
        <td class="col-full">
            {response_cell(full, 'full')}
        </td>
        <td class="col-lean">
            {response_cell(lean, 'lean')}
        </td>
        <td class="col-judge">
            <div class="judge-scores">
                <span>FULL: {judge['score_full']}</span>
                <span>LEAN: {judge['score_lean']}</span>
                <span class="verdict">{judge['verdict']}</span>
            </div>
            <div class="judge-note">{judge['note']}</div>
        </td>
    </tr>
    """

html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>Benchmark Token Budget — Safety Agent</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 13px; background: #f5f6fa; color: #2d3436; }}

  h1 {{ padding: 24px 32px 8px; font-size: 20px; color: #2d3436; }}
  .subtitle {{ padding: 0 32px 20px; color: #636e72; font-size: 12px; }}

  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #2d3436; color: #fff; padding: 12px 14px;
    text-align: left; font-size: 12px; font-weight: 600; letter-spacing: .5px;
    position: sticky; top: 0; z-index: 10;
  }}
  tr:nth-child(even) td {{ background: #fafbfc; }}
  td {{ padding: 14px; vertical-align: top; border-bottom: 1px solid #dfe6e9; }}

  .col-query  {{ width: 14%; background: #fff !important; }}
  .col-full   {{ width: 26%; border-left: 3px solid #e17055; }}
  .col-lean   {{ width: 26%; border-left: 3px solid #00b894; }}
  .col-judge  {{ width: 34%; border-left: 3px solid #6c5ce7; background: #faf9ff !important; }}

  .query-id   {{ font-weight: 700; font-size: 18px; color: #6c5ce7; margin-bottom: 6px; }}
  .query-text {{ font-weight: 600; margin-bottom: 10px; line-height: 1.4; }}

  .resp-meta {{ background: #f5f6fa; border-radius: 6px; padding: 8px 10px;
               margin-bottom: 10px; font-size: 11px; line-height: 1.8; }}
  .resp-text {{ line-height: 1.6; font-size: 12px; }}

  .badge {{ display: inline-block; border-radius: 4px; padding: 1px 6px;
           font-size: 11px; font-weight: 600; }}
  .badge-in  {{ background: #dfe6e9; color: #2d3436; }}
  .badge-out {{ background: #d1ecf1; color: #0c5460; }}
  .badge-tot {{ background: #fff3cd; color: #856404; }}

  .savings-wrap {{ margin-top: 8px; }}
  .savings-bar  {{ height: 8px; background: #dfe6e9; border-radius: 4px; overflow: hidden; margin-bottom: 3px; }}
  .savings-bar div {{ height: 100%; border-radius: 4px; }}
  .savings-label {{ font-size: 11px; font-weight: 700; }}

  .judge-scores {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
  .judge-scores span {{ background: #f5f6fa; border-radius: 4px;
                       padding: 3px 8px; font-size: 11px; font-weight: 600; }}
  .verdict {{ background: #6c5ce7 !important; color: #fff !important; }}
  .judge-note {{ line-height: 1.6; font-size: 12px; color: #2d3436; }}

  code {{ background: #f0f0f0; border-radius: 3px; padding: 1px 4px; font-size: 11px; }}

  .summary-bar {{
    display: flex; gap: 24px; padding: 16px 32px;
    background: #2d3436; color: #fff; font-size: 12px; flex-wrap: wrap;
  }}
  .summary-bar .item {{ display: flex; flex-direction: column; }}
  .summary-bar .val  {{ font-size: 22px; font-weight: 700; color: #00b894; }}
  .summary-bar .lbl  {{ color: #b2bec3; font-size: 11px; }}
</style>
</head>
<body>

<h1>Benchmark Token Budget — Safety Agent MCP</h1>
<p class="subtitle">
  Gemini 2.5-Flash · GEMINI_API_KEY_FALLBACK · LLM-as-Judge: {JUDGE_MODEL}
</p>

<div class="summary-bar">
  <div class="item"><span class="val">8</span><span class="lbl">Chiamate API totali</span></div>
  <div class="item"><span class="val">{sum(RESULTS[f'{q}_full']['input_tok'] for q in QUERY_LABELS):,}</span><span class="lbl">Input token SENZA filtro</span></div>
  <div class="item"><span class="val">{sum(RESULTS[f'{q}_lean']['input_tok'] for q in QUERY_LABELS):,}</span><span class="lbl">Input token CON filtro</span></div>
  <div class="item">
    <span class="val">
      {(1 - sum(RESULTS[f'{q}_lean']['input_tok'] for q in QUERY_LABELS) /
             sum(RESULTS[f'{q}_full']['input_tok'] for q in QUERY_LABELS)) * 100:.0f}%
    </span>
    <span class="lbl">Risparmio medio input token</span>
  </div>
  <div class="item"><span class="val" style="color:#e17055">1/4</span><span class="lbl">Query dove FULL è migliore (Q2)</span></div>
  <div class="item"><span class="val" style="color:#00b894">3/4</span><span class="lbl">Query dove LEAN è migliore o pari (dopo fix)</span></div>
</div>

<table>
  <thead>
    <tr>
      <th>Query</th>
      <th>🔴 SENZA filtro — payload completo (fields=*)</th>
      <th>🟢 CON filtro — fields scelti dal LLM</th>
      <th>⚖️ LLM as Judge · {JUDGE_MODEL}</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>

</body>
</html>
"""

out = ROOT / "benchmark_report.html"
out.write_text(html, encoding="utf-8")
print(f"Report generato: {out}")
