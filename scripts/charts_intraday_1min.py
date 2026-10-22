"""Gráficos 18-20 de la ampliación con velas de 1 minuto (docs/intradia_1min.md)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from corrbot import plots  # noqa: E402
import charts_intraday as ci  # noqa: E402

RESULTS = HERE.parent / "results"
ORIG = RESULTS / "intradia"                    # señales 15m/1h, gestión con velas de 5 min
GEST1 = RESULTS / "intradia_gestion_1min"      # señales 15m/1h, gestión con velas de 1 min (parte A)
MIN1 = RESULTS / "intradia_1min"               # señales 1m/5m, gestión con velas de 1 min (parte B)
TF_COLOR = {"15m": plots.SERIES[0], "1h": plots.SERIES[2]}


def chart_resolution() -> None:
    """18: cada configuración simulada con velas de 5 min frente a velas de 1 min."""
    import matplotlib.pyplot as plt

    dev5 = pd.read_csv(ORIG / "desarrollo_rejilla.csv").set_index("config")
    dev1 = pd.read_csv(GEST1 / "desarrollo_rejilla.csv").set_index("config")
    ex5 = pd.read_csv(ORIG / "examen_rejilla.csv").set_index("config")
    ex1 = pd.read_csv(GEST1 / "examen_rejilla.csv").set_index("config")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6))
    panels = [(axes[0], dev5["media_neta"], dev1.loc[dev5.index, "media_neta"], dev5["temporalidad"],
               "Desarrollo 2018–2023"),
              (axes[1], ex5["examen_media_neta"], ex1.loc[ex5.index, "examen_media_neta"], ex5["temporalidad"],
               "Examen 2024–2026")]
    for ax, x, y, tf, title in panels:
        lo = min(x.min(), y.min()) * 1.08
        hi = max(0.0005, max(x.max(), y.max()) * 1.2)
        ax.axhspan(0, hi, color=plots.GRID, alpha=0.35, zorder=0)
        ax.plot([lo, hi], [lo, hi], color=plots.MUTED, linewidth=1, zorder=1)
        for t in ["15m", "1h"]:
            m = tf == t
            ax.scatter(x[m], y[m], s=30, color=TF_COLOR[t], edgecolors=plots.SURFACE, linewidths=0.8, zorder=3,
                       label=f"señales en velas de {ci.TF_LABEL[t]}")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.axhline(0, color=plots.INK_2, linewidth=1)
        ax.axvline(0, color=plots.INK_2, linewidth=1)
        ci._pct_axis(ax, 2)
        from matplotlib.ticker import FuncFormatter

        ax.yaxis.set_major_formatter(FuncFormatter(
            lambda v, _: "0" if abs(v) < 1e-12 else plots.num(v * 100, 2, sign=True).replace("-", "−") + " %"))
        ax.set_xlabel("simulando cada 5 minutos")
        ax.set_title(title, fontsize=11.5, pad=8)
        diff = (y - x).abs()
        ax.text(0.03, 0.95, f"diferencia mediana: {plots.num(diff.median() * 100, 3)} % por operación\n"
                            f"positivas: {int((x > 0).sum())} → {int((y > 0).sum())} de {len(x)}",
                transform=ax.transAxes, va="top", fontsize=9, color=plots.INK_2)
    axes[0].set_ylabel("simulando minuto a minuto")
    axes[0].legend(loc="lower right", fontsize=9)
    fig.suptitle("Seguir cada operación minuto a minuto da prácticamente el mismo resultado",
                 x=0.015, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.015, 0.905, "Rentabilidad media por operación de las 96 configuraciones (sin apalancar). "
             "Sobre la diagonal = igual; zona sombreada = ganancias", color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.82, wspace=0.22, left=0.08, right=0.98, bottom=0.12)
    plots.save(fig, "18_intradia_1min_precision.png")


def chart_costs_all() -> None:
    """20: costes en proporción al riesgo, de velas de 1 minuto a velas de 1 hora."""
    import matplotlib.pyplot as plt

    grid = pd.concat([pd.read_csv(MIN1 / "desarrollo_rejilla.csv"), pd.read_csv(ORIG / "desarrollo_rejilla.csv")])
    g = grid.groupby(["temporalidad", "k"]).agg(costes_R=("costes_y_funding_R", "mean"),
                                                 stop=("distancia_stop", "mean")).reset_index()
    tfs = ["1m", "5m", "15m", "1h"]
    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    width = 0.26
    for j, k in enumerate([1.0, 2.0, 3.0]):
        sub = g[g["k"] == k].set_index("temporalidad").loc[tfs]
        x = np.arange(len(tfs)) + (j - 1) * (width + 0.03)
        ax.bar(x, sub["costes_R"], width=width, color=plots.SERIES[j], label=f"stop a {int(k)} ATR")
        for xi, (cr, st) in zip(x, zip(sub["costes_R"], sub["stop"])):
            ax.text(xi, cr + 0.02, f"{plots.num(cr * 100, 0)} %", ha="center", va="bottom", color=plots.INK,
                    fontsize=9.5, fontweight="bold")
            ax.text(xi, -0.07, f"{plots.num(st * 100, 2)} %", ha="center", va="top", color=plots.INK_2,
                    fontsize=8)
    ax.axhline(1.0, color=plots.SERIES[7], linewidth=1, linestyle=(0, (4, 3)))
    ax.text(len(tfs) - 0.55, 1.03, "costes = todo lo que arriesga el stop", color=plots.INK_2, fontsize=9,
            ha="right", va="bottom")
    ax.set_xticks(np.arange(len(tfs)), [f"velas de {ci.TF_LABEL[t]}" for t in tfs])
    ax.tick_params(axis="x", pad=22)
    ax.text(-0.5, -0.07, "stop medio:", ha="right", va="top", color=plots.INK_2, fontsize=8)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ci._plain_pct_axis(ax.yaxis)
    ax.set_ylim(0, max(1.1, g["costes_R"].max() * 1.15))
    ax.set_ylabel("costes por operación, en % de lo que arriesga el stop")
    ax.legend(loc="upper right", ncol=3)
    ax.set_title("Cuanto más pequeña es la vela, más pesan los costes", pad=26)
    plots.subtitle(ax, "Media de las operaciones de desarrollo (2018–2023, BTC+ETH). Comisiones, deslizamiento y "
                       "funding; ida y vuelta ≈ 0,12–0,14 % del precio")
    plots.save(fig, "20_intradia_costes_1min_a_1h.png")


def main() -> None:
    plots.setup()
    chart_resolution()
    ci.chart_entries_vs_random(
        res=MIN1, tfs=("1m", "5m"), name="19_intradia_1min_entradas_vs_azar.png",
        title="En velas de 1 y 5 minutos tampoco hay ventaja, y los costes pesan aún más",
        subtitle="Desarrollo 2018–2023, BTC+ETH, seguimiento minuto a minuto. Cada punto de color es una de las 96 "
                 "configuraciones; los grises, entradas al azar (20 semillas)", tick_step=0.0005)
    chart_costs_all()


if __name__ == "__main__":
    main()
