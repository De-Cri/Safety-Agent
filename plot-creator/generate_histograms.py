import io
import base64
from dataclasses import dataclass, field


@dataclass
class ChartData:
    labels: list
    values: list
    title: str = ""
    chart_type: str = "bar"  # bar|line|pie|horizontal_bar|treemap|calendar_heatmap|heatmap_grid
    extra: dict = field(default_factory=dict)


def render_chart(data: ChartData) -> str:
    if data.chart_type == "calendar_heatmap":
        return _render_calendar_heatmap(data)
    if data.chart_type == "heatmap_grid":
        return _render_heatmap_grid(data)
    if data.chart_type == "treemap":
        return _render_treemap(data)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()

    if data.chart_type == "pie":
        ax.pie(data.values, labels=data.labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    elif data.chart_type == "line":
        ax.plot(data.labels, data.values, marker="o", linewidth=2)
        ax.tick_params(axis="x", rotation=45)
        ax.fill_between(range(len(data.labels)), data.values, alpha=0.15)
    elif data.chart_type == "horizontal_bar":
        ax.barh(data.labels, data.values)
        ax.invert_yaxis()
    else:  # bar
        ax.bar(data.labels, data.values)
        ax.tick_params(axis="x", rotation=45)

    if data.title:
        ax.set_title(data.title)

    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_treemap(data: ChartData) -> str:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import squarify

    fig, ax = plt.subplots(figsize=(10, 6))
    norm = [v / max(data.values) for v in data.values]
    colors = plt.cm.RdYlGn_r(norm)
    squarify.plot(
        sizes=data.values,
        label=[f"{l}\n{v}" for l, v in zip(data.labels, data.values)],
        color=colors,
        ax=ax,
        pad=2,
        text_kwargs={"fontsize": 9},
    )
    ax.axis("off")
    if data.title:
        ax.set_title(data.title, pad=12)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_calendar_heatmap(data: ChartData) -> str:
    """GitHub-style calendar: settimane sull'asse X, giorni sull'Y, colore = intensità."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from datetime import datetime, timedelta

    dates = [datetime.strptime(l, "%Y-%m-%d") for l in data.labels]
    counts = {d: v for d, v in zip(dates, data.values)}

    if not dates:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Nessun dato", ha="center", va="center")
        return _fig_to_b64(fig)

    start = min(dates) - timedelta(days=min(dates).weekday())  # allinea al lunedì
    end = max(dates) + timedelta(days=6 - max(dates).weekday())
    weeks = int((end - start).days / 7) + 1

    grid = np.zeros((7, weeks))
    d = start
    for w in range(weeks):
        for dow in range(7):
            grid[dow, w] = counts.get(d, 0)
            d += timedelta(days=1)

    vmax = grid.max() or 1
    fig, ax = plt.subplots(figsize=(max(8, weeks * 0.4), 3))
    im = ax.imshow(grid, aspect="auto", cmap="YlOrRd", vmin=0, vmax=vmax, interpolation="nearest")

    ax.set_yticks(range(7))
    ax.set_yticklabels(["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], fontsize=8)

    month_ticks, month_labels, prev_month = [], [], None
    for w in range(weeks):
        d_w = start + timedelta(weeks=w)
        if d_w.month != prev_month:
            month_ticks.append(w)
            _MESI = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"]
            month_labels.append(f"{_MESI[d_w.month - 1]} {d_w.year}")
            prev_month = d_w.month
    ax.set_xticks(month_ticks)
    ax.set_xticklabels(month_labels, ha="left", fontsize=8)

    plt.colorbar(im, ax=ax, label="eventi")
    if data.title:
        ax.set_title(data.title)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_heatmap_grid(data: ChartData) -> str:
    """Matrice generica: righe e colonne definite in extra['rows']/extra['cols'],
    default 7 giorni × 24 ore per events_by_weekday_hour."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    matrix = data.extra.get("matrix")
    if matrix is None:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Nessun dato", ha="center", va="center")
        return _fig_to_b64(fig)

    rows  = data.extra.get("rows",   ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"])
    cols  = data.extra.get("cols",   [f"{h:02d}" for h in range(24)])
    xlabel = data.extra.get("xlabel", "Ora del giorno")

    grid = np.array(matrix)
    n_rows, n_cols = grid.shape
    fig_w = max(8, n_cols * 0.55)
    fig_h = max(3, n_rows * 0.55)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(grid, aspect="auto", cmap="YlOrRd", interpolation="nearest")

    vmax = grid.max() or 1
    for r in range(n_rows):
        for c in range(n_cols):
            v = int(grid[r, c])
            if v > 0:
                brightness = grid[r, c] / vmax
                color = "white" if brightness > 0.6 else "black"
                ax.text(c, r, str(v), ha="center", va="center", fontsize=6, color=color)

    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(rows, fontsize=9)
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(cols, fontsize=7, rotation=45, ha="right")
    ax.set_xlabel(xlabel)
    plt.colorbar(im, ax=ax, label="eventi")
    if data.title:
        ax.set_title(data.title)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _fig_to_b64(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
