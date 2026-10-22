"""Gráficos del análisis de apalancamiento y top 10 (lee los CSV de results/)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot import plots  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEV = ROOT / "results" / "apalancamiento"
TOP = ROOT / "results" / "top10"


def chart_leverage_curve() -> None:
    import matplotlib.pyplot as plt

    a = pd.read_csv(TOP / "btc_eth_cartera_A_completo.csv")
    h = pd.read_csv(TOP / "btc_eth_cartera_HODL_completo.csv")
    pa = pd.read_csv(TOP / "pit_cartera_A_completo.csv")
    ph = pd.read_csv(TOP / "pit_cartera_HODL_completo.csv")
    series = [("Estrategia A en BTC y ETH", a, plots.SERIES[0]), ("Mantener BTC y ETH", h, plots.SERIES[1]),
              ("Estrategia A en el top 10 de cada momento", pa, plots.SERIES[2]),
              ("Mantener el top 10 de cada momento", ph, plots.SERIES[3])]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5.2))
    for name, df, color in series:
        a1.plot(df.apalancamiento, df.CAGR.clip(lower=-1), color=color, linewidth=2, marker="o", markersize=3.5, label=name)
        a2.plot(df.apalancamiento, df.max_caida, color=color, linewidth=2, marker="o", markersize=3.5)
    a2.axhspan(-1.02, -0.5, color="#f3a9a8", alpha=0.25, zorder=0)
    a2.axhline(-0.5, color=plots.SERIES[7], linewidth=1)
    a2.text(9.9, -0.47, "tu límite: −50 %", ha="right", color=plots.INK_2, fontsize=9)
    a1.axhline(0, color=plots.AXIS, linewidth=1)
    for ax in (a1, a2):
        ax.set_xticks(range(0, 11))
        ax.set_xticklabels([f"{x}x" for x in range(0, 11)])
        ax.set_xlabel("apalancamiento")
    plots.es_axis(a1.yaxis, percent=True)
    plots.es_axis(a2.yaxis, percent=True)
    a1.set_ylim(-1.05, 1.2)
    a2.set_ylim(-1.02, 0.02)
    a1.set_title("Rentabilidad anual compuesta", fontsize=11, pad=8)
    a2.set_title("Peor caída desde máximos", fontsize=11, pad=8)
    fig.suptitle("Con tu límite de −50 %: como mucho ~1,5x con A y 0,5x manteniendo BTC y ETH",
                 x=0.06, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.06, 0.915, "Enero 2019 – octubre 2026, con comisiones, funding real y liquidación con el mínimo de cada día. "
             "−100 % = capital perdido.",
             color=plots.INK_2, fontsize=9.5)
    handles, labels = a1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=9.5, bbox_to_anchor=(0.5, -0.04))
    fig.subplots_adjust(top=0.82, bottom=0.2, wspace=0.18)
    plots.save(fig, "09_curva_apalancamiento.png")


def chart_top10_curves() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    c = pd.read_csv(TOP / "curvas_1x.csv", index_col=0, parse_dates=True)
    panels = [
        ("Sesgo de supervivencia (mantener)",
         [("HODL top 10 actual", "Top 10 de hoy (con sesgo)", plots.SERIES[3]),
          ("HODL top 10 en su momento", "Top 10 de cada momento (sin sesgo)", plots.SERIES[1])]),
        ("¿Más monedas o solo BTC y ETH? (A)",
         [("A solo BTC y ETH", "Solo BTC y ETH", plots.SERIES[0]),
          ("A top 10 en su momento", "Top 10 de cada momento", plots.SERIES[2])]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), sharey=True)
    for ax, (title, series) in zip(axes, panels):
        ax.axvspan(pd.Timestamp("2025-01-01", tz="UTC"), c.index[-1], color="#f0efec", zorder=0)
        for col, label, color in series:
            s = c[col]
            ax.plot(s.index, s.values, color=color, linewidth=1.8, label=label)
            ax.plot([s.index[-1]], [s.iloc[-1]], "o", color=color, markersize=6,
                    markeredgecolor=plots.SURFACE, markeredgewidth=2)
            ax.annotate("×" + plots.num(s.iloc[-1], 1), (s.index[-1], s.iloc[-1]), textcoords="offset points",
                        xytext=(6, -3), color=plots.INK_2, fontsize=9)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(FixedLocator([0.5, 1, 2, 5, 10, 20, 50, 100, 200]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "×" + f"{v:g}".replace(".", ",")))
        ax.set_xlim(pd.Timestamp("2018-11-01", tz="UTC"), pd.Timestamp("2027-08-01", tz="UTC"))
        ax.set_title(title, fontsize=11, pad=8)
        ax.legend(loc="upper left", fontsize=9)
        ax.xaxis.set_major_locator(plt.matplotlib.dates.YearLocator(2))
        ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%Y"))
    fig.suptitle("Top 10: el de hoy engaña; sin sesgo, añadir monedas a BTC y ETH empeora el resultado",
                 x=0.06, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.06, 0.915, "Enero 2019 – octubre 2026, sin apalancamiento, a partes iguales con reparto mensual, "
             "neto de costes. Sombreado: examen final", color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.83, wspace=0.06)
    plots.save(fig, "10_top10_curvas.png")


def chart_top10_tokens() -> None:
    import matplotlib.pyplot as plt

    t = pd.read_csv(TOP / "actual_por_token.csv")
    t = t[t["caida_A_1x"].notna()].copy()
    t["etiqueta"] = t["token"] + np.where(t["en_OKX"] == "no", " (no en OKX)", "")
    t = t.sort_values("caida_HODL_1x").reset_index(drop=True)
    y = np.arange(len(t))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 5.4), sharey=True)
    a1.hlines(y, t["caida_HODL_1x"], t["caida_A_1x"], color=plots.AXIS, linewidth=1.2)
    a1.plot(t["caida_HODL_1x"], y, "o", color=plots.MUTED, markersize=6, label="Mantener (HODL)")
    a1.plot(t["caida_A_1x"], y, "o", color=plots.SERIES[0], markersize=6, label="Estrategia A")
    a1.axvline(-0.5, color=plots.SERIES[7], linewidth=1)
    plots.es_axis(a1.xaxis, percent=True)
    a1.set_title("Peor caída sin apalancamiento", fontsize=11, pad=8)
    a1.set_yticks(y, t["etiqueta"])
    a1.grid(axis="y", visible=False)
    h = 0.36
    a2.barh(y - h / 2, t["apalanc_max_HODL_caida≤50%"], height=h, color=plots.MUTED, label="Mantener (HODL)")
    a2.barh(y + h / 2, t["apalanc_max_A_caida≤50%"], height=h, color=plots.SERIES[0], label="Estrategia A")
    for yi, v in zip(y, t["apalanc_max_A_caida≤50%"]):
        a2.text(v + 0.05, yi + h / 2, f"{plots.num(v, 1)}x", va="center", color=plots.INK_2, fontsize=8.5)
    a2.set_title("Apalancamiento máximo sin pasar de −50 %", fontsize=11, pad=8)
    a2.grid(axis="y", visible=False)
    a2.set_xlim(0, max(3.0, t["apalanc_max_A_caida≤50%"].max() + 0.6))
    plots.es_axis(a2.xaxis, 1)
    a2.legend(loc="lower right", fontsize=9)
    fig.suptitle("Top 10 de hoy, token a token: A recorta las caídas; el margen para apalancar es pequeño",
                 x=0.06, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.06, 0.915, "Desde que cada token tiene 200 días de historia en Binance hasta oct 2026 (como máximo desde 2019)",
             color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.83, wspace=0.08)
    plots.save(fig, "11_top10_por_token.png")


def main() -> None:
    plots.setup()
    chart_leverage_curve()
    chart_top10_curves()
    chart_top10_tokens()


if __name__ == "__main__":
    main()
