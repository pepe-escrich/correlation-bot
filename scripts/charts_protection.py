"""Gráficos del análisis de controles de protección (lee results/proteccion/)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot import plots  # noqa: E402

RES = Path(__file__).resolve().parent.parent / "results" / "proteccion"


def chart_max_leverage() -> None:
    import matplotlib.pyplot as plt

    best = pd.read_csv(RES / "apalancamiento_maximo_por_variante.csv")
    best = best.iloc[::-1].reset_index(drop=True)
    y = np.arange(len(best))
    base = best.loc[best["variante"] == "Sin protección", "CAGR_hist"].iloc[0]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    colors = [plots.SERIES[0] if v == "Sin protección" else (plots.SERIES[1] if "a posteriori" in v else plots.MUTED)
              for v in best["variante"]]
    ax.barh(y, best["CAGR_hist"], height=0.55, color=colors)
    ax.axvline(base, color=plots.SERIES[0], linewidth=1)
    for yi, (lev, cagr, dd, p50) in enumerate(zip(best["apalanc_mejor_aceptable"], best["CAGR_hist"],
                                                   best["caida_hist"], best["P(caída>50%)"])):
        ax.text(cagr + 0.006, yi, f"{plots.num(lev, 1)}x · peor caída {plots.num(dd * 100, 0)} % · "
                                  f"prob. >50 %: {plots.num(p50 * 100, 0)} %", va="center", color=plots.INK_2, fontsize=8.8)
    ax.set_yticks(y, best["variante"])
    ax.set_xlim(0, 0.66)
    ax.grid(axis="y", visible=False)
    plots.es_axis(ax.xaxis, percent=True)
    ax.set_xlabel("rentabilidad anual compuesta (2018–2026) con el mejor apalancamiento que cumple tu límite")
    ax.set_title("Solo una combinación elegida a posteriori rinde más que no apalancar, y justo en el límite", pad=26)
    plots.subtitle(ax, "Para cada control: el apalancamiento que más rinde sin pasar de −50 % (histórico), con ≤ 5 % "
                       "de probabilidad de superarlo en 3 años y ≤ 1 % de liquidación")
    plots.save(fig, "12_proteccion_apalancamiento_max.png")


def chart_risk_return() -> None:
    import matplotlib.pyplot as plt

    tab = pd.read_csv(RES / "variantes_apalancamiento.csv")
    ref = tab[tab["variante"] == "Sin protección"].sort_values("apalancamiento")
    panels = ["Volatilidad rápida", "Stop intradía (3σ)", "Freno por caída (suelo −40 %)",
              "Freno con reinicio anual", "Apalancar solo con tendencia fuerte",
              "Tendencia fuerte + freno con reinicio (a posteriori)"]
    panels = [p for p in panels if p in set(tab["variante"])]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.4), sharex=True, sharey=True)
    for ax, name in zip(axes.flat, panels):
        g = tab[tab["variante"] == name].sort_values("apalancamiento")
        ax.axvspan(-1.05, -0.5, color="#f3a9a8", alpha=0.25, zorder=0)
        ax.axvline(-0.5, color=plots.SERIES[7], linewidth=1)
        ax.plot(ref["hist_max_caida"], ref["hist_CAGR"].clip(lower=-0.3), color=plots.MUTED, linewidth=1.4,
                marker="o", markersize=3, label="Sin protección")
        ax.plot(g["hist_max_caida"], g["hist_CAGR"].clip(lower=-0.3), color=plots.SERIES[0], linewidth=2,
                marker="o", markersize=4, label="Con el control")
        for lev in [1, 2, 3]:
            row = g[g["apalancamiento"] == lev]
            if len(row) and row["hist_CAGR"].iloc[0] > -0.3:
                ax.annotate(f"{lev}x", (row["hist_max_caida"].iloc[0], row["hist_CAGR"].iloc[0]),
                            textcoords="offset points", xytext=(4, 6), color=plots.INK, fontsize=8.5)
        ax.set_title(name, fontsize=10, pad=6)
        ax.set_xlim(-1.02, -0.15)
        ax.set_ylim(-0.3, 0.85)
        ax.set_xticks([-0.8, -0.6, -0.4, -0.2])
    for ax in axes.flat[len(panels):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        plots.es_axis(ax.xaxis, percent=True)
        ax.set_xlabel("peor caída histórica")
    for ax in axes[:, 0]:
        plots.es_axis(ax.yaxis, percent=True)
        ax.set_ylabel("rentabilidad anual")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.985, 0.955), ncol=2, fontsize=9.5)
    fig.suptitle("Cada control frente a no proteger, de 1x a 10x", x=0.06, ha="left", fontsize=13,
                 fontweight="bold", color=plots.INK)
    fig.text(0.06, 0.925, "Mejor = más arriba con la misma caída. Zona roja: por encima de tu límite de −50 %. "
             "BTC+ETH, 2018–2026", color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.86, hspace=0.25, wspace=0.08)
    plots.save(fig, "13_proteccion_riesgo_rentabilidad.png")


def main() -> None:
    plots.setup()
    chart_max_leverage()
    chart_risk_return()


if __name__ == "__main__":
    main()
