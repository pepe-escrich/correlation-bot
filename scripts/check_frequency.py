"""¿Cambia algo si la estrategia A se revisa cada hora o cada minuto en vez de una vez al día?

Misma regla que la validada (medias de 50/100/200 días, volatilidad de 30 días con objetivo
del 40 %, banda de 10 puntos, costes del 0,15 % por unidad operada), evaluada con el precio
del momento:
  - el precio está "por encima de la media de n días" si supera la media de los n−1 cierres
    diarios anteriores (equivale a la media de n días contando el precio actual como cierre
    de hoy, así que al cierre del día coincide exactamente con la versión diaria);
  - la volatilidad incluye la rentabilidad del día en curso.
Variantes: diaria (la validada), cada hora, cada minuto y mixta (reduce en cualquier minuto,
amplía solo al cierre del día). Cada mitad (BTC y ETH) va por separado, como en la validación.

Uso: python scripts/check_frequency.py   (~2 minutos; necesita las velas de 1 minuto)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corrbot.data import load_klines  # noqa: E402
from corrbot.trend import apply_band, backtest_position, strategy_a  # noqa: E402

OUT = ROOT / "results" / "frecuencia"
START, EXAM, END = (pd.Timestamp(x, tz="UTC") for x in ["2018-03-05", "2025-01-01", "2026-10-22"])
WINDOWS = (50, 100, 200)
TARGET_VOL, BAND, COST, DAYS = 0.40, 0.10, 0.0015, 365


def live_target(sym: str) -> tuple[pd.Series, pd.Series]:
    """Exposición objetivo en cada minuto con el precio del momento, y precios de 1 minuto."""
    daily = load_klines(sym, "1d")["close"]
    bars = load_klines(sym, "1m")["close"]
    bars = bars[(bars.index >= START) & (bars.index < END)]
    day = bars.index.floor("D")
    p = bars.to_numpy()
    above = []
    for n in WINDOWS:
        thr = daily.rolling(n - 1).mean().shift(1)          # media de los n−1 cierres anteriores
        above.append(p > thr.reindex(day).to_numpy())
    trend = np.mean(above, axis=0)
    lr = np.log(daily).diff()
    a1 = lr.rolling(29).sum().shift(1).reindex(day).to_numpy()       # 29 rentabilidades completas
    a2 = (lr ** 2).rolling(29).sum().shift(1).reindex(day).to_numpy()
    prev_close = daily.shift(1).reindex(day).to_numpy()
    r_live = np.log(p / prev_close)                                  # rentabilidad del día en curso
    s1, s2 = a1 + r_live, a2 + r_live ** 2
    vol = np.sqrt(np.maximum(s2 - s1 ** 2 / 30, 0) / 29 * DAYS)
    scale = np.minimum(1.0, TARGET_VOL / vol)
    target = trend * scale
    valid = np.isfinite(a1) & np.isfinite(prev_close)
    for n in WINDOWS:
        valid &= np.isfinite(daily.rolling(n - 1).mean().shift(1).reindex(day).to_numpy())
    return pd.Series(np.where(valid, target, np.nan), index=bars.index), bars


def mixed_band(target: np.ndarray, is_close: np.ndarray) -> np.ndarray:
    """Reduce en cualquier minuto si el objetivo baja ≥ banda (o a 0); amplía solo al cierre del día."""
    out = np.empty(len(target))
    cur = 0.0
    for i, (t, close) in enumerate(zip(target.tolist(), is_close.tolist())):
        if t == t:                                                   # no es NaN
            if (t == 0.0 and cur != 0.0) or (cur - t >= BAND):
                cur = t
            elif close and abs(t - cur) >= BAND:
                cur = t
        out[i] = cur
    return out


def portfolio(parts: list, start, end) -> pd.Series:
    """Cartera 50/50 que empieza el periodo repartida a partes iguales (cada mitad va por separado)."""
    out = []
    for eq in parts:
        e = eq[(eq.index >= start - pd.Timedelta(days=1)) & (eq.index < end)]
        out.append(e / e.iloc[0])
    return 0.5 * out[0] + 0.5 * out[1].reindex(out[0].index).ffill()


def metrics(eq: pd.Series, gross: pd.Series, orders: pd.Series, start, end) -> dict:
    o = orders[(orders.index >= start) & (orders.index < end)]
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"multiplicador": eq.iloc[-1], "CAGR": eq.iloc[-1] ** (1 / years) - 1,
            "CAGR_sin_costes": gross.iloc[-1] ** (1 / years) - 1, "max_caida": (eq / eq.cummax() - 1).min(),
            "ordenes_por_año": o.sum() / years}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    halves = {}
    for sym in ["BTCUSDT", "ETHUSDT"]:
        target, px = live_target(sym)
        idx = px.index
        last_of_hour = (idx + pd.Timedelta(minutes=1)).floor("h") != idx.floor("h")
        last_of_day = (idx + pd.Timedelta(minutes=1)).floor("D") != idx.floor("D")
        variants = {
            "diaria (validada)": apply_band(target.where(last_of_day), BAND),
            "cada hora": apply_band(target.where(last_of_hour), BAND),
            "cada minuto": apply_band(target, BAND),
            "mixta: vende al minuto, compra al cierre": pd.Series(
                mixed_band(target.to_numpy(), last_of_day), index=idx),
        }
        # Referencia: la versión diaria original con velas diarias
        dly = load_klines(sym, "1d")["close"]
        ref = backtest_position(dly, strategy_a(dly))
        ref = ref[(ref.index >= START) & (ref.index < END)]
        ref0 = backtest_position(dly, strategy_a(dly), cost=0.0)
        ref0 = ref0[(ref0.index >= START) & (ref0.index < END)]
        halves.setdefault("referencia diaria (velas diarias)", []).append(
            ((1 + ref["ret"]).cumprod(), (1 + ref0["ret"]).cumprod(), (ref["turnover"] > 0).astype(int)))
        for name, pos in variants.items():
            bt = backtest_position(px, pos, cost=COST)
            bt0 = backtest_position(px, pos, cost=0.0)
            daily_last = lambda x: (1 + x).cumprod().resample("1D").last().ffill()  # noqa: E731
            orders = (bt["turnover"] > 0).astype(int)
            halves.setdefault(name, []).append((daily_last(bt["ret"]), daily_last(bt0["ret"]),
                                                orders.resample("1D").sum()))
        print(sym, "hecho", flush=True)
    rows = []
    for name, parts in halves.items():
        orders = parts[0][2].add(parts[1][2], fill_value=0)
        for period, s, e in [("2018-2026", START, END), ("desarrollo 2018-2024", START, EXAM),
                             ("examen 2025-2026", EXAM, END)]:
            eq = portfolio([parts[0][0], parts[1][0]], s, e)
            gross = portfolio([parts[0][1], parts[1][1]], s, e)
            rows.append({"variante": name, "periodo": period, **metrics(eq, gross, orders, s, e)})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "frecuencia_chequeo.csv", index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 10):
        print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
