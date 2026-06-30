import sys
import csv
import re
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import seaborn as sns

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"

sns.set_theme(style="whitegrid", palette="muted")


# ---------------------------------------------------------------------------
# Load + parse into a DataFrame
# ---------------------------------------------------------------------------

def parse_trigger(trigger_raw: str) -> list[tuple[str, float | None]]:
    # Each detection in the trigger is "ViolationType XX%" — one per person/vehicle
    results = []
    for part in trigger_raw.split(", "):
        part = part.strip()
        m = re.match(r"^(.*?)\s+(\d+)%$", part)
        if m:
            results.append((m.group(1).strip(), float(m.group(2))))
        else:
            results.append((part, None))
    return results


def load(path: str) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=DELIMITER):
            camera, event_type = r["Name"].split(": ", 1) if ": " in r["Name"] else (r["Name"], "")
            dt = datetime.strptime(r["Date and Time"], "%d/%m/%Y, %H:%M:%S")
            detections = parse_trigger(r["Trigger"])
            # Primary violation = first detection type
            primary_violation = detections[0][0] if detections else ""
            rows.append({
                "event_id":        int(r["Event ID"]),
                "datetime":        dt,
                "date":            dt.date(),
                "hour":            dt.hour,
                "camera":          camera.strip(),
                "event_type":      event_type.strip(),
                "severity":        int(r["Severity"]),
                "trigger_raw":     r["Trigger"],
                "primary_violation": primary_violation,
                "n_detections":    len(detections),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Plot 1 — Violations by camera (stacked bar)
# Shows which cameras are hotspots and what violation dominates each one
# ---------------------------------------------------------------------------

def plot_violations_by_camera(df: pd.DataFrame):
    pivot = (
        df.groupby(["camera", "primary_violation"])
        .size()
        .unstack(fill_value=0)
    )
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=True).index]

    fig, ax = plt.subplots(figsize=(12, 6))
    pivot.plot(kind="barh", stacked=True, ax=ax, colormap="tab10")
    ax.set_title("Violations by camera", fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of events")
    ax.set_ylabel("")
    ax.legend(title="Violation type", bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig("data-cleaning/plots/plot_1_violations_by_camera.png", dpi=150)
    plt.close()
    print("Saved: plot_1_violations_by_camera.png")


# ---------------------------------------------------------------------------
# Plot 2 — Events by hour of day
# Violations spike at shift changes (morning, lunch, afternoon)?
# ---------------------------------------------------------------------------

def plot_events_by_hour(df: pd.DataFrame):
    hourly = df.groupby(["hour", "primary_violation"]).size().unstack(fill_value=0)

    fig, ax = plt.subplots(figsize=(14, 5))
    hourly.plot(kind="bar", stacked=True, ax=ax, colormap="tab10", width=0.85)
    ax.set_title("Event distribution by hour of day", fontsize=14, fontweight="bold")
    ax.set_xlabel("Hour")
    ax.set_ylabel("Number of events")
    ax.set_xticklabels([str(h) for h in hourly.index], rotation=0)
    ax.legend(title="Violation type", bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig("data-cleaning/plots/plot_2_events_by_hour.png", dpi=150)
    plt.close()
    print("Saved: plot_2_events_by_hour.png")


# ---------------------------------------------------------------------------
# Plot 3 — Daily trend over the 19-day period
# Is safety improving or getting worse over time?
# ---------------------------------------------------------------------------

def plot_daily_trend(df: pd.DataFrame):
    daily = df.groupby(["date", "primary_violation"]).size().unstack(fill_value=0)
    daily.index = pd.to_datetime(daily.index)

    fig, ax = plt.subplots(figsize=(14, 5))
    for col in daily.columns:
        ax.plot(daily.index, daily[col], marker="o", markersize=4, label=col)
    ax.set_title("Daily violation trend", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Number of events")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.legend(title="Violation type", bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("data-cleaning/plots/plot_3_daily_trend.png", dpi=150)
    plt.close()
    print("Saved: plot_3_daily_trend.png")


# ---------------------------------------------------------------------------
# Plot 4 — Severity heatmap: camera × severity level
# Which cameras generate the most critical events?
# ---------------------------------------------------------------------------

def plot_severity_heatmap(df: pd.DataFrame):
    pivot = (
        df.groupby(["camera", "severity"])
        .size()
        .unstack(fill_value=0)
    )
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="YlOrRd", ax=ax, linewidths=0.5)
    ax.set_title("Severity by camera", fontsize=14, fontweight="bold")
    ax.set_xlabel("Severity")
    ax.set_ylabel("")
    plt.tight_layout()
    plt.savefig("data-cleaning/plots/plot_4_severity_heatmap.png", dpi=150)
    plt.close()
    print("Saved: plot_4_severity_heatmap.png")


# ---------------------------------------------------------------------------
# Plot 5 — Multiple detections per camera
# Where do multiple people appear without PPE in the same frame?
# ---------------------------------------------------------------------------

def plot_multi_detections(df: pd.DataFrame):
    multi = df[df["n_detections"] > 1]
    counts = multi.groupby("camera").size().sort_values(ascending=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    counts.plot(kind="barh", ax=ax, color=sns.color_palette("muted")[2])
    ax.set_title("Cameras with multiple detections in the same frame", fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of multi-detection events")
    ax.set_ylabel("")
    plt.tight_layout()
    plt.savefig("data-cleaning/plots/plot_5_multi_detections.png", dpi=150)
    plt.close()
    print("Saved: plot_5_multi_detections.png")


def main():
    print("Loading data...")
    df = load(CSV_PATH)
    print(f"  {len(df)} events loaded\n")

    print("Generating charts:")
    plot_violations_by_camera(df)
    plot_events_by_hour(df)
    plot_daily_trend(df)
    plot_severity_heatmap(df)
    plot_multi_detections(df)

    print("\nAll charts saved to data-cleaning/plots/")


if __name__ == "__main__":
    main()
