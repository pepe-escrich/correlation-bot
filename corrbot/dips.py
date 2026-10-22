"""Estrategia B: comprar tras una caída brusca (pocas horas) dentro de una tendencia
alcista y vender al cabo de un tiempo fijo.

Ejecución modelada de forma conservadora:
  * Al cierre de la vela del disparador se pone una orden LÍMITE de compra a ese precio.
    Solo se ejecuta si el mínimo de la vela siguiente llega a ese precio; si el precio
    rebota sin tocarla, la operación se pierde (como pasaría en real).
  * La salida es a mercado al cierre de la vela `hold_bars` posterior a la compra.
  * Se cobra comisión de entrada (maker), de salida (taker), deslizamiento y el funding
    real de los perpetuos durante las horas mantenidas.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

BAR = pd.Timedelta(minutes=5)
BARS_PER_DAY = 288


@dataclass(frozen=True)
class DipParams:
    window_bars: int = 48            # caída medida en las últimas 4 h
    k: float = 3.0                   # umbral: caída de más de k desviaciones típicas
    hold_bars: int = 48              # salida a las 4 h
    trend_min: float | None = 2 / 3  # filtro de tendencia de A (None = sin filtro)
    vol_days: int = 30


@dataclass(frozen=True)
class DipCosts:
    entry: float = 0.0002     # orden límite en futuros (maker)
    exit: float = 0.0005      # orden a mercado (taker)
    slippage: float = 0.0002  # por operación completa

    @property
    def total(self) -> float:
        return self.entry + self.exit + self.slippage


def filter_on_bars(daily_exposure: pd.Series, bar_index: pd.DatetimeIndex) -> np.ndarray:
    """Exposición de tendencia que se conoce en cada vela intradía.

    El índice diario es la hora de apertura del día d; su cierre (y por tanto la señal)
    se conoce a las 00:00 del día d+1, así que se desplaza un día antes de rellenar."""
    known = daily_exposure.copy()
    known.index = known.index + pd.Timedelta(days=1)
    return known.reindex(bar_index, method="ffill").to_numpy()


def zscore_drop(close: np.ndarray, window_bars: int, vol_days: int) -> np.ndarray:
    """Rentabilidad de las últimas `window_bars` velas en desviaciones típicas
    (estimadas con los `vol_days` días anteriores, sin incluir la vela actual)."""
    lp = np.log(close)
    rw = np.full(len(lp), np.nan)
    rw[window_bars:] = lp[window_bars:] - lp[:-window_bars]
    sig = (pd.Series(rw).rolling(BARS_PER_DAY * vol_days, min_periods=BARS_PER_DAY * 10)
           .std().shift(1).to_numpy())
    return rw / sig


def dip_trades(bars: pd.DataFrame, daily_exposure: pd.Series | None, params: DipParams = DipParams(),
               costs: DipCosts = DipCosts(), funding: pd.Series | None = None,
               z: np.ndarray | None = None) -> pd.DataFrame:
    """Lista de operaciones de la estrategia B sobre velas de 5 min (columnas close y low)."""
    close = bars["close"].to_numpy()
    low = bars["low"].to_numpy()
    n = len(close)
    if z is None:
        z = zscore_drop(close, params.window_bars, params.vol_days)
    cond = z < -params.k
    if params.trend_min is not None:
        filt = filter_on_bars(daily_exposure, bars.index)
        cond &= filt >= params.trend_min - 1e-9
    cond[n - params.hold_bars - 2:] = False
    rows, busy_until = [], -1
    for i in np.flatnonzero(cond):
        if i <= busy_until:
            continue
        limit = close[i]
        if low[i + 1] > limit:          # el precio rebotó sin tocar la orden: no hay operación
            continue
        exit_bar = i + 1 + params.hold_bars
        rows.append((i + 1, exit_bar, limit, close[exit_bar]))
        busy_until = exit_bar
    if not rows:
        return pd.DataFrame(columns=["entrada", "salida", "bruto", "funding", "neto"])
    fill, exit_bar, entry_px, exit_px = map(np.array, zip(*rows))
    t_in = bars.index[fill] + BAR     # momento aproximado de la compra (cierre de la vela)
    t_out = bars.index[exit_bar] + BAR
    gross = exit_px / entry_px - 1
    fund = np.zeros(len(gross))
    if funding is not None and len(funding):
        cum = np.concatenate([[0.0], np.cumsum(funding.to_numpy())])
        ft = funding.index.to_numpy()
        a = np.searchsorted(ft, t_in.to_numpy(), side="right")
        b = np.searchsorted(ft, t_out.to_numpy(), side="right")
        fund = cum[b] - cum[a]            # el largo paga el funding positivo
    net = gross - costs.total - fund
    return pd.DataFrame({"entrada": t_in, "salida": t_out, "bruto": gross, "funding": fund, "neto": net})


def trade_stats(trades: pd.DataFrame, years: float) -> dict:
    if len(trades) < 2:
        return {"operaciones_año": len(trades) / years, "neto_medio_pb": np.nan, "t": np.nan,
                "aciertos": np.nan, "acumulado": np.nan}
    net = trades["neto"].to_numpy()
    return {
        "operaciones_año": len(net) / years,
        "neto_medio_pb": net.mean() * 1e4,
        "t": net.mean() / (net.std(ddof=1) / np.sqrt(len(net))),
        "aciertos": (net > 0).mean(),
        "acumulado": np.prod(1 + net) - 1,
    }


def daily_returns(trades: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Rentabilidad diaria de la cartera de B (operaciones agrupadas por día de salida)."""
    if trades.empty:
        return pd.Series(0.0, index=index)
    day = trades["salida"].dt.floor("D")
    growth = (1 + trades["neto"]).groupby(day.to_numpy()).prod() - 1
    return growth.reindex(index, fill_value=0.0)
