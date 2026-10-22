"""Controles de protección ante caídas para la estrategia A apalancada (BTC y ETH).

Mismo modelo que corrbot/leverage.py (funding, liquidación con el mínimo diario, rebalanceo
con costes, reparto mensual), más estos controles opcionales:

  * fast_vol  -> el tamaño usa la mayor de dos volatilidades: la de 30 días y una rápida
                 (media exponencial de ~10 días). Reduce la posición en cuanto el mercado
                 se pone nervioso.
  * stop_k    -> stop intradía: si el precio cae más de k desviaciones típicas diarias desde
                 el cierre anterior, la posición se cierra (con deslizamiento extra) y no se
                 vuelve a entrar hasta el cierre del día siguiente. El stop nunca se pone más
                 lejos que `stop_cap` × la distancia a la liquidación.
  * dd_floor  -> freno por caída (CPPI/TIPP): la exposición se multiplica por el "colchón"
                 que queda hasta un suelo situado `dd_floor` por debajo del máximo del capital.
                 En el máximo se usa todo el apalancamiento; en el suelo, cero.
                 dd_reset_days: el máximo de referencia es el de los últimos N días (permite
                 volver a operar tras tocar el suelo; None = suelo permanente).
  * strong_only -> solo se apalanca (>1x) cuando las tres medias están a favor.

Todas las decisiones usan información hasta el cierre anterior (sin mirar al futuro).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .leverage import LevConfig
from .trend import trend_exposure

DAYS = 365


@dataclass(frozen=True)
class Controls:
    name: str = "Sin protección"
    target_vol: float = 0.40
    fast_vol: bool = False
    stop_k: float | None = None
    stop_cap: float = 0.5
    dd_floor: float | None = None
    dd_reset_days: int | None = None
    strong_only: bool = False

    def with_(self, **kw) -> "Controls":
        return replace(self, **kw)


def prepare_asset(close: pd.Series, low: pd.Series, funding_day: np.ndarray) -> dict[str, np.ndarray]:
    """Arrays diarios de un activo: rentabilidades, mínimo, tendencia y volatilidades."""
    c = close.to_numpy(dtype=float)
    r = np.zeros(len(c))
    r[1:] = c[1:] / c[:-1] - 1
    r_low = np.zeros(len(c))
    r_low[1:] = low.to_numpy(dtype=float)[1:] / c[:-1] - 1
    lr = np.log(close).diff()
    vol_slow = (lr.rolling(30).std() * np.sqrt(DAYS)).to_numpy()
    vol_fast = (np.sqrt((lr ** 2).ewm(halflife=5, min_periods=10).mean()) * np.sqrt(DAYS)).to_numpy()
    return {"r": r, "r_low": np.minimum(r_low, r), "f": funding_day,
            "trend": trend_exposure(close).fillna(0.0).to_numpy(),
            "vol_slow": vol_slow, "vol_fast": vol_fast}


def simulate_protected(assets: list[dict[str, np.ndarray]], L: float, ctl: Controls = Controls(),
                       cfg: LevConfig = LevConfig(), rebalance: np.ndarray | None = None) -> dict:
    n_days, n_assets = len(assets[0]["r"]), len(assets)
    perp = L > 1
    cost = cfg.perp_cost if perp else cfg.spot_cost
    mm = cfg.maintenance
    if rebalance is None:
        rebalance = np.zeros(n_days, dtype=bool)
    get = lambda k: np.column_stack([a[k] for a in assets])  # noqa: E731
    r, r_low, f, trend = get("r"), get("r_low"), get("f"), get("trend")
    vol = np.fmax(get("vol_slow"), get("vol_fast")) if ctl.fast_vol else get("vol_slow")
    vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nan)

    eq = np.zeros(n_assets)
    notional = np.zeros(n_assets)
    total = np.empty(n_days)
    stats = {"liquidaciones": 0, "stops": 0, "dias_en_suelo": 0}

    def dd_multiplier(t: int) -> float:
        if ctl.dd_floor is None:
            return 1.0
        lo = 0 if ctl.dd_reset_days is None else max(0, t - ctl.dd_reset_days + 1)
        peak = total[lo:t + 1].max()
        floor = (1 - ctl.dd_floor) * peak
        cushion = (total[t] - floor) / total[t] if total[t] > 0 else 0.0
        return float(np.clip(cushion / ctl.dd_floor, 0.0, 1.0))

    def target(t: int, i: int, mult: float) -> float:
        if not np.isfinite(vol[t, i]) or trend[t, i] <= 0:
            return 0.0
        scale = min(1.0, ctl.target_vol / vol[t, i])
        lev = L if (not ctl.strong_only or trend[t, i] >= 1.0) else min(L, 1.0)
        return trend[t, i] * scale * lev * mult

    def allocate(t: int, value: float, mult: float, blocked: np.ndarray) -> None:
        share = value / n_assets
        for i in range(n_assets):
            tgt = 0.0 if blocked[i] else target(t, i, mult) * share
            eq[i] = share - abs(tgt - notional[i]) * cost
            notional[i] = 0.0 if blocked[i] else target(t, i, mult) * eq[i]

    total[0] = 1.0
    allocate(0, 1.0, 1.0, np.zeros(n_assets, dtype=bool))
    total[0] = eq.sum()
    for t in range(1, n_days):
        blocked = np.zeros(n_assets, dtype=bool)
        for i in range(n_assets):
            n_i = notional[i]
            if eq[i] <= 0 or n_i == 0:
                continue
            lev_eff = n_i / eq[i]
            liq_ret = -(1 / lev_eff - mm) / (1 - mm) if perp else -1.0
            if ctl.stop_k is not None and np.isfinite(vol[t - 1, i]):
                x = min(ctl.stop_k * vol[t - 1, i] / np.sqrt(DAYS), ctl.stop_cap * abs(liq_ret))
                if r_low[t, i] <= -x:
                    excess = -x - r_low[t, i]
                    fill = max(r_low[t, i], -x - max(0.005, 0.1 * excess))
                    if perp and fill <= liq_ret:
                        eq[i], notional[i] = 0.0, 0.0
                        stats["liquidaciones"] += 1
                    else:
                        eq[i] += n_i * fill - n_i * (1 + fill) * cost - (n_i * f[t, i] if perp else 0.0)
                        notional[i] = 0.0
                        stats["stops"] += 1
                    blocked[i] = True
                    continue
            if perp and r_low[t, i] <= liq_ret:
                eq[i], notional[i] = 0.0, 0.0
                stats["liquidaciones"] += 1
                continue
            if perp:
                eq[i] -= n_i * f[t, i]
            eq[i] += n_i * r[t, i]
            notional[i] = n_i * (1 + r[t, i])
            if eq[i] <= 0:
                eq[i], notional[i] = 0.0, 0.0
                stats["liquidaciones"] += 1
        total[t] = max(eq.sum(), 0.0)
        mult = dd_multiplier(t)
        if mult == 0.0:
            stats["dias_en_suelo"] += 1
        if rebalance[t]:
            allocate(t, total[t], mult, blocked)
            total[t] = eq.sum()
            continue
        for i in range(n_assets):
            if eq[i] <= 0 or blocked[i]:
                continue
            tgt = target(t, i, mult)
            cur = notional[i] / eq[i]
            if (tgt == 0.0 and notional[i] != 0.0) or abs(cur - tgt) >= cfg.band * max(1.0, tgt):
                eq[i] -= abs(tgt * eq[i] - notional[i]) * cost
                notional[i] = tgt * eq[i]
        total[t] = eq.sum()
    return {"equity": total, **stats}
