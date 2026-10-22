"""Estrategia A aplicada a HYPE con 1.000 $ desde el 1 de enero de 2026.

Datos: velas diarias del par spot HYPE/USDC de Hyperliquid (cotiza desde el 29-11-2024; en
Binance solo desde septiembre de 2026). Misma regla que la validada en BTC y ETH: medias de
50/100/200 días, volatilidad de 30 días con objetivo del 40 %, banda de 10 puntos, costes del
0,15 % por operación. Se simula como lo haría el bot: cantidad fija de HYPE entre órdenes y la
banda medida contra el % realmente invertido.

Informativo: la misma regla sin el límite de volatilidad, mantener HYPE y la estrategia A en
BTC+ETH en el mismo periodo.

Uso: python scripts/hype_2026.py   → results/hype_2026/ y docs/img/21_hype_2026.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corrbot import plots  # noqa: E402
from corrbot.data import download_hyperliquid_daily, load_klines  # noqa: E402
from corrbot.trend import trend_exposure, vol_scale  # noqa: E402

OUT = ROOT / "results" / "hype_2026"
DECISION_0 = pd.Timestamp("2025-12-31", tz="UTC")   # primera decisión con el cierre del 31-12-2025
END = pd.Timestamp("2026-10-21", tz="UTC")
CAPITAL, COST, BAND = 1000.0, 0.0015, 0.10


def simulate(close: pd.Series, target: pd.Series, capital: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bot: cantidad fija de monedas entre órdenes; ordena si el % real se aleja ≥ banda del objetivo
    (o si el objetivo es 0). La orden se lanza al cierre diario (00:00 UTC del día siguiente)."""
    usdt, qty = capital, 0.0
    orders, days = [], []
    for t in close.loc[DECISION_0:END].index:
        p = close.loc[t]
        eq = usdt + qty * p
        f = qty * p / eq
        tg = target.loc[t]
        if np.isfinite(tg) and (abs(tg - f) >= BAND or (tg == 0 and qty > 0)):
            delta = tg * eq - qty * p
            fee = abs(delta) * COST
            usdt -= delta + fee
            qty += delta / p
            orders.append({"fecha": (t + pd.Timedelta(days=1)).date(), "orden": "compra" if delta > 0 else "venta",
                           "importe_$": abs(delta), "precio": p, "invertido_tras_la_orden": tg, "coste_$": fee})
        value = usdt + qty * p
        days.append({"fecha": t, "valor_$": value, "en_moneda_$": qty * p, "usdt_$": usdt,
                     "invertido": qty * p / value})
    return pd.DataFrame(orders), pd.DataFrame(days).set_index("fecha")


def summary(name: str, days: pd.DataFrame, orders: pd.DataFrame) -> dict:
    v = days["valor_$"]
    return {"variante": name, "valor_final_$": v.iloc[-1], "rentabilidad": v.iloc[-1] / v.iloc[0] - 1,
            "peor_caida": (v / v.cummax() - 1).min(), "ordenes": len(orders),
            "invertido_medio": days["invertido"].iloc[1:].mean(),
            "dias_todo_fuera": int((days["invertido"].iloc[1:] < 1e-9).sum()),
            "costes_$": orders["coste_$"].sum() if len(orders) else 0.0}


def chart(hype: pd.DataFrame, hodl: pd.Series, btceth: pd.Series) -> None:
    import matplotlib.pyplot as plt

    plots.setup()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.8), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    series = [(hodl, "Mantener HYPE", plots.SERIES[1]), (hype["valor_$"], "Estrategia A en HYPE", plots.SERIES[0]),
              (btceth, "Estrategia A en BTC+ETH", plots.SERIES[2])]
    for s, label, color in series:
        ax1.plot(s.index, s, color=color, linewidth=2, label=label)
        ax1.annotate(f"{s.iloc[-1]:,.0f} $".replace(",", "."), (s.index[-1], s.iloc[-1]), xytext=(6, 0),
                     textcoords="offset points", va="center", color=plots.INK, fontsize=9.5)
    ax1.axhline(CAPITAL, color=plots.MUTED, linewidth=1)
    ax1.set_ylabel("valor de los 1.000 $")
    ax1.legend(loc="upper left")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f} $".replace(",", ".")))
    ax1.set_title("Con HYPE en 2026, la estrategia gana pero se queda muy por detrás de mantener", pad=26)
    plots.subtitle(ax1, "1.000 $ desde el 1 de enero de 2026 hasta el 21 de octubre. Estrategia A con la regla validada "
                        "(medias de 50/100/200 días y límite de volatilidad del 40 %)")
    ax2.fill_between(hype.index, hype["invertido"], step="post", color=plots.SERIES[0], alpha=0.35, linewidth=0)
    ax2.plot(hype.index, hype["invertido"], drawstyle="steps-post", color=plots.SERIES[0], linewidth=1.2)
    ax2.set_ylim(0, 1)
    plots.es_axis(ax2.yaxis, percent=True)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: "0" if v == 0 else f"{v * 100:.0f} %"))
    ax2.set_ylabel("% invertido en HYPE")
    import matplotlib.dates as mdates

    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: plots.MESES[mdates.num2date(v).month - 1]))
    fig.subplots_adjust(hspace=0.12, right=0.9)
    plots.save(fig, "21_hype_2026.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hype = download_hyperliquid_daily()["close"]
    vol30 = np.log(hype).diff().rolling(30).std() * np.sqrt(365)
    targets = {"Estrategia A (regla validada)": trend_exposure(hype) * vol_scale(hype, 0.40),
               "Sin límite de volatilidad (informativo)": trend_exposure(hype) * 1.0}
    rows = []
    for name, tgt in targets.items():
        orders, days = simulate(hype, tgt, CAPITAL)
        rows.append(summary(name, days, orders))
        if name.startswith("Estrategia A"):
            main_orders, main_days = orders, days
    px = hype.loc[DECISION_0:END]
    hodl = CAPITAL * (1 - COST) * px / px.iloc[0]
    hodl.iloc[0] = CAPITAL
    rows.append({"variante": "Mantener HYPE", "valor_final_$": hodl.iloc[-1], "rentabilidad": hodl.iloc[-1] / CAPITAL - 1,
                 "peor_caida": (hodl / hodl.cummax() - 1).min(), "ordenes": 1, "invertido_medio": 1.0,
                 "dias_todo_fuera": 0, "costes_$": CAPITAL * COST})
    # Contexto: la estrategia validada en BTC+ETH (500 $ cada una) en el mismo periodo
    parts = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        c = load_klines(sym, "1d")["close"]
        o, d = simulate(c, trend_exposure(c) * vol_scale(c, 0.40), CAPITAL / 2)
        parts.append((o, d))
    btceth = parts[0][1]["valor_$"] + parts[1][1]["valor_$"]
    inv = (parts[0][1]["en_moneda_$"] + parts[1][1]["en_moneda_$"]) / btceth
    rows.append({"variante": "Estrategia A en BTC+ETH (contexto)", "valor_final_$": btceth.iloc[-1],
                 "rentabilidad": btceth.iloc[-1] / CAPITAL - 1, "peor_caida": (btceth / btceth.cummax() - 1).min(),
                 "ordenes": len(parts[0][0]) + len(parts[1][0]), "invertido_medio": inv.iloc[1:].mean(),
                 "dias_todo_fuera": int((inv.iloc[1:] < 1e-9).sum()),
                 "costes_$": parts[0][0]["coste_$"].sum() + parts[1][0]["coste_$"].sum()})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "resumen.csv", index=False)
    main_orders.to_csv(OUT / "ordenes.csv", index=False)
    monthly = main_days[["en_moneda_$", "usdt_$", "valor_$", "invertido"]].resample("ME").last()
    monthly["precio_HYPE"] = hype.resample("ME").last().reindex(monthly.index)
    monthly["volatilidad_30d"] = vol30.resample("ME").last().reindex(monthly.index)
    monthly.to_csv(OUT / "mensual.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 12, "display.max_rows", 200):
        print(res.round(3).to_string(index=False))
        print(main_orders.round(2).to_string(index=False))
        print(monthly.round(2).to_string())
        print("volatilidad 30d de HYPE en 2026: mediana %.0f %%, rango %.0f–%.0f %%" % (
            vol30.loc["2026"].median() * 100, vol30.loc["2026"].min() * 100, vol30.loc["2026"].max() * 100))
    chart(main_days, hodl, btceth)


if __name__ == "__main__":
    main()
