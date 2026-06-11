import io
import base64
from dataclasses import dataclass


@dataclass
class ChartData:
    labels: list
    values: list
    title: str = ""


def render_chart(data: ChartData) -> str:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.bar(data.labels, data.values)
    if data.title:
        ax.set_title(data.title)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
