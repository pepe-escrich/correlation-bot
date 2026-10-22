"""Fase 1 - Análisis exploratorio: ¿se cumplen las premisas de la idea?

1. ¿Qué pares de tokens sólidos están más correlacionados?
2. ¿ETH amplifica de verdad los movimientos de BTC (beta, tramos)?
3. ¿Es predecible el siguiente tramo? (lo que la regla necesita)
4. ¿Están cointegrados (el ratio vuelve a una media)?

Uso: python scripts/explore.py   (requiere haber ejecutado scripts/download_data.py)
Genera CSV en results/ y gráficos en docs/img/.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot import plots  # noqa: E402
from corrbot.data import load_closes  # noqa: E402
from corrbot.stats import (  # noqa: E402
    dual_beta, engle_granger_pvalue, half_life, lag1_autocorr, legs_table, log_returns,
    ols_beta, variance_ratio, zigzag,
)
from download_data import UNIVERSE  # noqa: E402

warnings.filterwarnings("ignore")
RESULTS = Path(__file__).resolve().parent.parent / "results"
START = "2018-01-01"
COST_PER_SWITCH = 0.001  # 0,1 % por cambio de posición (referencia para comparar)


def correlations() -> None:
    d = load_closes([f"{t}USDT" for t in UNIVERSE], "1d")
    d.columns = UNIVERSE
    r = log_returns(d)
    last2y = r[r.index >= r.index[-1] - pd.Timedelta(days=730)]
    corr = last2y.corr()
    corr.round(3).to_csv(RESULTS / "correlacion_diaria_2anios.csv")
    rows = []
    for i, a in enumerate(UNIVERSE):
        for b in UNIVERSE[i + 1:]:
            roll = r[a].rolling(90).corr(r[b])
            roll = roll[roll.index >= "2021-01-01"]
            rows.append({"par": f"{a}-{b}", "corr_2a": corr.loc[a, b],
                         "corr_90d_min_desde_2021": roll.min(), "corr_90d_mediana": roll.median()})
    pairs = pd.DataFrame(rows).sort_values("corr_2a", ascending=False)
    pairs.head(20).round(3).to_csv(RESULTS / "pares_mas_correlados.csv", index=False)
    vs_btc = pd.DataFrame({t: {
        "corr_btc_2a": corr.loc["BTC", t],
        "beta_btc_2a": ols_beta(last2y[t].to_numpy(), last2y["BTC"].to_numpy())["beta"],
        "vol_anual_2a": last2y[t].std() * np.sqrt(365),
    } for t in UNIVERSE}).T.sort_values("corr_btc_2a", ascending=False)
    vs_btc.round(3).to_csv(RESULTS / "tokens_vs_btc.csv")
    print("Top 5 pares:", pairs.head(5)[["par", "corr_2a"]].to_dict("records"))


def eth_btc_profile(d: pd.DataFrame) -> pd.DataFrame:
    r = log_returns(d[["BTC", "ETH"]]).dropna()
    rows = []
    for year, rr in r.groupby(r.index.year):
        b = ols_beta(rr.ETH.to_numpy(), rr.BTC.to_numpy())
        db = dual_beta(rr.ETH.to_numpy(), rr.BTC.to_numpy())
        g = d[d.index.year == year]
        rows.append({"año": year, "ETH/BTC_inicio": g.R.iloc[0], "ETH/BTC_fin": g.R.iloc[-1],
                     "variacion_ratio": g.R.iloc[-1] / g.R.iloc[0] - 1, "correlacion": b["corr"],
                     "beta": b["beta"], "beta_subidas": db["beta_up"], "beta_bajadas": db["beta_down"],
                     "vol_BTC": rr.BTC.std() * np.sqrt(365), "vol_ETH": rr.ETH.std() * np.sqrt(365),
                     "vol_ratio": (rr.ETH - rr.BTC).std() * np.sqrt(365)})
    b = ols_beta(r.ETH.to_numpy(), r.BTC.to_numpy())
    db = dual_beta(r.ETH.to_numpy(), r.BTC.to_numpy())
    rows.append({"año": "total", "ETH/BTC_inicio": d.R.iloc[0], "ETH/BTC_fin": d.R.iloc[-1],
                 "variacion_ratio": d.R.iloc[-1] / d.R.iloc[0] - 1, "correlacion": b["corr"],
                 "beta": b["beta"], "beta_subidas": db["beta_up"], "beta_bajadas": db["beta_down"],
                 "vol_BTC": r.BTC.std() * np.sqrt(365), "vol_ETH": r.ETH.std() * np.sqrt(365),
                 "vol_ratio": (r.ETH - r.BTC).std() * np.sqrt(365)})
    out = pd.DataFrame(rows)
    out.round(4).to_csv(RESULTS / "eth_btc_por_anio.csv", index=False)
    print(f"Beta subidas {db['beta_up']:.2f} vs bajadas {db['beta_down']:.2f} (t dif {db['t_diff']:.1f})")
    return r


def legs(h: pd.DataFrame) -> pd.DataFrame:
    rows, legs5 = [], None
    for thr in [0.02, 0.05, 0.10, 0.20]:
        L = legs_table(zigzag(h.BTC.to_numpy(), thr), h.BTC.to_numpy(), h.ETH.to_numpy(), h.index)
        if thr == 0.05:
            legs5 = L
        for direction, g in L.groupby("direction"):
            eth_wins = (g.pct_b > g.pct_a) if direction == "subida" else (g.pct_b < g.pct_a)
            rows.append({"umbral": thr, "tramo": direction, "n": len(g),
                         "duracion_mediana_h": g.bars.median(),
                         "BTC_mediana": g.pct_a.median(), "ETH_mediana": g.pct_b.median(),
                         "amplificacion_mediana": g.amplification.median(),
                         "pct_tramos_donde_ETH_amplifica": eth_wins.mean()})
    pd.DataFrame(rows).round(4).to_csv(RESULTS / "tramos_zigzag.csv", index=False)
    return legs5


def predictability(m5: pd.DataFrame) -> pd.DataFrame:
    """Ventaja de la regla "tras subida -> BTC, tras bajada -> ETH" en la siguiente vela."""
    rows = []
    for label, rule in [("5m", None), ("15m", "15min"), ("1h", "1h"), ("4h", "4h"),
                        ("12h", "12h"), ("1d", "1D"), ("3d", "3D"), ("1w", "7D")]:
        p = m5 if rule is None else m5.resample(rule).last().dropna()
        lr = np.log(p).diff().dropna()
        rel = lr.ETH - lr.BTC
        df = pd.DataFrame({"btc": lr.BTC, "nxt": rel.shift(-1)}).dropna()
        up, down = df[df.btc > 0].nxt, df[df.btc < 0].nxt
        edge = (down.mean() - up.mean()) / 2
        se = np.sqrt(up.var() / len(up) + down.var() / len(down)) / 2
        p_switch = np.mean(np.sign(df.btc).diff().abs() > 0)
        rows.append({"temporalidad": label, "velas": len(df),
                     "ratio_siguiente_tras_bajada_pb": down.mean() * 1e4,
                     "ratio_siguiente_tras_subida_pb": up.mean() * 1e4,
                     "ventaja_por_vela_pb": edge * 1e4, "t_ventaja": edge / se,
                     "prob_cambio": p_switch, "coste_por_vela_pb": p_switch * COST_PER_SWITCH * 1e4,
                     "autocorr_ratio": lag1_autocorr(rel)[0]})
    out = pd.DataFrame(rows)
    out.round(4).to_csv(RESULTS / "predictibilidad.csv", index=False)
    return out


def variance_ratios(h: pd.DataFrame) -> None:
    l_ratio = np.log(h.ETH / h.BTC).to_numpy()
    l_btc = np.log(h.BTC).to_numpy()
    rows = []
    for q in [2, 4, 12, 24, 72, 168, 336, 720]:
        vr_r, z_r = variance_ratio(l_ratio, q)
        vr_b, z_b = variance_ratio(l_btc, q)
        rows.append({"horizonte_h": q, "VR_ratio_ETHBTC": vr_r, "z_ratio": z_r, "VR_BTC": vr_b, "z_BTC": z_b})
    pd.DataFrame(rows).round(3).to_csv(RESULTS / "variance_ratio.csv", index=False)


def cointegration(d: pd.DataFrame) -> None:
    rows = []
    for win in [90, 180, 365]:
        pvals, hls = [], []
        for end in pd.date_range(pd.Timestamp("2019-01-01", tz="UTC"), d.index[-1], freq="30D"):
            w = d[(d.index > end - pd.Timedelta(days=win)) & (d.index <= end)]
            if len(w) < win * 0.9:
                continue
            pvals.append(engle_granger_pvalue(np.log(w.ETH), np.log(w.BTC)))
            beta = np.polyfit(np.log(w.BTC), np.log(w.ETH), 1)[0]
            hls.append(half_life(np.log(w.ETH) - beta * np.log(w.BTC)))
        hls = np.array(hls)
        rows.append({"ventana_dias": win, "ventanas": len(pvals),
                     "pct_cointegradas_5pct": np.mean(np.array(pvals) < 0.05),
                     "vida_media_mediana_dias": np.median(hls[np.isfinite(hls)])})
    pd.DataFrame(rows).round(3).to_csv(RESULTS / "cointegracion.csv", index=False)


# -------------------------------------------------------------------- gráficos
def chart_ratio(d_full: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    R = d_full["ETHBTC"].dropna()
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(R.index, R.values, color=plots.SERIES[0], linewidth=1.8)
    ax.set_yscale("log")
    ticks = [0.015, 0.02, 0.03, 0.05, 0.08, 0.12]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
    ax.set_ylim(0.014, 0.13)
    marks = [("2018-01-01", "2018-06-30", "max"), ("2019-01-01", "2019-12-31", "min"),
             ("2021-06-01", "2022-12-31", "max"), ("2025-01-01", "2025-06-30", "min")]
    for a, b, kind in marks:
        seg = R[(R.index >= pd.Timestamp(a, tz="UTC")) & (R.index <= pd.Timestamp(b, tz="UTC"))]
        t = seg.idxmax() if kind == "max" else seg.idxmin()
        v = seg.loc[t]
        ax.plot([t], [v], "o", color=plots.SERIES[0], markersize=6, markeredgecolor=plots.SURFACE, markeredgewidth=2)
        ax.annotate(f"{plots.num(v, 3)}\n{plots.mes(t)}", (t, v), textcoords="offset points",
                    xytext=(8, 4 if kind == "max" else -22), color=plots.INK_2, fontsize=9)
    t, v = R.index[-1], R.iloc[-1]
    ax.plot([t], [v], "o", color=plots.SERIES[0], markersize=6, markeredgecolor=plots.SURFACE, markeredgewidth=2)
    ax.annotate(f"hoy\n{plots.num(v, 3)}", (t, v), textcoords="offset points", xytext=(-6, -32), color=plots.INK, fontsize=9.5)
    ax.set_title("ETH/BTC no vuelve a una media fija: se mueve por tendencias largas", pad=26)
    plots.subtitle(ax, "Precio de 1 ETH en BTC (par ETHBTC de Binance), escala logarítmica, velas diarias")
    plots.save(fig, "01_ratio_eth_btc.png")


def chart_corr_beta(r: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    roll_corr = r.ETH.rolling(90).corr(r.BTC).dropna()
    roll_beta = (r.ETH.rolling(90).cov(r.BTC) / r.BTC.rolling(90).var()).dropna()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True)
    a1.plot(roll_corr.index, roll_corr.values, color=plots.SERIES[0], linewidth=1.6)
    a1.set_ylim(0.5, 1.0)
    plots.es_axis(a1.yaxis, 1)
    a1.set_title("Muy correlacionados, pero ETH no se mueve el doble que BTC", pad=26)
    plots.subtitle(a1, "Correlación de rentabilidades diarias ETH-BTC (ventana móvil de 90 días)")
    a2.plot(roll_beta.index, roll_beta.values, color=plots.SERIES[1], linewidth=1.6)
    end = roll_beta.index[-1]
    a2.axhline(1.0, color=plots.MUTED, linewidth=1)
    a2.text(end, 0.88, "beta 1 (igual que BTC)", ha="right", va="top", color=plots.INK_2, fontsize=9)
    a2.axhline(2.0, color=plots.MUTED, linewidth=1)
    a2.text(end, 2.05, "beta 2: el ejemplo de la idea (BTC +1 %, ETH +2 %)", ha="right", va="bottom",
            color=plots.INK_2, fontsize=9)
    a2.set_ylim(0.4, 2.35)
    plots.es_axis(a2.yaxis, 1)
    plots.subtitle(a2, "Beta de ETH respecto a BTC (cuánto se mueve ETH por cada 1 % de BTC), 90 días")
    fig.subplots_adjust(hspace=0.32)
    plots.save(fig, "02_correlacion_beta.png")


def chart_legs(L: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    lim = 0.45
    xs = np.array([-lim, lim])
    ax.plot(xs, xs, color=plots.MUTED, linewidth=1.2, label="ETH se mueve igual que BTC")
    ax.plot(xs / 2, xs, color=plots.INK_2, linewidth=1.2, linestyle=(0, (4, 3)),
            label="ETH se mueve el doble (hipótesis)")
    for i, (direction, label) in enumerate([("subida", "Tramos de subida de BTC"), ("bajada", "Tramos de bajada de BTC")]):
        g = L[L.direction == direction]
        ax.scatter(g.pct_a, g.pct_b, s=22, color=plots.SERIES[i], alpha=0.55,
                   edgecolors=plots.SURFACE, linewidths=0.6, label=label)
    ax.set_xlim(-lim * 0.75, lim)
    ax.set_ylim(-lim * 0.95, lim)
    plots.es_axis(ax.xaxis, percent=True)
    plots.es_axis(ax.yaxis, percent=True)
    ax.set_xlabel("Variación de BTC en el tramo")
    ax.set_ylabel("Variación de ETH en el mismo tramo")
    ax.legend(loc="upper left", fontsize=9.5)
    ax.set_title("En cada tramo, ETH ≈ BTC × 1,1 (no ×2) y con mucho ruido", pad=26)
    plots.subtitle(ax, f"{len(L)} tramos de BTC de al menos un 5 % (2018–2026, velas de 1 h)")
    plots.save(fig, "03_tramos_btc_eth.png")


def chart_predictability(pred: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.8))
    x = np.arange(len(pred))
    t = pred.t_ventaja.to_numpy()
    colors = [plots.DIVERGING[1] if v > 0 else plots.DIVERGING[5] for v in t]
    ax.axhspan(-2, 2, color="#f0efec", zorder=0)
    ax.text(3.5, -1.0, "zona de ruido (|t| < 2): no se distingue del azar",
            ha="center", va="center", color=plots.INK_2, fontsize=9)
    ax.bar(x, t, width=0.55, color=colors, zorder=2)
    for xi, v in zip(x, t):
        ax.text(xi, v + (0.4 if v > 0 else -0.4), plots.num(v, 1, sign=True), ha="center",
                va="bottom" if v > 0 else "top", color=plots.INK_2, fontsize=9)
    ax.axhline(0, color=plots.AXIS, linewidth=1)
    ax.set_xticks(x, [f"velas de {s}" for s in pred.temporalidad], fontsize=9)
    ax.set_ylabel("fuerza de la señal (estadístico t)")
    from matplotlib.ticker import MultipleLocator
    ax.yaxis.set_major_locator(MultipleLocator(4))
    plots.es_axis(ax.yaxis, 0)
    ax.set_ylim(min(t.min() - 2, -4), max(t.max() + 2, 4))
    ax.grid(axis="x", visible=False)
    ax.set_title("La regla no tiene ventaja estadística en ninguna temporalidad", pad=26)
    plots.subtitle(ax, "Azul = a favor de la idea (tras subida, ETH/BTC cae).  Rojo = en contra "
                       "(ETH sigue a BTC con retraso o hay tendencia)")
    plots.save(fig, "04_predictibilidad.png")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    plots.setup()
    correlations()
    d_full = load_closes(["BTCUSDT", "ETHUSDT", "ETHBTC"], "1d")
    d_full.columns = ["BTC", "ETH", "ETHBTC"]
    d = d_full[d_full.index >= pd.Timestamp(START, tz="UTC")].dropna().copy()
    d["R"] = d.ETH / d.BTC
    r = eth_btc_profile(d)
    h = load_closes(["BTCUSDT", "ETHUSDT"], "1h", start=START).dropna()
    h.columns = ["BTC", "ETH"]
    legs5 = legs(h)
    m5 = load_closes(["BTCUSDT", "ETHUSDT"], "5m", start=START).dropna()
    m5.columns = ["BTC", "ETH"]
    pred = predictability(m5)
    print(pred[["temporalidad", "ventaja_por_vela_pb", "t_ventaja", "coste_por_vela_pb"]].round(2).to_string(index=False))
    variance_ratios(h)
    cointegration(d)
    chart_ratio(d_full)
    chart_corr_beta(r)
    chart_legs(legs5)
    chart_predictability(pred)
    print("OK: resultados en results/ y gráficos en docs/img/")


if __name__ == "__main__":
    main()
