"""Gráficos 14-17 de la estrategia intradía con stop escalonado (lee results/intradia/)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot import plots  # noqa: E402

RES = Path(__file__).resolve().parent.parent / "results" / "intradia"
TF_LABEL = {"1m": "1 min", "5m": "5 min", "15m": "15 min", "1h": "1 hora"}
ENTRY_COLOR = {"ruptura": plots.SERIES[0], "retroceso": plots.SERIES[1]}
REASON_ORDER = ["stop", "breakeven", "stop que persigue", "objetivo", "tiempo"]
REASON_LABEL = {"stop": "stop inicial", "breakeven": "breakeven", "stop que persigue": "stop que persigue",
                "objetivo": "objetivo 3R", "tiempo": "cierre a las 24 h"}


def _signed_pct(v: float, decimals: int) -> str:
    if round(abs(v) * 100, decimals) == 0:
        return "0 %"
    return plots.num(v * 100, decimals, sign=True).replace("-", "−") + " %"


def _plain_pct_axis(axis) -> None:
    from matplotlib.ticker import FuncFormatter

    axis.set_major_formatter(FuncFormatter(lambda v, _: "0" if abs(v) < 1e-12 else plots.num(v * 100, 0) + " %"))


def _pct_axis(ax, decimals: int = 2) -> None:
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: "0" if abs(v) < 1e-12 else plots.num(v * 100, decimals, sign=True).replace("-", "−") + " %"))


def chart_entries_vs_random(res: Path = RES, tfs: tuple[str, ...] = ("15m", "1h"),
                            name: str = "14_intradia_entradas_vs_azar.png",
                            title: str = "Ninguna entrada se distingue del azar, y los costes las dejan todas en negativo",
                            subtitle: str = "Desarrollo 2018–2023, BTC+ETH. Cada punto de color es una de las 96 "
                                            "configuraciones; los grises, entradas al azar con las mismas gestiones "
                                            "(20 semillas)", tick_step: float | None = None) -> None:
    """14 (y 19): cada configuración frente a las entradas al azar, antes y después de costes."""
    import matplotlib.pyplot as plt

    grid = pd.read_csv(res / "desarrollo_rejilla.csv")
    rand = pd.read_csv(res / "azar_desarrollo.csv")
    sel = json.loads((res / "veredicto.json").read_text())["seleccionada"]
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True, sharex=True)
    rows = [(tf, e) for tf in tfs for e in ("ruptura", "retroceso", "al azar")]
    ypos = {row: len(rows) - 1 - i for i, row in enumerate(rows)}
    for ax, col, panel in [(axes[0], "media_bruta", "Antes de costes"), (axes[1], "media_neta", "Después de costes")]:
        for (tf, entry), y in ypos.items():
            if entry == "al azar":
                v = rand.loc[rand["temporalidad"] == tf, col].to_numpy()
                ax.scatter(v, y + rng.uniform(-0.28, 0.28, len(v)), s=7, color=plots.MUTED, alpha=0.35,
                           linewidths=0, zorder=2)
            else:
                g = grid[(grid["temporalidad"] == tf) & (grid["entrada"] == entry)]
                ax.scatter(g[col], y + rng.uniform(-0.18, 0.18, len(g)), s=34, color=ENTRY_COLOR[entry],
                           edgecolors=plots.SURFACE, linewidths=0.8, zorder=3)
                hit = g[g["config"] == sel]
                if len(hit):
                    ax.scatter(hit[col], [y] * len(hit), s=120, facecolors="none", edgecolors=plots.INK,
                               linewidths=1.4, zorder=4)
        ax.axvline(0, color=plots.INK_2, linewidth=1, zorder=1)
        ax.set_title(panel, fontsize=11.5, pad=8)
        ax.grid(axis="y", visible=False)
        if tick_step:
            from matplotlib.ticker import MultipleLocator

            ax.xaxis.set_major_locator(MultipleLocator(tick_step))
        _pct_axis(ax)
        ax.set_xlabel("rentabilidad media por operación (sin apalancar)")
    axes[0].set_yticks(list(ypos.values()), [f"{TF_LABEL[tf]} · {e}" for tf, e in ypos])
    axes[0].set_ylim(-0.6, len(rows) - 0.4)
    x_sel = grid.loc[grid["config"] == sel, "media_neta"].iloc[0]
    y_sel = ypos[(grid.loc[grid["config"] == sel, "temporalidad"].iloc[0],
                  grid.loc[grid["config"] == sel, "entrada"].iloc[0])]
    axes[1].annotate("la elegida\n(la mejor de 96)", (x_sel, y_sel), xytext=(12, 16), textcoords="offset points",
                     fontsize=8.8, color=plots.INK_2, arrowprops=dict(arrowstyle="-", color=plots.INK_2, lw=0.8))
    fig.suptitle(title, x=0.015, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.015, 0.905, subtitle, color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.82, wspace=0.06, left=0.15, right=0.98, bottom=0.12)
    plots.save(fig, name)


def chart_costs() -> None:
    """15: qué parte del riesgo de cada operación se va en costes, por temporalidad y stop."""
    import matplotlib.pyplot as plt

    grid = pd.read_csv(RES / "desarrollo_rejilla.csv")
    g = grid.groupby(["temporalidad", "k"]).agg(costes_R=("costes_y_funding_R", "mean"),
                                                 stop=("distancia_stop", "mean")).reset_index()
    fig, ax = plt.subplots(figsize=(10, 5.2))
    width = 0.26
    for j, k in enumerate([1.0, 2.0, 3.0]):
        sub = g[g["k"] == k].set_index("temporalidad").loc[["15m", "1h"]]
        x = np.arange(2) + (j - 1) * (width + 0.03)
        ax.bar(x, sub["costes_R"], width=width, color=plots.SERIES[j], label=f"stop a {int(k)} ATR")
        for xi, (cr, st) in zip(x, zip(sub["costes_R"], sub["stop"])):
            ax.text(xi, cr + 0.008, f"{plots.num(cr * 100, 0)} %", ha="center", va="bottom", color=plots.INK,
                    fontsize=10, fontweight="bold")
            ax.text(xi, cr / 2, f"stop\n{plots.num(st * 100, 2)} %", ha="center", va="center", color="white",
                    fontsize=8.3)
    ax.set_xticks([0, 1], ["velas de 15 min", "velas de 1 hora"])
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    _plain_pct_axis(ax.yaxis)
    ax.set_ylabel("costes por operación, en % de lo que arriesga el stop")
    ax.legend(loc="upper right", ncol=3)
    ax.set_ylim(0, g["costes_R"].max() * 1.25)
    ax.set_title("En velas pequeñas, comisiones y deslizamiento se comen buena parte del riesgo", pad=26)
    plots.subtitle(ax, "Media de las operaciones de desarrollo. Dentro de cada barra: distancia media del stop "
                       "inicial. Ida y vuelta ≈ 0,12–0,14 % del precio")
    plots.save(fig, "15_intradia_costes.png")


def chart_breakeven() -> None:
    """16: qué hace el breakeven (motivos de salida) y si mejora la rentabilidad."""
    import matplotlib.pyplot as plt

    grid = pd.read_csv(RES / "desarrollo_rejilla.csv")
    sel = json.loads((RES / "veredicto.json").read_text())["seleccionada"]
    row = grid[grid["config"] == sel].iloc[0]
    fam = grid[(grid["temporalidad"] == row["temporalidad"]) & (grid["entrada"] == row["entrada"])
               & (grid["k"] == row["k"]) & (grid["salida"] == row["salida"])].sort_values("be_paso")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.6), gridspec_kw={"width_ratios": [1.2, 1]})
    # Izquierda: cómo terminan las operaciones con cada opción de breakeven
    y = np.arange(len(fam))[::-1]
    left = np.zeros(len(fam))
    reasons = [r for r in REASON_ORDER if fam[f"% {r}"].sum() > 0]
    for j, r in enumerate(reasons):
        v = fam[f"% {r}"].to_numpy()
        ax1.barh(y, v, left=left, height=0.6, color=plots.SERIES[REASON_ORDER.index(r)],
                 edgecolor=plots.SURFACE, linewidth=2, label=REASON_LABEL[r])
        for yi, li, vi in zip(y, left, v):
            if vi >= 0.07:
                ax1.text(li + vi / 2, yi, f"{plots.num(vi * 100, 0)} %", ha="center", va="center",
                         color="white", fontsize=8.8)
        left += v
    ax1.set_yticks(y, [b.replace("breakeven a ", "breakeven a ") for b in fam["breakeven"]])
    ax1.set_xlim(0, 1)
    _plain_pct_axis(ax1.xaxis)
    ax1.grid(visible=False)
    ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=len(reasons), fontsize=8.8,
               handlelength=1.2, columnspacing=1.0)
    ax1.set_title("Cómo terminan las operaciones (la elegida)", fontsize=11.5, pad=8)
    for yi, mn in zip(y, fam["media_neta"]):
        ax1.text(1.01, yi, _signed_pct(mn, 3), va="center",
                 color=plots.INK_2, fontsize=8.8, transform=ax1.get_yaxis_transform())
    ax1.text(1.01, len(fam) - 0.45, "media\nneta", va="bottom", color=plots.MUTED, fontsize=8,
             transform=ax1.get_yaxis_transform())
    # Derecha: cambio de la rentabilidad media al añadir el breakeven, en las 24 familias
    base = grid[grid["be_paso"] == 3].set_index(["temporalidad", "entrada", "k", "salida"])["media_neta"]
    rng = np.random.default_rng(1)
    labels = []
    for j, step in enumerate([0, 1, 2]):
        g = grid[grid["be_paso"] == step].set_index(["temporalidad", "entrada", "k", "salida"])["media_neta"]
        diff = (g - base.reindex(g.index)).to_numpy()
        yj = 2 - j
        ax2.scatter(diff, yj + rng.uniform(-0.15, 0.15, len(diff)), s=26, color=plots.SERIES[1],
                    edgecolors=plots.SURFACE, linewidths=0.8, zorder=3)
        ax2.plot([diff.mean()] * 2, [yj - 0.3, yj + 0.3], color=plots.INK, linewidth=2, zorder=4)
        better = int((diff > 0).sum())
        ax2.text(1.01, yj, f"mejora {better} de {len(diff)}", va="center", color=plots.INK_2, fontsize=8.8,
                 transform=ax2.get_yaxis_transform())
        labels.append(grid.loc[grid["be_paso"] == step, "breakeven"].iloc[0])
    from matplotlib.ticker import MultipleLocator

    ax2.axvline(0, color=plots.INK_2, linewidth=1)
    ax2.set_yticks([2, 1, 0], labels)
    ax2.set_ylim(-0.6, 2.6)
    ax2.grid(axis="y", visible=False)
    ax2.xaxis.set_major_locator(MultipleLocator(0.0003))
    _pct_axis(ax2, 2)
    ax2.set_xlabel("cambio de la rentabilidad media por operación\nfrente a no usar breakeven")
    ax2.set_title("¿Mejora la rentabilidad? (24 combinaciones)", fontsize=11.5, pad=8)
    fig.suptitle("El breakeven cambia cómo terminan las operaciones, pero no las hace rentables",
                 x=0.015, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.015, 0.905, "Desarrollo 2018–2023, BTC+ETH, sin apalancar. Raya negra: cambio medio",
             color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.82, wspace=0.72, left=0.12, right=0.87, bottom=0.2)
    plots.save(fig, "16_intradia_breakeven.png")


def chart_leverage() -> None:
    """17: capital de la configuración elegida con distintos apalancamientos."""
    import matplotlib.pyplot as plt

    curves = pd.read_csv(RES / "curvas.csv", index_col=0, parse_dates=True)
    floor = 1e-4
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.axvspan(pd.Timestamp("2024-01-01", tz="UTC"), curves.index[-1], color=plots.GRID, alpha=0.5, zorder=0)
    for j, col in enumerate(curves.columns):
        v = curves[col].clip(lower=floor)
        ax.plot(v.index, v, color=plots.SERIES[j], linewidth=1.8, label=col)
        below = curves[col] < 0.1
        if below.any():
            t = curves.index[below.argmax()]
            ax.scatter([t], [0.1], s=30, color=plots.SERIES[j], edgecolors=plots.SURFACE, zorder=4)
    ax.set_yscale("log")
    ax.set_ylim(floor * 0.8, 60)
    ticks = [10, 1, 0.1, 0.01, 0.001, 0.0001]
    ax.set_yticks(ticks, ["1.000 %", "100 %", "10 %", "1 %", "0,1 %", "0,01 %"])
    ax.minorticks_off()
    ax.axhline(0.5, color=plots.SERIES[7], linewidth=1, linestyle=(0, (4, 3)))
    ax.text(pd.Timestamp("2025-04-01", tz="UTC"), 0.58, "tu límite: −50 %", color=plots.INK_2, fontsize=9)
    ax.text(pd.Timestamp("2024-02-01", tz="UTC"), 3.2, "examen", color=plots.INK_2, fontsize=9)
    gone = curves["10x"] < floor
    if gone.any():
        t0 = curves.index[gone.argmax()]
        months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                  "octubre", "noviembre", "diciembre"]
        ax.annotate(f"10x: queda menos del 0,01 %\ndesde el {t0.day} de {months[t0.month - 1]} de {t0.year}",
                    (t0, floor), xytext=(16, 14), textcoords="offset points", fontsize=8.8, color=plots.INK_2,
                    va="bottom", arrowprops=dict(arrowstyle="-", color=plots.INK_2, lw=0.8))
    ax.set_ylabel("capital que queda (escala logarítmica)")
    ax.legend(loc="upper right", ncol=5, title=None)
    ax.set_title("Con rentabilidad negativa por operación, el apalancamiento solo acelera la pérdida", pad=26)
    plots.subtitle(ax, "Configuración elegida, BTC+ETH (50/50, reparto mensual), jun 2018 – oct 2026. "
                       "Punto: cuando el capital baja del 10 %")
    plots.save(fig, "17_intradia_apalancamiento.png")


def main() -> None:
    plots.setup()
    chart_entries_vs_random()
    chart_costs()
    chart_breakeven()
    chart_leverage()


if __name__ == "__main__":
    main()
