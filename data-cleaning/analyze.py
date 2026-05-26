
import sys
import csv

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import re
from datetime import datetime

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"

#Splits a trigger string into (violation_type, confidence) pairs, one per detection (detection>=1)

#The main thing from the data obtained is ,a trigger can be active on multiple detection per event, so
#the goal is to create a db structured to manage that
def parse_trigger(trigger_raw: str) -> list[tuple[str, float]]:
    results = []
    for part in trigger_raw.split(", "):
        part = part.strip()
        m = re.match(r"^(.*?)\s+(\d+)%$", part)
        if m:
            results.append((m.group(1).strip(), float(m.group(2))))
        else:
            results.append((part, None))
    return results

#This function helps extracting the camera_name from the event_name which are in the same "Name" column,
#this is crucial because from the same camera_name we can have different events_name.
# e.g. "[Uscita Pedane Bottom Extended:] Operators without Hard Hat (0,7);" and "[Uscita Pedane Bottom Extended:] Operators without High Vis Vest;"

def parse_name(name: str) -> tuple[str, str]:
    if ": " in name:
        parts = name.split(": ", 1)
        return parts[0].strip(), parts[1].strip()
    return name.strip(), ""


def load_data(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        for row in reader:
            rows.append(row)
    return rows


def main():
    rows = load_data(CSV_PATH)
    print(f"{'='*60}")
    print(f"ANALISI: {CSV_PATH}")
    print(f"{'='*60}")
    print(f"Totale righe: {len(rows)}")
    print(f"Colonne: {list(rows[0].keys())}\n")

    event_ids = [int(r["Event ID"]) for r in rows]
    event_ids_set = set(event_ids)
    duplicates = []
    if len(event_ids) != len(event_ids_set):
        seen = set()
        duplicates = [eid for eid in event_ids if eid in seen or seen.add(eid)]

    print(f"[Event ID]")
    print(f"  Range: {min(event_ids)} -> {max(event_ids)}")
    print(f"  Attesi (consecutivi): {max(event_ids) - min(event_ids) + 1}")
    print(f"  Presenti nel file:    {len(event_ids_set)}")
    expected = set(range(min(event_ids), max(event_ids) + 1))
    gaps = sorted(expected - set(event_ids))
    print(f"  ID mancanti (gap):    {len(gaps)}")
    if gaps[:20]:
        print(f"  Primi 20 gap: {gaps[:20]}")
    print(f"  Duplicati:            {len(duplicates)}")
    if duplicates:
        print(f"  ID duplicati: {duplicates}")
    print()




if __name__ == "__main__":
    main()
