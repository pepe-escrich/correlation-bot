"""EXAMEN FINAL (2025-01-01 → último dato) de la estrategia A + B con la configuración
congelada en el protocolo pre-registrado. Se ejecuta una sola vez.

Uso: python scripts/final_exam.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corrbot import plots  # noqa: E402
from corrbot.dips import dip_trades, daily_returns, trade_stats  # noqa: E402
from corrbot.trend import perf  # noqa: E402
from validate_a import (  # noqa: E402
    OTHER_TOKENS, daily_close, dev_window, hodl_ret, portfolio, run_a, sl, verdict,
)
from validate_b import A_PRIORI, COSTS, DEV_START, bars, exposure, funding, in_period  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "validacion"
EXAM_START = pd.Timestamp("2025-01-01", tz="UTC")
DEV_END = pd.Timestamp("2024-12-31", tz="UTC")


def exam_a(btc: pd.Series, eth: pd.Series) -> tuple[pd.DataFrame, bool, dict]:
    end = min(btc.index[-1], eth.index[-1])
    r = {"A BTC": sl(run_a(btc)["ret"], EXAM_START, end), "HODL BTC": sl(hodl_ret(btc), EXAM_START, end),
         "A ETH": sl(run_a(eth)["ret"], EXAM_START, end), "HODL ETH": sl(hodl_ret(eth), EXAM_START, end)}
    r["A 50/50"] = portfolio([r["A BTC"], r["A ETH"]])
    r["HODL 50/50"] = portfolio([r["HODL BTC"], r["HODL ETH"]])
    tab = pd.DataFrame({k: perf(v) for k, v in r.items()}).T
    a, h = tab.loc["A 50/50"], tab.loc["HODL 50/50"]
    ok = a["max_caida"] >= -0.50 and a["max_caida"] >= h["max_caida"] and a["sharpe"] >= h["sharpe"] - 0.3
    return tab, ok, r


def exam_b() -> tuple[pd.DataFrame, bool, dict]:
    trades = {t: dip_trades(bars(t), exposure(t), A_PRIORI, COSTS, funding(t)) for t in ["BTC", "ETH"]}
    exam = pd.concat([in_period(tr, EXAM_START, pd.Timestamp("2100-01-01", tz="UTC")) for tr in trades.values()])
    yrs = (exam["salida"].max() - EXAM_START).days / 365.25 if len(exam) else 1.0
    st = trade_stats(exam, yrs) if len(exam) else {"operaciones_año": 0}
    st["neto_total"] = exam["neto"].sum() if len(exam) else 0.0
    ok = st["neto_total"] > 0
    return pd.DataFrame([st]), ok, trades


def combined(r_a: dict, trades_b: dict, start, end) -> pd.DataFrame:
    """Cartera 80 % A (40 % BTC + 40 % ETH) + 20 % B (10 % por activo), sin reequilibrar."""
    idx = sl(r_a["A BTC"], start, end).index
    rb = {t: daily_returns(in_period(tr, start, end + pd.Timedelta(days=1)), idx) for t, tr in trades_b.items()}
    parts = [sl(r_a["A BTC"], start, end), sl(r_a["A ETH"], start, end), rb["BTC"], rb["ETH"]]
    weights = [0.4, 0.4, 0.1, 0.1]
    eq = sum(w * (1 + p).cumprod() for w, p in zip(weights, parts))
    ret = eq.pct_change().fillna(eq.iloc[0] - 1)
    hodl = portfolio([sl(r_a["HODL BTC"], start, end), sl(r_a["HODL ETH"], start, end)])
    return pd.DataFrame({"A+B (80/20)": perf(ret), "Solo A": perf(portfolio(parts[:2])),
                         "HODL 50/50": perf(hodl)}).T


def chart_equity(btc: pd.Series, eth: pd.Series) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    start = max(dev_window(btc)[0], dev_window(eth)[0])
    end = min(btc.index[-1], eth.index[-1])
    a = portfolio([sl(run_a(btc)["ret"], start, end), sl(run_a(eth)["ret"], start, end)])
    h = portfolio([sl(hodl_ret(btc), start, end), sl(hodl_ret(eth), start, end)])
    eq_a, eq_h = (1 + a).cumprod(), (1 + h).cumprod()
    dd_a, dd_h = eq_a / eq_a.cummax() - 1, eq_h / eq_h.cummax() - 1
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10.5, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    for ax in (a1, a2):
        ax.axvspan(EXAM_START, end, color="#f0efec", zorder=0)
    a1.plot(eq_h.index, eq_h.values, color=plots.MUTED, linewidth=1.6, label="Mantener 50/50 BTC-ETH (HODL)")
    a1.plot(eq_a.index, eq_a.values, color=plots.SERIES[0], linewidth=2, label="Estrategia A (tendencia + tamaño por volatilidad)")
    a1.set_yscale("log")
    ticks = [0.2, 0.5, 1, 2, 5, 10, 20]
    a1.yaxis.set_major_locator(FixedLocator(ticks))
    a1.yaxis.set_minor_locator(NullLocator())
    a1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "×" + f"{v:g}".replace(".", ",")))
    for eq, color in [(eq_a, plots.SERIES[0]), (eq_h, plots.MUTED)]:
        a1.annotate("×" + plots.num(eq.iloc[-1], 1), (eq.index[-1], eq.iloc[-1]), textcoords="offset points",
                    xytext=(6, -3), color=plots.INK_2, fontsize=9)
    a1.text(EXAM_START + pd.Timedelta(days=12), 0.3, "examen final:\nestos datos no se\nusaron para diseñar",
            color=plots.INK_2, fontsize=9, va="center")
    a1.legend(loc="upper left", fontsize=9.5)
    a1.set_title("Estrategia A: crece más que mantener y con caídas mucho menores", pad=26)
    plots.subtitle(a1, "Multiplicador del capital (escala log), medido en dólares y neto de comisiones. Mar 2018 – oct 2026")
    a2.fill_between(dd_h.index, dd_h.values, 0, color=plots.MUTED, alpha=0.25, linewidth=0)
    a2.plot(dd_h.index, dd_h.values, color=plots.MUTED, linewidth=1.2)
    a2.plot(dd_a.index, dd_a.values, color=plots.SERIES[0], linewidth=1.6)
    a2.axhline(-0.5, color=plots.SERIES[7], linewidth=1)
    a2.text(pd.Timestamp("2023-11-01", tz="UTC"), -0.53, "tu límite: −50 %", color=plots.INK_2, fontsize=9, va="top")
    a2.set_ylim(-0.95, 0.02)
    plots.es_axis(a2.yaxis, percent=True)
    plots.subtitle(a2, "Caída desde el máximo anterior")
    fig.subplots_adjust(hspace=0.28)
    plots.save(fig, "07_estrategia_A.png")


def chart_tokens() -> None:
    import matplotlib.pyplot as plt

    toks = pd.read_csv(OUT / "A_c4_otros_tokens.csv")
    c1 = pd.read_csv(OUT / "A_c1_desarrollo.csv", index_col=0)
    extra = pd.DataFrame([
        {"token": "BTC", "sharpe_A": c1.loc["A BTC", "sharpe"], "sharpe_HODL": c1.loc["HODL BTC", "sharpe"],
         "caida_A": c1.loc["A BTC", "max_caida"], "caida_HODL": c1.loc["HODL BTC", "max_caida"]},
        {"token": "ETH", "sharpe_A": c1.loc["A ETH", "sharpe"], "sharpe_HODL": c1.loc["HODL ETH", "sharpe"],
         "caida_A": c1.loc["A ETH", "max_caida"], "caida_HODL": c1.loc["HODL ETH", "max_caida"]}])
    t = pd.concat([extra, toks[extra.columns]]).sort_values("caida_HODL").reset_index(drop=True)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 6.6), sharey=True)
    y = np.arange(len(t))
    for ax, col_a, col_h, title in [(a1, "caida_A", "caida_HODL", "Caída máxima"),
                                    (a2, "sharpe_A", "sharpe_HODL", "Sharpe (rentabilidad por unidad de riesgo)")]:
        ax.hlines(y, t[col_h], t[col_a], color=plots.AXIS, linewidth=1.2)
        ax.plot(t[col_h], y, "o", color=plots.MUTED, markersize=6, label="Mantener (HODL)")
        ax.plot(t[col_a], y, "o", color=plots.SERIES[0], markersize=6, label="Estrategia A")
        ax.set_title(title, fontsize=11, pad=8)
        ax.grid(axis="y", visible=False)
    plots.es_axis(a1.xaxis, percent=True)
    plots.es_axis(a2.xaxis, 1)
    a1.set_yticks(y, t["token"])
    handles, labels = a2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.98, 0.955), ncol=2, fontsize=9.5)
    better = (t.sharpe_A > t.sharpe_HODL).sum()
    fig.suptitle(f"En los 20 tokens la caída máxima baja; el Sharpe solo mejora en {better} de 20",
                 x=0.06, ha="left", fontsize=13, fontweight="bold", color=plots.INK)
    fig.text(0.06, 0.925, "Periodo de desarrollo (hasta dic 2024), misma configuración en todos los tokens",
             color=plots.INK_2, fontsize=9.5)
    fig.subplots_adjust(top=0.86, wspace=0.08)
    plots.save(fig, "08_A_por_token.png")


def main() -> None:
    plots.setup()
    btc, eth = daily_close("BTC"), daily_close("ETH")
    tab_a, ok_a6, r_a_exam = exam_a(btc, eth)
    tab_a.to_csv(OUT / "examen_A.csv", float_format="%.4f")
    print("EXAMEN FINAL A (2025-01-01 → último dato):")
    print(tab_a.round(3).to_string())
    print(f"Criterio 6 de A: {verdict(ok_a6)}\n")

    tab_b, ok_b5, trades_b = exam_b()
    tab_b.to_csv(OUT / "examen_B.csv", index=False, float_format="%.5f")
    print("EXAMEN FINAL B:")
    print(tab_b.round(4).to_string(index=False))
    print(f"Criterio 5 de B: {verdict(ok_b5)}\n")

    # Cartera combinada (informativo), desarrollo y examen
    end = min(btc.index[-1], eth.index[-1])
    full = {"A BTC": run_a(btc)["ret"], "A ETH": run_a(eth)["ret"], "HODL BTC": hodl_ret(btc), "HODL ETH": hodl_ret(eth)}
    comb_dev = combined(full, trades_b, DEV_START, DEV_END)
    comb_exam = combined(full, trades_b, EXAM_START, end)
    comb_dev.to_csv(OUT / "combinada_desarrollo.csv", float_format="%.4f")
    comb_exam.to_csv(OUT / "combinada_examen.csv", float_format="%.4f")
    print("Cartera combinada (informativo) - desarrollo:\n", comb_dev.round(3).to_string())
    print("Cartera combinada (informativo) - examen:\n", comb_exam.round(3).to_string())

    chart_equity(btc, eth)
    chart_tokens()
    pd.DataFrame({"criterio": ["A6 examen final", "B5 examen final"],
                  "resultado": [verdict(ok_a6), verdict(ok_b5)]}).to_csv(OUT / "examen_resumen.csv", index=False)


if __name__ == "__main__":
    main()
