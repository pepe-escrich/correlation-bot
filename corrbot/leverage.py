"""Simulación con apalancamiento (0x a 10x) de una o varias posiciones largas.

Modelo (por cada activo, "sub-cuenta" con margen aislado):
  * Apalancamiento L <= 1: spot. Sin financiación ni liquidación.
  * L > 1: futuros perpetuos. Se paga el funding real sobre TODO el nocional (los largos
    pagan cuando el funding es positivo) y hay liquidación: si el mínimo del día hace que
    el capital caiga por debajo del margen de mantenimiento, esa sub-cuenta pierde todo.
  * El nocional objetivo es L × exposición × capital. Cada día el nocional se desvía con el
    precio; se reajusta cuando se aleja del objetivo más que la banda (coste por unidad
    operada). Mantener un apalancamiento constante obliga a vender en caídas y comprar en
    subidas: eso (y la volatilidad) es lo que hace que el apalancamiento alto destruya valor.
  * Cartera: capital repartido a partes iguales entre los activos y re-repartido cada mes
    (una sub-cuenta liquidada vuelve a recibir capital en el siguiente reparto).

Convención temporal: arrays diarios alineados. r[t] y r_low[t] son la rentabilidad del día t
respecto al cierre de t-1 (al cierre y en el mínimo); e[t] es la exposición objetivo decidida
al cierre de t (sin apalancar, entre 0 y 1); f[t] es el funding por unidad de nocional pagado
durante el día t.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LevConfig:
    spot_cost: float = 0.0015          # comisión + deslizamiento por unidad operada (spot)
    perp_cost: float = 0.0010          # taker 0,05 % + deslizamiento 0,05 % (futuros)
    default_funding_8h: float = 0.0001  # 0,01 % cada 8 h cuando no hay dato
    maintenance: float = 0.005         # margen de mantenimiento
    band: float = 0.10                 # banda de rebalanceo (relativa al objetivo si > 1)


def daily_funding(funding_8h: pd.Series | None, index: pd.DatetimeIndex,
                  default_8h: float = 0.0001) -> np.ndarray:
    """Funding pagado por un largo durante cada día (suma de los cobros de ese día)."""
    if funding_8h is None or funding_8h.empty:
        return np.full(len(index), 3 * default_8h)
    per_day = funding_8h.groupby(funding_8h.index.floor("D")).sum()
    out = per_day.reindex(index)
    return out.fillna(3 * default_8h).to_numpy()


def asset_arrays(close: pd.Series, low: pd.Series, exposure: pd.Series,
                 funding_day: np.ndarray) -> dict[str, np.ndarray]:
    """Prepara los arrays diarios de un activo."""
    c = close.to_numpy(dtype=float)
    r = np.zeros(len(c))
    r_low = np.zeros(len(c))
    r[1:] = c[1:] / c[:-1] - 1
    r_low[1:] = low.to_numpy(dtype=float)[1:] / c[:-1] - 1
    e = np.nan_to_num(exposure.to_numpy(dtype=float), nan=0.0)
    return {"r": r, "r_low": np.minimum(r_low, r), "e": e, "f": funding_day}


def simulate_portfolio(assets: list[dict[str, np.ndarray]], L: float, cfg: LevConfig = LevConfig(),
                       rebalance: np.ndarray | None = None,
                       members: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Simula una cartera de sub-cuentas apalancadas.

    assets    -> lista de dicts con r, r_low, e, f (mismo número de días).
    rebalance -> bool por día: True = re-repartir el capital a partes iguales tras el cierre.
    members   -> bool [días, activos]: qué activos forman parte de la cartera ese día
                 (para un universo que cambia). None = todos siempre.
    Devuelve el capital total diario (empieza en 1) y el nº de liquidaciones.
    """
    n_days, n_assets = len(assets[0]["r"]), len(assets)
    if members is None:
        members = np.ones((n_days, n_assets), dtype=bool)
    if rebalance is None:
        rebalance = np.zeros(n_days, dtype=bool)
    perp = L > 1
    cost = cfg.perp_cost if perp else cfg.spot_cost
    r = np.column_stack([a["r"] for a in assets])
    r_low = np.column_stack([a["r_low"] for a in assets])
    e = np.column_stack([a["e"] for a in assets])
    f = np.column_stack([a["f"] for a in assets])

    eq = np.zeros(n_assets)          # capital de cada sub-cuenta
    notional = np.zeros(n_assets)    # nocional invertido tras el último cierre
    cash = 0.0                       # capital fuera de las sub-cuentas
    total = np.empty(n_days)
    liquidations = 0

    def allocate(t: int, total_value: float) -> None:
        nonlocal cash
        m = members[t]
        k = m.sum()
        new_eq = np.where(m, total_value / k, 0.0) if k else np.zeros(n_assets)
        cash = 0.0 if k else total_value
        for i in range(n_assets):
            target_n = L * e[t, i] * new_eq[i] if m[i] else 0.0
            trade = abs(target_n - notional[i])
            new_eq[i] -= trade * cost if new_eq[i] > 0 else 0.0
            notional[i] = L * e[t, i] * new_eq[i] if m[i] else 0.0
        eq[:] = new_eq

    allocate(0, 1.0)
    total[0] = eq.sum() + cash
    for t in range(1, n_days):
        for i in range(n_assets):
            if eq[i] <= 0 or notional[i] == 0:
                continue
            if perp:
                worst = eq[i] + notional[i] * r_low[t, i]
                if worst <= cfg.maintenance * notional[i] * (1 + r_low[t, i]):
                    eq[i], notional[i] = 0.0, 0.0
                    liquidations += 1
                    continue
                eq[i] -= notional[i] * f[t, i]
            eq[i] += notional[i] * r[t, i]
            if eq[i] <= 0:
                eq[i], notional[i] = 0.0, 0.0
                liquidations += 1
                continue
            notional[i] *= 1 + r[t, i]
        value = eq.sum() + cash
        total[t] = value
        if rebalance[t] or (members[t] != members[t - 1]).any():
            allocate(t, value)
            total[t] = eq.sum() + cash
            continue
        for i in range(n_assets):
            if eq[i] <= 0:
                continue
            target = L * e[t, i] if members[t, i] else 0.0
            current = notional[i] / eq[i]
            if (target == 0.0 and notional[i] != 0.0) or abs(current - target) >= cfg.band * max(1.0, target):
                eq[i] -= abs(target * eq[i] - notional[i]) * cost
                notional[i] = target * eq[i]
        total[t] = eq.sum() + cash
    return {"equity": total, "liquidations": liquidations}


def month_starts(index: pd.DatetimeIndex) -> np.ndarray:
    """True el primer día de cada mes (reparto mensual del capital)."""
    m = (index.tz_localize(None) if index.tz is not None else index).to_period("M")
    out = np.zeros(len(index), dtype=bool)
    out[1:] = m[1:] != m[:-1]
    return out


def equity_metrics(equity: np.ndarray, index: pd.DatetimeIndex, liquidations: int = 0) -> dict:
    eq = pd.Series(equity, index=index)
    years = len(eq) / 365
    final = eq.iloc[-1] / eq.iloc[0]
    ret = eq.pct_change().fillna(0.0).replace([np.inf, -np.inf], 0.0)
    sd = ret.std()
    return {
        "multiplicador": final,
        "CAGR": final ** (1 / years) - 1 if final > 0 else -1.0,
        "max_caida": (eq / eq.cummax() - 1).min(),
        "sharpe": ret.mean() / sd * np.sqrt(365) if sd > 1e-10 and final > 0 else np.nan,
        "liquidaciones": liquidations,
        "peor_año": (eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).first() - 1).min(),
    }


def bootstrap_paths(assets: list[dict[str, np.ndarray]], horizon: int, block: int,
                    rng: np.random.Generator) -> list[dict[str, np.ndarray]]:
    """Remuestreo por bloques de días completos (mismos días para todos los activos)."""
    n = len(assets[0]["r"])
    starts = rng.integers(1, n - block, int(np.ceil(horizon / block)))
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[:horizon]
    return [{k: v[idx] for k, v in a.items()} for a in assets]
