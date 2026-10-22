"""Backtester de estrategias de rotación entre dos activos.

Convención: A = activo "tranquilo" (p. ej. BTC), B = activo de beta alta (p. ej. ETH).
La cartera está siempre 100 % en A (posición 0) o 100 % en B (posición 1).

Identidad clave (se cumple exactamente):
    resultado_vs_HODL_A = exp( sum_{barras en B} Δlog(B/A) ) · (1 - coste)^nº_cambios
Es decir, frente a "quedarse en BTC", la estrategia solo gana o pierde por cómo se
mueve el ratio ETH/BTC mientras está en ETH, menos las comisiones.

Las señales se calculan con datos hasta el CIERRE de la barra t y la posición se
mantiene durante la barra t+1 (sin mirar al futuro).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .stats import zigzag

PERIODS_PER_YEAR = {"5m": 365 * 288, "15m": 365 * 96, "1h": 365 * 24, "4h": 365 * 6,
                    "12h": 365 * 2, "1d": 365, "3d": 365 / 3, "1w": 52}


@dataclass(frozen=True)
class Costs:
    """Costes por operación (fracciones: 0.001 = 0,1 %)."""

    fee: float = 0.00075        # Binance spot con descuento BNB (sin descuento: 0.001)
    slippage: float = 0.0002    # medio spread + deslizamiento (tick ETH/BTC ≈ 0,03 %)
    trades_per_switch: int = 1  # 1 con par directo (ETH/BTC); 2 si se pasa por USDT

    @property
    def per_switch(self) -> float:
        return self.trades_per_switch * (self.fee + self.slippage)


NO_COSTS = Costs(fee=0.0, slippage=0.0)


# --------------------------------------------------------------------- señales
def target_time_rule(signal_returns: np.ndarray, contrarian: bool = True,
                     deadband: float = 0.0, start: int = 0) -> np.ndarray:
    """Regla literal: tras una vela en la que A sube -> A (contrarian) ; tras bajada -> B.

    Con contrarian=False se hace lo contrario (seguir la tendencia).
    `deadband` ignora velas con movimiento menor que ese umbral (se mantiene posición).
    """
    r = np.asarray(signal_returns, dtype=float)
    tgt = np.full(len(r), np.nan)
    up, down = r > deadband, r < -deadband
    tgt[up] = 0.0 if contrarian else 1.0
    tgt[down] = 1.0 if contrarian else 0.0
    return _ffill(tgt, start)


def target_zigzag(signal_prices: np.ndarray, threshold: float, contrarian: bool = True,
                  start: int = 0) -> np.ndarray:
    """Tramos por umbral: cuando se confirma una subida de X % desde el último mínimo
    -> A (contrarian) ; cuando se confirma una bajada de X % desde el último máximo -> B.
    """
    piv = zigzag(signal_prices, threshold)
    tgt = np.full(len(signal_prices), np.nan)
    after_up = 0.0 if contrarian else 1.0  # giro alcista confirmado (pivote = mínimo)
    after_down = 1.0 - after_up
    conf = piv["confirm"].to_numpy()
    tgt[conf] = np.where(piv["kind"].to_numpy() == -1, after_up, after_down)
    return _ffill(tgt, start)


def target_anchored_grid(ratio: np.ndarray, threshold: float, contrarian: bool = True,
                         start: int = 0) -> np.ndarray:
    """"Grid" de un nivel sobre el ratio B/A, anclado al precio del último cambio.

    contrarian: en A, compra B si el ratio cae X % desde el último cambio; en B, vuelve
    a A si el ratio sube X % desde la compra (toma de beneficio clásica de un grid).
    """
    x = np.asarray(ratio, dtype=float)
    tgt = np.empty(len(x))
    pos, anchor = start, x[0]
    for i, v in enumerate(x):
        if contrarian:
            if pos == 0 and v <= anchor * (1 - threshold):
                pos, anchor = 1, v
            elif pos == 1 and v >= anchor * (1 + threshold):
                pos, anchor = 0, v
        else:
            if pos == 0 and v >= anchor * (1 + threshold):
                pos, anchor = 1, v
            elif pos == 1 and v <= anchor * (1 - threshold):
                pos, anchor = 0, v
        tgt[i] = pos
    return tgt


def _ffill(tgt: np.ndarray, start: int) -> np.ndarray:
    s = pd.Series(tgt).ffill().fillna(float(start))
    return s.to_numpy()


# ------------------------------------------------------------------ simulación
def run_switch(pa: pd.Series, pb: pd.Series, target: np.ndarray, costs: Costs) -> pd.DataFrame:
    """Simula la rotación 0/1. Devuelve equity en moneda base (USDT) y en unidades de A."""
    ra = pa.pct_change().fillna(0.0).to_numpy()
    rb = pb.pct_change().fillna(0.0).to_numpy()
    tgt = np.asarray(target, dtype=float)
    held = np.concatenate([[tgt[0]], tgt[:-1]])
    switch = np.concatenate([[0.0], np.abs(np.diff(tgt))])
    growth = (1 + held * rb + (1 - held) * ra) * (1 - switch * costs.per_switch)
    equity = np.cumprod(growth)
    hodl_a = (pa / pa.iloc[0]).to_numpy()
    return pd.DataFrame({"equity": equity, "equity_in_a": equity / hodl_a,
                         "held": held, "switch": switch}, index=pa.index)


def run_rebalance(pa: pd.Series, pb: pd.Series, weight_b: float = 0.5, costs: Costs = Costs(),
                  band: float | None = None, every: int | None = None) -> pd.DataFrame:
    """Cartera con pesos fijos (bot de rebalanceo). Rebalancea cada `every` barras y/o
    cuando el peso se desvía más de `band` del objetivo. Coste proporcional a lo operado."""
    ra = pa.pct_change().fillna(0.0).to_numpy()
    rb = pb.pct_change().fillna(0.0).to_numpy()
    c = costs.fee + costs.slippage
    value, wb = 1.0, weight_b
    equity = np.empty(len(ra))
    equity[0] = 1.0
    n_reb = 0
    for t in range(1, len(ra)):
        vb = value * wb * (1 + rb[t])
        va = value * (1 - wb) * (1 + ra[t])
        value = va + vb
        wb = vb / value
        if (band is not None and abs(wb - weight_b) > band) or (every and t % every == 0):
            value -= abs(wb - weight_b) * value * c
            wb = weight_b
            n_reb += 1
        equity[t] = value
    hodl_a = (pa / pa.iloc[0]).to_numpy()
    out = pd.DataFrame({"equity": equity, "equity_in_a": equity / hodl_a}, index=pa.index)
    out.attrs["rebalances"] = n_reb
    return out


# ---------------------------------------------------------------------- métricas
def summarize(result: pd.DataFrame, name: str = "") -> dict:
    eq = result["equity"]
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total = eq.iloc[-1] / eq.iloc[0]
    daily = eq.resample("1D").last().pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan
    out = {
        "estrategia": name,
        "multiplicador": total,
        "CAGR": total ** (1 / years) - 1,
        "max_drawdown": (eq / eq.cummax() - 1).min(),
        "sharpe": sharpe,
        "vs_hodl_a": result["equity_in_a"].iloc[-1] / result["equity_in_a"].iloc[0],
    }
    if "switch" in result:
        n = result["switch"].sum()
        out["cambios_por_año"] = n / years
        out["tiempo_en_b"] = result["held"].mean()
    elif "rebalances" in result.attrs:
        out["cambios_por_año"] = result.attrs["rebalances"] / years
    return out


def yearly_vs_a(result: pd.DataFrame) -> pd.Series:
    """Rendimiento frente a HODL A año a año (1.05 = +5 % más unidades de A)."""
    e = result["equity_in_a"]
    ends = e.groupby(e.index.year).last()
    starts = e.groupby(e.index.year).first()
    prev = ends.shift(1).fillna(starts)
    return ends / prev


# -------------------------------------------------------------- test de azar
def random_timing_null(pa: pd.Series, pb: pd.Series, target: np.ndarray,
                       n_sims: int = 500, seed: int = 0) -> np.ndarray:
    """Distribución de resultados (vs HODL A, sin costes) de estrategias con el MISMO
    número de cambios y las mismas duraciones de tenencia, pero en orden aleatorio.
    Sirve para ver si el "timing" de la estrategia es mejor que el azar."""
    rng = np.random.default_rng(seed)
    dlr = np.diff(np.log(pb.to_numpy() / pa.to_numpy()), prepend=np.nan)
    dlr[0] = 0.0
    dlr = np.nan_to_num(dlr)
    tgt = np.asarray(target, dtype=float)
    held = np.concatenate([[tgt[0]], tgt[:-1]])
    change = np.flatnonzero(np.diff(held)) + 1
    bounds = np.concatenate([[0], change, [len(held)]])
    lengths = np.diff(bounds)
    out = np.empty(n_sims)
    for k in range(n_sims):
        perm = rng.permutation(lengths)
        state0 = rng.integers(0, 2)
        states = (np.arange(len(perm)) + state0) % 2
        sim_held = np.repeat(states, perm)
        out[k] = np.exp(np.sum(sim_held * dlr))
    return out


def walk_forward(curves_in_a: dict[str, pd.Series], train_years: int = 2,
                 first_test_year: int | None = None) -> pd.DataFrame:
    """Selección de parámetros "a ciegas": cada 1 de enero se elige la configuración que
    mejor lo hizo (vs HODL A) en los `train_years` anteriores y se aplica al año siguiente."""
    df = pd.DataFrame(curves_in_a)
    years = sorted(set(df.index.year))
    first = first_test_year or years[0] + train_years
    rows = []
    for y in [y for y in years if y >= first]:
        train = df[(df.index.year >= y - train_years) & (df.index.year < y)]
        test = df[df.index.year == y]
        if train.empty or test.empty:
            continue
        train_perf = train.iloc[-1] / train.iloc[0]
        best = train_perf.idxmax()
        prev_end = df[df.index.year < y].iloc[-1]
        test_perf = test.iloc[-1] / prev_end
        rows.append({"año": y, "elegida": best, "train_vs_a": train_perf[best],
                     "test_vs_a": test_perf[best], "mejor_a_posteriori": test_perf.idxmax(),
                     "mejor_test_vs_a": test_perf.max()})
    return pd.DataFrame(rows)
