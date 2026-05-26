
import sys
import csv

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import re
from datetime import datetime

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"

# the goal is to create a db structured to manage multiple detections per event that as well as splitting each sensitive information into a different column.

# Triggers can have multiple detections, comma-separated, one per person/vehicle in the frame
# Splits a trigger string into (violation_type, confidence) pairs, one per detection (detection>=1)
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

# This function splits the camera_name from the event_name that are in the same "Name" column,
# this is crucial because from the same camera_name we can have different events_name.
# e.g. "Uscita Pedane Bottom Extended: [Operators without Hard Hat (0,7)];" and "Uscita Pedane Bottom Extended: [Operators without High Vis Vest];"

def parse_name(name: str) -> tuple[str, str]:
    if ": " in name:
        parts = name.split(": ", 1)
        return parts[0].strip(), parts[1].strip()
    return name.strip(), ""

# Generic counter — applies extract() to each row and returns counts sorted by frequency.
def count_field(rows: list[dict], extract) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        key = extract(r)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

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
    
    # GENERAL EVENTS INFO

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

    # DATE AND TIME INFO
    # Parsing dates into datetime obj helps understanding time-range.
    parsed_dates = []
    date_errors = []
    for r in rows:
        try:
            dt = datetime.strptime(r["Date and Time"], "%d/%m/%Y, %H:%M:%S")
            parsed_dates.append(dt)
        except ValueError as e:
            date_errors.append((r["Event ID"], r["Date and Time"], str(e)))

    print(f"[Date and Time]")
    if parsed_dates:
        print(f"  Formato: DD/MM/YYYY, HH:MM:SS  ✓")
        print(f"  Periodo: {min(parsed_dates).strftime('%d/%m/%Y')} -> {max(parsed_dates).strftime('%d/%m/%Y')}")
        print(f"  Giorni distinti: {len(set(d.date() for d in parsed_dates))}")
    if date_errors:
        print(f"  ERRORI parsing ({len(date_errors)}):")
        for eid, val, err in date_errors[:5]:
            print(f"    ID {eid}: '{val}' → {err}")
    print()

    # SEVERITY ANALYSIS
    severities = [r["Severity"] for r in rows]
    sev_counts = count_field(rows, lambda r: r["Severity"])
    invalid_sev = [s for s in severities if not s.strip().isdigit()]

    print(f"[Severity]")
    for sev, cnt in sorted(sev_counts.items()):
        print(f"  {sev}: {cnt} eventi ({cnt/len(rows)*100:.1f}%)")
    if invalid_sev:
        print(f"  VALORI NON NUMERICI: {set(invalid_sev)}")
    print()

    # REVIEWD ANALYSIS
    reviewed_counts: dict[str, int] = {}
    for r in rows:
        v = r["Reviewed"]
        reviewed_counts[v] = reviewed_counts.get(v, 0) + 1
    print(f"[Reviewed]")
    for val, cnt in reviewed_counts.items():
        print(f"  '{val}': {cnt}")
    print()

    # Camera - Location analysis
    
    # Creating a dictionary, the intent is being able to dict gives O(1) lookup by camera name later
    cam_counts = count_field(rows, lambda r: parse_name(r["Name"])[0])
    et_counts  = count_field(rows, lambda r: parse_name(r["Name"])[1])
    print(f"[Location / Camera Name] — {len(cam_counts)} camere distinte")
    for cam, cnt in cam_counts.items():
        print(f"  {cam}: {cnt}")
    print()

    print(f"[Event Type] — {len(et_counts)} tipi distinti")
    for et, cnt in et_counts.items():
        print(f"  {et}: {cnt}")
    print()


    #Trigger analysis
    all_violations = []
    multi_detection_count = 0
    trigger_parse_errors = []
    for r in rows:
        raw = r["Trigger"]
        detections = parse_trigger(raw)
        if len(detections) > 1:
            multi_detection_count += 1
        for vtype, conf in detections:
            if conf is None:
                trigger_parse_errors.append((r["Event ID"], raw))
            else:
                all_violations.append(vtype)

    viol_counts: dict[str, int] = {}
    for vtype in all_violations:
        viol_counts[vtype] = viol_counts.get(vtype, 0) + 1
    print(f"[Trigger / Violations]")
    print(f"  Totale detection (incluse multi): {sum(viol_counts.values())}")
    print(f"  Eventi con detection multipla:    {multi_detection_count}")
    for vtype, cnt in sorted(viol_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  '{vtype}': {cnt}")
    if trigger_parse_errors:
        print(f"  ERRORI parsing trigger ({len(trigger_parse_errors)}):")
        for eid, raw in trigger_parse_errors[:5]:
            print(f"    ID {eid}: '{raw}'")
    print()

    sorted_ids = sorted(event_ids, reverse=True)
    is_sorted = event_ids == sorted_ids
    print(f"[Ordinamento]")
    print(f"  ID in ordine decrescente: {'Sì' if is_sorted else 'No (riordinamento locale presente)'}")
    print()

    # Null / empty checks
    print(f"[Campi vuoti / null]")
    field_empty: dict[str, int] = {}
    for r in rows:
        for k, v in r.items():
            if v is None or v.strip() == "":
                field_empty[k] = field_empty.get(k, 0) + 1
    if field_empty:
        for k, cnt in field_empty.items():
            print(f"  '{k}': {cnt} vuoti")
    else:
        print(f"  Nessun campo vuoto  ")
    print()


if __name__ == "__main__":
    main()
