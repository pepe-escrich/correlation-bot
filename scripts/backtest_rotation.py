"""Fase 2 - Backtest de la rotación BTC <-> ETH (y otros pares) con comisiones.

Variantes probadas (todas sin mirar al futuro: se decide al cierre y se opera en la vela siguiente):
  * Regla literal por tiempo: tras una vela en la que BTC sube -> BTC; si baja -> ETH.
  * Regla por tramos: tras confirmarse una subida de X % de BTC -> BTC; tras bajada de X % -> ETH.
  * Las mismas reglas aplicadas directamente al ratio ETH/BTC, y su versión "al revés"
    (seguir la tendencia en vez de llevarle la contraria).
  * Referencias: HODL BTC, HODL ETH y cartera 50/50 con rebalanceo (bot de rebalanceo).

Uso: python scripts/backtest_rotation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot import plots  # noqa: E402
from corrbot.backtest import (  # noqa: E402
    NO_COSTS, Costs, random_timing_null, run_rebalance, run_switch, summarize,
    target_anchored_grid, target_time_rule, target_zigzag, walk_forward, yearly_vs_a,
)
from corrbot.data import load_closes  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
START = "2018-01-01"
BASE = Costs(fee=0.00075, slippage=0.0002)  # Binance con BNB + medio spread (~0,095 % por cambio)
COSTS = {
    "bruto (sin costes)": NO_COSTS,
    "0,05 % + spread (tipo Pionex)": Costs(fee=0.0005, slippage=0.0002),
    "0,075 % + spread (Binance+BNB)": BASE,
    "vía USDT (2 operaciones)": Costs(fee=0.00075, slippage=0.0002, trades_per_switch=2),
}
TIMEFRAMES = [("5m", None), ("15m", "15min"), ("1h", "1h"), ("4h", "4h"),
              ("12h", "12h"), ("1d", "1D"), ("3d", "3D"), ("1w", "7D")]
THRESHOLDS = [0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30]


def load_pair(a: str, b: str, interval: str, start: str = START) -> pd.DataFrame:
    df = load_closes([f"{a}USDT", f"{b}USDT"], interval, start=start).dropna()
    df.columns = ["A", "B"]
    return df


# ------------------------------------------------------------------ 1. regla literal
def time_rule() -> pd.DataFrame:
    m5 = load_pair("BTC", "ETH", "5m")
    rows = []
    for label, rule in TIMEFRAMES:
        p = m5 if rule is None else m5.resample(rule).last().dropna()
        btc_ret = p.A.pct_change().fillna(0).to_numpy()
        for contrarian in (True, False):
            tgt = target_time_rule(btc_ret, contrarian=contrarian)
            row = {"regla": "idea (tras subida -> BTC)" if contrarian else "al revés (tras subida -> ETH)",
                   "temporalidad": label}
            for name, costs in COSTS.items():
                row[name] = run_switch(p.A, p.B, tgt, costs).equity_in_a.iloc[-1]
            s = summarize(run_switch(p.A, p.B, tgt, BASE))
            row["cambios_por_año"] = s["cambios_por_año"]
            row["comisiones_por_año_%capital"] = s["cambios_por_año"] * BASE.per_switch * 100
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "bt_regla_temporal.csv", index=False, float_format="%.4g")
    return out


# --------------------------------------------------------------- 2. reglas por umbral
def threshold_rules(h: pd.DataFrame) -> pd.DataFrame:
    ratio, btc = (h.B / h.A).to_numpy(), h.A.to_numpy()
    families = [("tramos de BTC", target_zigzag, btc), ("tramos del ratio", target_zigzag, ratio),
                ("grid del ratio", target_anchored_grid, ratio)]
    rows = []
    for family, fn, signal in families:
        for thr in THRESHOLDS:
            for contrarian in (True, False):
                tgt = fn(signal, thr, contrarian=contrarian)
                gross = run_switch(h.A, h.B, tgt, NO_COSTS)
                net = run_switch(h.A, h.B, tgt, BASE)
                s = summarize(net)
                rows.append({"familia": family, "umbral": thr,
                             "regla": "idea (contraria)" if contrarian else "al revés (tendencia)",
                             "bruto_vs_HODL_BTC": gross.equity_in_a.iloc[-1],
                             "neto_vs_HODL_BTC": net.equity_in_a.iloc[-1],
                             "multiplicador_usd": s["multiplicador"], "max_drawdown_usd": s["max_drawdown"],
                             "cambios_por_año": s["cambios_por_año"], "tiempo_en_ETH": s["tiempo_en_b"]})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "bt_reglas_umbral.csv", index=False, float_format="%.4g")
    return out


def benchmarks(h: pd.DataFrame) -> dict[str, pd.DataFrame]:
    res = {
        "HODL BTC": run_switch(h.A, h.B, np.zeros(len(h)), BASE),
        "HODL ETH": run_switch(h.A, h.B, np.ones(len(h)), BASE),
        "50/50 sin rebalancear": run_rebalance(h.A, h.B, 0.5, NO_COSTS),
        "50/50 rebalanceo banda 5 %": run_rebalance(h.A, h.B, 0.5, BASE, band=0.05),
        "50/50 rebalanceo banda 10 %": run_rebalance(h.A, h.B, 0.5, BASE, band=0.10),
    }
    pd.DataFrame([summarize(v, k) for k, v in res.items()]).to_csv(
        RESULTS / "bt_referencias.csv", index=False, float_format="%.4g")
    return res


# ------------------------------------------------------------- 3. robustez
def key_strategies(h: pd.DataFrame, d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ratio, btc = (h.B / h.A).to_numpy(), h.A.to_numpy()
    return {
        "Idea: rotación diaria": run_switch(d.A, d.B, target_time_rule(d.A.pct_change().fillna(0).to_numpy()), BASE),
        "Idea: tramos de BTC del 5 %": run_switch(h.A, h.B, target_zigzag(btc, 0.05, True), BASE),
        "Al revés: tendencia del ratio 5 %": run_switch(h.A, h.B, target_zigzag(ratio, 0.05, False), BASE),
        "Al revés: tendencia del ratio 10 %": run_switch(h.A, h.B, target_zigzag(ratio, 0.10, False), BASE),
        "Al revés: tendencia del ratio 15 %": run_switch(h.A, h.B, target_zigzag(ratio, 0.15, False), BASE),
        "Rebalanceo 50/50 (banda 10 %)": run_rebalance(h.A, h.B, 0.5, BASE, band=0.10),
        "HODL ETH": run_switch(h.A, h.B, np.ones(len(h)), BASE),
    }


def robustness(h: pd.DataFrame, key: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    yearly = pd.DataFrame({k: yearly_vs_a(v) for k, v in key.items()})
    yearly.index.name = "año"
    yearly.to_csv(RESULTS / "bt_por_anio.csv", float_format="%.4g")

    rows = []
    for start in ["2018-01-01", "2019-01-01", "2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]:
        hh = h[h.index >= pd.Timestamp(start, tz="UTC")]
        ratio, btc = (hh.B / hh.A).to_numpy(), hh.A.to_numpy()
        dd = hh.resample("1D").last().dropna()
        row = {"inicio": start, "ETH/BTC (variación del ratio)": ratio[-1] / ratio[0]}
        row["Idea: rotación diaria"] = run_switch(dd.A, dd.B, target_time_rule(dd.A.pct_change().fillna(0).to_numpy()), BASE).equity_in_a.iloc[-1]
        row["Idea: tramos de BTC del 5 %"] = run_switch(hh.A, hh.B, target_zigzag(btc, 0.05, True), BASE).equity_in_a.iloc[-1]
        for thr in (0.05, 0.10, 0.15):
            row[f"Al revés: tendencia del ratio {thr:.0%}"] = run_switch(hh.A, hh.B, target_zigzag(ratio, thr, False), BASE).equity_in_a.iloc[-1]
        row["Rebalanceo 50/50 (banda 10 %)"] = run_rebalance(hh.A, hh.B, 0.5, BASE, band=0.10).equity_in_a.iloc[-1]
        rows.append(row)
    by_start = pd.DataFrame(rows)
    by_start.to_csv(RESULTS / "bt_fecha_inicio.csv", index=False, float_format="%.4g")
    return yearly, by_start


def random_null(h: pd.DataFrame) -> pd.DataFrame:
    ratio, btc = (h.B / h.A).to_numpy(), h.A.to_numpy()
    cases = {
        "Idea: tramos de BTC del 5 %": target_zigzag(btc, 0.05, True),
        "Al revés: tendencia del ratio 5 %": target_zigzag(ratio, 0.05, False),
        "Al revés: tendencia del ratio 10 %": target_zigzag(ratio, 0.10, False),
        "Al revés: tendencia del ratio 15 %": target_zigzag(ratio, 0.15, False),
    }
    rows = []
    for name, tgt in cases.items():
        sims = random_timing_null(h.A, h.B, tgt, n_sims=2000, seed=1)
        real = run_switch(h.A, h.B, tgt, NO_COSTS).equity_in_a.iloc[-1]
        rows.append({"estrategia": name, "real_bruto_vs_BTC": real, "azar_mediana": np.median(sims),
                     "azar_p95": np.quantile(sims, 0.95), "percentil_vs_azar": np.mean(sims < real)})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "bt_test_azar.csv", index=False, float_format="%.4g")
    return out


def walk_forward_selection(h: pd.DataFrame, bench: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ratio, btc = (h.B / h.A).to_numpy(), h.A.to_numpy()
    curves = {}
    for thr in [0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30]:
        for contrarian in (True, False):
            tag = "idea" if contrarian else "al revés"
            curves[f"tramos BTC {thr:.1%} ({tag})"] = run_switch(h.A, h.B, target_zigzag(btc, thr, contrarian), BASE).equity_in_a
            curves[f"tramos ratio {thr:.1%} ({tag})"] = run_switch(h.A, h.B, target_zigzag(ratio, thr, contrarian), BASE).equity_in_a
    curves["HODL BTC"] = bench["HODL BTC"].equity_in_a
    curves["HODL ETH"] = bench["HODL ETH"].equity_in_a
    curves["Rebalanceo 50/50"] = bench["50/50 rebalanceo banda 10 %"].equity_in_a
    wf = walk_forward(curves, train_years=2, first_test_year=2020)
    wf.to_csv(RESULTS / "bt_walk_forward.csv", index=False, float_format="%.4g")
    return wf


# ------------------------------------------------------------------ 4. otros pares
PAIRS = [("BTC", "ETH"), ("BTC", "SOL"), ("ETH", "SOL"), ("BTC", "BNB"), ("BTC", "XRP"), ("BTC", "DOGE"),
         ("BTC", "LTC"), ("BTC", "LINK"), ("ETH", "LINK"), ("XRP", "ADA"), ("BTC", "BCH"), ("BTC", "ADA")]
DIRECT_PAIRS = {"ETHBTC", "SOLBTC", "SOLETH", "BNBBTC", "XRPBTC", "DOGEBTC", "LTCBTC", "LINKBTC",
                "LINKETH", "ADABTC", "BCHBTC"}


def other_pairs(start: str = "2021-01-01") -> pd.DataFrame:
    rows = []
    for a, b in PAIRS:
        h = load_pair(a, b, "1h", start=start)
        costs = Costs(fee=BASE.fee, slippage=BASE.slippage,
                      trades_per_switch=1 if f"{b}{a}" in DIRECT_PAIRS else 2)
        ratio, pa = (h.B / h.A).to_numpy(), h.A.to_numpy()
        d = h.resample("1D").last().dropna()
        rebal = run_rebalance(h.A, h.B, 0.5, costs, band=0.10).equity_in_a.iloc[-1]
        row = {"par (B/A)": f"{b}/{a}", "variación B/A": ratio[-1] / ratio[0],
               "Rebalanceo 50/50": rebal,
               "Idea: rotación diaria": run_switch(d.A, d.B, target_time_rule(d.A.pct_change().fillna(0).to_numpy()), costs).equity_in_a.iloc[-1],
               "Idea: tramos de A del 5 %": run_switch(h.A, h.B, target_zigzag(pa, 0.05, True), costs).equity_in_a.iloc[-1],
               "Idea: tramos de A del 10 %": run_switch(h.A, h.B, target_zigzag(pa, 0.10, True), costs).equity_in_a.iloc[-1],
               "Al revés: tendencia ratio 10 %": run_switch(h.A, h.B, target_zigzag(ratio, 0.10, False), costs).equity_in_a.iloc[-1],
               "Al revés: tendencia ratio 15 %": run_switch(h.A, h.B, target_zigzag(ratio, 0.15, False), costs).equity_in_a.iloc[-1],
               "operaciones por cambio": costs.trades_per_switch}
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "bt_otros_pares.csv", index=False, float_format="%.4g")
    return out


# ------------------------------------------------------------------------ gráficos
def chart_curves(key: dict[str, pd.DataFrame]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    order = ["Idea: rotación diaria", "Idea: tramos de BTC del 5 %", "Al revés: tendencia del ratio 10 %",
             "Rebalanceo 50/50 (banda 10 %)", "HODL ETH"]
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.axhline(1.0, color=plots.MUTED, linewidth=1.2, label="HODL BTC (no hacer nada) = ×1")
    ends = []
    for i, name in enumerate(order):
        s = key[name].equity_in_a.resample("1D").last()
        ax.plot(s.index, s.values, color=plots.SERIES[i], linewidth=1.8, label=name)
        ends.append([s.iloc[-1], i, s.index[-1]])
    ax.set_yscale("log")
    ticks = [0.1, 0.2, 0.5, 1, 2, 5]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "×" + f"{v:g}".replace(".", ",")))
    ax.set_ylim(0.08, 7)
    # Etiquetas finales sin solaparse: separación mínima en escala log y línea guía.
    ends.sort(key=lambda e: e[0])
    label_y = [e[0] for e in ends]
    min_gap = 10 ** 0.07
    for k in range(1, len(label_y)):
        label_y[k] = max(label_y[k], label_y[k - 1] * min_gap)
    for (value, i, t), y in zip(ends, label_y):
        ax.plot([t], [value], "o", color=plots.SERIES[i], markersize=6, markeredgecolor=plots.SURFACE, markeredgewidth=2)
        ax.annotate("×" + plots.num(value, 2), (t, value), xytext=(t + pd.Timedelta(days=75), y),
                    textcoords="data", va="center", color=plots.INK_2, fontsize=9,
                    arrowprops={"arrowstyle": "-", "color": plots.AXIS, "linewidth": 0.8,
                                "shrinkA": 4, "shrinkB": 2})
    ax.legend(loc="upper left", fontsize=9.5, ncol=1)
    ax.set_title("Medido en BTC: la idea pierde; seguir la tendencia solo funcionó hasta 2021", pad=26)
    plots.subtitle(ax, "BTC que tendrías por cada BTC inicial (×1 = igual que holdear BTC). Neto de comisiones, 2018–2026")
    ax.set_xlim(right=ax.get_xlim()[1] + 260)
    plots.save(fig, "05_curvas_en_btc.png")


def chart_yearly(yearly: pd.DataFrame, last_date: pd.Timestamp) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, LogNorm

    data = yearly.T
    cmap = LinearSegmentedColormap.from_list("div", plots.DIVERGING[::-1])
    fig, ax = plt.subplots(figsize=(10.5, 4.4))
    norm = LogNorm(vmin=1 / 3, vmax=3)
    ax.imshow(np.clip(data.values, 1 / 3, 3), cmap=cmap, norm=norm, aspect="auto")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data.values[i, j]
            dark = v > 2.0 or v < 0.5
            ax.text(j, i, plots.num(v, 2), ha="center", va="center", fontsize=9,
                    color="#ffffff" if dark else plots.INK)
    partial = last_date.month < 12 or last_date.day < 31
    labels = [f"{c}*" if partial and c == last_date.year else str(c) for c in data.columns]
    ax.set_xticks(range(data.shape[1]), labels)
    ax.set_yticks(range(data.shape[0]), data.index)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    ax.set_xticks(np.arange(-0.5, data.shape[1]), minor=True)
    ax.set_yticks(np.arange(-0.5, data.shape[0]), minor=True)
    ax.grid(which="minor", color=plots.SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("Año a año frente a holdear BTC: desde 2022 casi todo pierde", pad=26)
    note = f"  *{last_date.year} hasta {plots.MESES[last_date.month - 1]}" if partial else ""
    plots.subtitle(ax, "Azul = más BTC que holdeando BTC ese año; rojo = menos.  1,10 = +10 % de BTC." + note)
    plots.save(fig, "06_mapa_anual.png")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    plots.setup()
    h = load_pair("BTC", "ETH", "1h")
    d = h.resample("1D").last().dropna()
    print("1/6 regla literal por temporalidad...", flush=True)
    tr = time_rule()
    print(tr[["regla", "temporalidad", "bruto (sin costes)", "0,075 % + spread (Binance+BNB)", "cambios_por_año"]].to_string(index=False))
    print("2/6 reglas por umbral...", flush=True)
    threshold_rules(h)
    bench = benchmarks(h)
    print("3/6 robustez (por año, fecha de inicio)...", flush=True)
    key = key_strategies(h, d)
    yearly, by_start = robustness(h, key)
    print(yearly.round(2).to_string())
    print(by_start.round(2).to_string(index=False))
    print("4/6 test de azar...", flush=True)
    print(random_null(h).round(3).to_string(index=False))
    print("5/6 walk-forward...", flush=True)
    wf = walk_forward_selection(h, bench)
    print(wf.round(2).to_string(index=False))
    print("6/6 otros pares...", flush=True)
    print(other_pairs().round(2).to_string(index=False))
    chart_curves(key)
    chart_yearly(yearly, h.index[-1])
    print("OK: resultados en results/ y gráficos en docs/img/")


if __name__ == "__main__":
    main()
