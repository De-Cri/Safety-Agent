# Safety Agent — Agente LLM per l'analisi di eventi di sicurezza sul lavoro

*[Nome Cognome — eventuale corso/candidatura]*

## Contesto e obiettivo

Nei siti industriali i sistemi di computer vision collegati alle telecamere CCTV rilevano automaticamente le violazioni di sicurezza (DPI mancanti: casco, giubbotto ad alta visibilità, ecc.), producendo migliaia di eventi che nessun responsabile riesce a esaminare manualmente. Safety Agent trasforma questo flusso in una conversazione: l'utente chiede in linguaggio naturale ("quali telecamere registrano più violazioni?", "mostrami il trend dell'ultima settimana") e un agente LLM interroga il database e risponde con conteggi, filtri, trend temporali e grafici. Il progetto è stato sviluppato e validato su un dataset reale di eventi CCTV di un impianto industriale, non incluso nell'elaborato per riservatezza: i grafici e gli esempi allegati sono generati da dati sintetici equivalenti.

## Architettura

```
UI (chat web) → FastAPI → Agente (Gemini 2.5 Flash) → MCP server → PostgreSQL
```

La scelta progettuale centrale è che **il modello non riceve mai il dump del database**: accede ai dati esclusivamente attraverso strumenti esposti via Model Context Protocol (MCP). Il server MCP pubblica strumenti primitivi (`get_event_by_id`, `list_events`), aggregazioni (`count_events`, `group_by_count`, `average_severity`, `events_per_day`, `events_by_hour`) e una risorsa `db://schema` che descrive al modello lo schema *live* del database — telecamere e tipi di evento effettivi, letti all'avvio e iniettati nel system prompt. Questo garantisce risposte fondate sui dati (il modello non può inventare valori), privacy (vede solo ciò che serve alla domanda) e costi sotto controllo. Il backend FastAPI ospita il server MCP nel proprio ciclo di vita — un solo processo condiviso tra le richieste — e serve una UI di chat web; in alternativa è disponibile una CLI.

## Controllo del budget di token

Gli strumenti restituiscono di default solo i campi essenziali (modalità *lean*) e mai più di 20 righe; la cronologia della chat viene potata agli ultimi due turni. Un benchmark dedicato, con valutazione della qualità delle risposte tramite LLM-as-judge, confronta i payload completi con quelli filtrati su query realistiche: il filtro lato server riduce i token in input del **55–57% a parità di qualità della risposta**. Il benchmark ha anche guidato il design: per le domande di panoramica i listing grezzi spingono il modello a elencare anziché sintetizzare, da cui la scelta di fornire strumenti di aggregazione dedicati.

## Pipeline dati e validazione

Il dataset grezzo (CSV) attraversa una pipeline di analisi e pulizia (gestione duplicati, parsing di rilevazioni multiple per frame, separazione camera/tipo evento) prima dell'import in PostgreSQL su due tabelle normalizzate (`safety_events`, `event_detections`). Il progetto include test automatici su tre livelli: query sul database, strumenti MCP end-to-end e budget di token.

## Contenuto dell'elaborato

L'archivio contiene il codice sorgente completo (server MCP, agente, API, UI, pipeline dati, test e benchmark) e il video allegato dimostra il funzionamento: avvio del sistema, interrogazioni in linguaggio naturale e generazione di grafici dalle risposte.
