"""Estilo común de gráficos (paleta validada para daltonismo, líneas finas, rejilla tenue)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent.parent / "docs" / "img"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# Paleta categórica (orden fijo; nunca se cicla).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# Divergente azul <-> rojo con gris neutro en el centro.
DIVERGING = ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f3a9a8", "#e34948", "#a32b2a"]


def setup() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.size": 10.5,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2,
        "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": INK,
        "axes.titlelocation": "left", "axes.titlepad": 12,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.labelcolor": INK_2,
    })


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def num(v: float, decimals: int = 2, sign: bool = False) -> str:
    """Número con coma decimal (formato español)."""
    text = f"{v:+.{decimals}f}" if sign else f"{v:.{decimals}f}"
    return text.replace(".", ",")


def pct(v: float, decimals: int = 0, sign: bool = True) -> str:
    return num(v * 100, decimals, sign) + " %"


def mes(ts) -> str:
    return f"{MESES[ts.month - 1]} {ts.year}"


def es_axis(axis, decimals: int = 1, percent: bool = False) -> None:
    """Etiquetas de eje con coma decimal (o en % si percent=True)."""
    from matplotlib.ticker import FuncFormatter

    if percent:
        axis.set_major_formatter(FuncFormatter(lambda v, _: "0" if abs(v) < 1e-12 else pct(v)))
    else:
        axis.set_major_formatter(FuncFormatter(lambda v, _: num(v, decimals).replace("-", "−")))


def subtitle(ax, text: str) -> None:
    """Subtítulo gris bajo el título (va dentro del área del eje, arriba a la izquierda)."""
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK_2, fontsize=9.5, va="bottom")


def save(fig, name: str) -> Path:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    path = IMG_DIR / name
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path
