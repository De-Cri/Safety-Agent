"""Rigenera i grafici in data-cleaning/plots/ con dati sintetici.

I grafici nel README non devono contenere dati reali: nomi di telecamere,
volumi e distribuzioni del dataset vero restano privati. Qui costruiamo un
DataFrame con la stessa forma di quello prodotto da visualize.load() ma con
camere inventate e conteggi campionati a caso, poi riusiamo le stesse
funzioni di plot così lo stile resta identico.

Uso (dalla root del repo, i path di salvataggio sono relativi):
    python data-cleaning/generate_demo_plots.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# visualize.py vive in una cartella con il trattino, quindi niente import
# di package: aggiungiamo la cartella al path e basta.
sys.path.insert(0, str(Path(__file__).parent))
import visualize  # noqa: E402

rng = np.random.default_rng(42)  # seed fisso: stessi grafici a ogni run

# Nomi di fantasia con un'aria industriale credibile
CAMERAS = [
    "Ingresso Nord",
    "Banchina Carico",
    "Magazzino A",
    "Piazzale Est",
    "Linea Confezionamento",
    "Uscita Sud",
    "Deposito Materiali",
    "Officina",
]
# Pesi diversi per camera: un grafico dove tutte le barre sono uguali
# non somiglia a nessun impianto reale
CAMERA_WEIGHTS = np.array([8, 6, 5, 4, 3, 2, 1.5, 1])
CAMERA_WEIGHTS = CAMERA_WEIGHTS / CAMERA_WEIGHTS.sum()

VIOLATIONS = ["No Hard Hat", "No High Vis vest", "No Face cover", "person"]
VIOLATION_WEIGHTS = np.array([0.55, 0.30, 0.10, 0.05])

# Le violazioni si concentrano nei cambi turno e dopo pranzo, di notte
# quasi nulla: la stessa forma che ci si aspetta da un impianto vero.
HOUR_WEIGHTS = np.array(
    [0.2, 0.1, 0.1, 0.1, 0.3, 1, 3, 6, 5, 4, 3.5, 3, 2, 5, 4.5, 4, 3.5, 4, 3, 1.5, 0.8, 0.5, 0.3, 0.2]
)
HOUR_WEIGHTS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

N_EVENTS = 2500
N_DAYS = 19
START = datetime(2026, 3, 1)


def make_demo_df() -> pd.DataFrame:
    cameras = rng.choice(CAMERAS, size=N_EVENTS, p=CAMERA_WEIGHTS)
    violations = rng.choice(VIOLATIONS, size=N_EVENTS, p=VIOLATION_WEIGHTS)
    days = rng.integers(0, N_DAYS, size=N_EVENTS)
    hours = rng.choice(24, size=N_EVENTS, p=HOUR_WEIGHTS)
    minutes = rng.integers(0, 60, size=N_EVENTS)

    # Severity alta per i DPI mancanti, bassa per le detection generiche
    severity = np.where(
        np.isin(violations, ["No Hard Hat", "No High Vis vest"]),
        rng.integers(5, 9, size=N_EVENTS),
        rng.integers(1, 5, size=N_EVENTS),
    )
    # Quasi sempre una persona sola nel frame, ogni tanto un gruppetto
    n_detections = rng.choice([1, 2, 3], size=N_EVENTS, p=[0.82, 0.13, 0.05])

    rows = []
    for i in range(N_EVENTS):
        dt = START + timedelta(days=int(days[i]), hours=int(hours[i]), minutes=int(minutes[i]))
        rows.append({
            "event_id":          i + 1,
            "datetime":          dt,
            "date":              dt.date(),
            "hour":              dt.hour,
            "camera":            cameras[i],
            "event_type":        violations[i],
            "severity":          int(severity[i]),
            "trigger_raw":       f"{violations[i]} {rng.integers(70, 96)}%",
            "primary_violation": violations[i],
            "n_detections":      int(n_detections[i]),
        })
    return pd.DataFrame(rows)


def main():
    df = make_demo_df()
    print(f"Dataset sintetico: {len(df)} eventi, {df['camera'].nunique()} camere\n")
    visualize.plot_violations_by_camera(df)
    visualize.plot_events_by_hour(df)
    visualize.plot_daily_trend(df)
    visualize.plot_severity_heatmap(df)
    visualize.plot_multi_detections(df)
    print("\nGrafici demo salvati in data-cleaning/plots/")


if __name__ == "__main__":
    main()
