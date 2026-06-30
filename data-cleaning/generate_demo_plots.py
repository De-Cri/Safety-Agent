"""Regenerate the charts in data-cleaning/plots/ with synthetic data.

The charts in the README must not contain real data: camera names,
volumes, and distributions of the real dataset stay private. Here we build a
DataFrame with the same shape as the one produced by visualize.load() but with
made-up cameras and randomly sampled counts, then reuse the same plot
functions so the style stays identical.

Usage (from the repo root, the save paths are relative):
    python data-cleaning/generate_demo_plots.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# visualize.py lives in a folder with a hyphen, so no package import:
# we just add the folder to the path.
sys.path.insert(0, str(Path(__file__).parent))
import visualize  # noqa: E402

rng = np.random.default_rng(42)  # fixed seed: same charts on every run

# Made-up names with a believable industrial feel
CAMERAS = [
    "North Entrance",
    "Loading Dock",
    "Warehouse A",
    "East Yard",
    "Packaging Line",
    "South Exit",
    "Materials Store",
    "Workshop",
]
# Different weights per camera: a chart where all bars are equal
# does not resemble any real plant
CAMERA_WEIGHTS = np.array([8, 6, 5, 4, 3, 2, 1.5, 1])
CAMERA_WEIGHTS = CAMERA_WEIGHTS / CAMERA_WEIGHTS.sum()

VIOLATIONS = ["No Hard Hat", "No High Vis vest", "No Face cover", "person"]
VIOLATION_WEIGHTS = np.array([0.55, 0.30, 0.10, 0.05])

# Violations cluster around shift changes and after lunch, at night
# almost nothing: the same shape you'd expect from a real plant.
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

    # High severity for missing PPE, low for generic detections
    severity = np.where(
        np.isin(violations, ["No Hard Hat", "No High Vis vest"]),
        rng.integers(5, 9, size=N_EVENTS),
        rng.integers(1, 5, size=N_EVENTS),
    )
    # Almost always a single person in the frame, occasionally a small group
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
    print(f"Synthetic dataset: {len(df)} events, {df['camera'].nunique()} cameras\n")
    visualize.plot_violations_by_camera(df)
    visualize.plot_events_by_hour(df)
    visualize.plot_daily_trend(df)
    visualize.plot_severity_heatmap(df)
    visualize.plot_multi_detections(df)
    print("\nDemo charts saved to data-cleaning/plots/")


if __name__ == "__main__":
    main()
