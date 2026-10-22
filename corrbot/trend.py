"""Estrategia A: seguimiento de tendencia (comprado o fuera) con tamaño por volatilidad.

Convención: la posición se decide con el cierre de la vela t y se mantiene durante la
vela t+1 (sin mirar al futuro). Posición entre 0 (todo en USDT) y 1 (todo invertido).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365


def trend_exposure(close: pd.Series, windows: tuple[int, ...] = (50, 100, 200)) -> pd.Series:
    """Fracción de medias simples que quedan por debajo del precio (0, 1/n, ..., 1).

    Vale NaN hasta que existe la media más larga."""
    parts = []
    for n in windows:
        sma = close.rolling(n).mean()
        parts.append((close > sma).astype(float).where(sma.notna()))
    return pd.concat(parts, axis=1).mean(axis=1, skipna=False)


def vol_scale(close: pd.Series, target: float | None = 0.40, window: int = 30) -> pd.Series:
    """Escala para que la volatilidad esperada no supere `target` (anualizada). Máximo 1."""
    if target is None:
        return pd.Series(1.0, index=close.index)
    vol = np.log(close).diff().rolling(window).std() * np.sqrt(DAYS_PER_YEAR)
    return (target / vol).clip(upper=1.0)


def apply_band(target: pd.Series, band: float = 0.10) -> pd.Series:
    """Solo cambia la posición si el objetivo se aleja al menos `band` de la actual.
    Las salidas completas (objetivo 0) se ejecutan siempre."""
    out = np.empty(len(target))
    cur = 0.0
    for i, t in enumerate(target.to_numpy()):
        if np.isfinite(t) and (abs(t - cur) >= band or (t == 0.0 and cur != 0.0)):
            cur = float(t)
        out[i] = cur
    return pd.Series(out, index=target.index)


def strategy_a(close: pd.Series, windows: tuple[int, ...] = (50, 100, 200),
               target_vol: float | None = 0.40, band: float = 0.10) -> pd.Series:
    """Posición objetivo de la estrategia A (decidida al cierre de cada vela diaria)."""
    raw = trend_exposure(close, windows) * vol_scale(close, target_vol)
    return apply_band(raw, band)


def backtest_position(close: pd.Series, position: pd.Series, cost: float = 0.0015,
                      delay: int = 0) -> pd.DataFrame:
    """Rentabilidad diaria de mantener `position` (0..1) del activo y el resto en efectivo.

    cost  -> coste por unidad de posición operada (comisión + deslizamiento).
    delay -> velas de retraso adicionales en la ejecución (test de estrés).
    """
    r = close.pct_change().fillna(0.0)
    held = position.shift(1 + delay).fillna(0.0)
    turnover = held.diff().abs()
    turnover.iloc[0] = abs(held.iloc[0])
    ret = held * r - turnover * cost
    return pd.DataFrame({"ret": ret, "held": held, "turnover": turnover})


def perf(ret: pd.Series, turnover: pd.Series | None = None) -> dict:
    """Métricas en dólares a partir de rentabilidades diarias."""
    ret = ret.dropna()
    eq = (1 + ret).cumprod()
    years = len(ret) / DAYS_PER_YEAR
    sd = ret.std()
    out = {
        "multiplicador": eq.iloc[-1],
        "CAGR": eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0,
        "volatilidad": sd * np.sqrt(DAYS_PER_YEAR),
        "sharpe": ret.mean() / sd * np.sqrt(DAYS_PER_YEAR) if sd > 0 else np.nan,
        "max_caida": (eq / eq.cummax() - 1).min(),
    }
    out["calmar"] = out["CAGR"] / abs(out["max_caida"]) if out["max_caida"] < 0 else np.nan
    if turnover is not None:
        out["rotacion_anual"] = turnover.loc[ret.index].sum() / years
    return out


def random_trend_null(close: pd.Series, exposure: pd.Series, target_vol: float | None,
                      band: float, cost: float, start: pd.Timestamp, end: pd.Timestamp,
                      n_sims: int = 1000, seed: int = 0) -> np.ndarray:
    """Sharpe de estrategias con los mismos tramos de exposición de tendencia (mismas
    duraciones y niveles) pero en orden aleatorio. Mide si el *timing* aporta."""
    rng = np.random.default_rng(seed)
    exp = exposure.dropna()
    vals = exp.to_numpy()
    change = np.flatnonzero(np.diff(vals)) + 1
    bounds = np.concatenate([[0], change, [len(vals)]])
    runs = [(vals[a], b - a) for a, b in zip(bounds[:-1], bounds[1:])]
    scale = vol_scale(close, target_vol).loc[exp.index]
    sharpes = np.empty(n_sims)
    for k in range(n_sims):
        order = rng.permutation(len(runs))
        sim = np.concatenate([np.full(runs[j][1], runs[j][0]) for j in order])
        pos = apply_band(pd.Series(sim, index=exp.index) * scale, band)
        bt = backtest_position(close.loc[exp.index], pos, cost)
        r = bt["ret"][(bt.index >= start) & (bt.index <= end)]
        sharpes[k] = r.mean() / r.std() * np.sqrt(DAYS_PER_YEAR)
    return sharpes


def block_bootstrap_max_dd(ret: pd.Series, horizon_days: int = 3 * 365, block: int = 30,
                           n_sims: int = 2000, seed: int = 0) -> np.ndarray:
    """Caídas máximas simuladas re-muestreando bloques de `block` días de rentabilidades."""
    rng = np.random.default_rng(seed)
    r = ret.dropna().to_numpy()
    n_blocks = int(np.ceil(horizon_days / block))
    out = np.empty(n_sims)
    for k in range(n_sims):
        starts = rng.integers(0, len(r) - block, n_blocks)
        path = np.concatenate([r[s:s + block] for s in starts])[:horizon_days]
        eq = np.cumprod(1 + path)
        out[k] = (eq / np.maximum.accumulate(eq) - 1).min()
    return out
