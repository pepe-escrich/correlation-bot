"""Estrategia intradía con stop-loss escalonado (protocolo en docs/intradia_10x.md).

Señales en velas de 15 min o 1 h (con el filtro de tendencia diaria de la estrategia A) y
gestión de cada operación sobre velas de 5 min:
  1) stop inicial a k × ATR,
  2) breakeven (+costes) al avanzar m × la distancia del stop,
  3) objetivo a 3 × distancia o stop que persigue al mejor cierre,
  4) cierre por tiempo a las 24 h.
Regla conservadora: si en una vela se tocan el stop y otro nivel, cuenta el stop primero; el
breakeven y el stop que persigue se aplican desde la vela siguiente.

Las operaciones se simulan sin apalancamiento; el apalancamiento se aplica después
(`month_paths`), usando la peor excursión adversa de cada operación para detectar
liquidaciones.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .dips import filter_on_bars

FIVE_MIN = pd.Timedelta(minutes=5)
REASONS = np.array(["stop", "breakeven", "stop que persigue", "objetivo", "tiempo"], dtype=object)


@dataclass(frozen=True)
class Mgmt:
    k: float = 2.0                 # stop inicial = k × ATR
    be: float | None = 1.0         # breakeven al avanzar be × distancia (None = sin breakeven)
    exit: str = "tp"               # "tp" (objetivo) o "trail" (stop que persigue)
    tp_r: float = 3.0              # objetivo en múltiplos de la distancia del stop
    max_hours: float = 24.0

    @property
    def max_bars(self) -> int:
        return int(round(self.max_hours * 12))


@dataclass(frozen=True)
class TradeCosts:
    taker: float = 0.0005
    maker: float = 0.0002
    slip: float = 0.0002
    overshoot: float = 0.10        # fracción de lo que la vela atraviesa el stop que se pierde

    @property
    def be_offset(self) -> float:
        """Margen sobre el precio de entrada para que salir en breakeven deje ~0 neto."""
        return 2 * (self.taker + self.slip)


# --------------------------------------------------------------------- señales
def resample_ohlc(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return bars[list(agg)].resample(rule).agg(agg).dropna()


def atr(ohlc: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = ohlc["close"].shift(1)
    tr = pd.concat([ohlc["high"] - ohlc["low"], (ohlc["high"] - prev).abs(), (ohlc["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def direction_allowed(ohlc: pd.DataFrame, daily_exposure: pd.Series) -> np.ndarray:
    """+1 si se permiten largos, −1 si se permiten cortos, 0 si no se opera."""
    expo = filter_on_bars(daily_exposure, ohlc.index)
    return np.where(expo >= 2 / 3 - 1e-9, 1, np.where(expo <= 1e-9, -1, 0)).astype(int)


def signals(ohlc: pd.DataFrame, kind: str, allowed: np.ndarray, p: float | None = None,
            seed: int = 0, lookback: int = 20) -> np.ndarray:
    """Señal (+1 largo, −1 corto, 0 nada) al cierre de cada vela."""
    c, h, lo = ohlc["close"], ohlc["high"], ohlc["low"]
    if kind == "breakout":
        up = (c > h.shift(1).rolling(lookback).max()).to_numpy()
        down = (c < lo.shift(1).rolling(lookback).min()).to_numpy()
    elif kind == "pullback":
        ema, a = c.ewm(span=20, adjust=False).mean(), atr(ohlc)
        up = (c < ema - a).to_numpy()
        down = (c > ema + a).to_numpy()
    elif kind == "random":
        u = np.random.default_rng(seed).random(len(c))
        up = down = u < p
    else:
        raise ValueError(kind)
    return np.where((allowed == 1) & up, 1, np.where((allowed == -1) & down, -1, 0))


# --------------------------------------------------------------- simulación
def _ns(values) -> np.ndarray:
    """Fechas (con o sin zona horaria) → enteros en nanosegundos UTC."""
    idx = pd.DatetimeIndex(values)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.values.astype("datetime64[ns]").astype(np.int64)


def _entries(bars: pd.DataFrame, ohlc: pd.DataFrame, sig: np.ndarray, atr_tf: pd.Series, tf: pd.Timedelta):
    """Candidatas válidas: vela de 5 min de entrada (la que abre al cierre de la señal),
    dirección y ATR de la señal. Se descartan las que caen en un hueco de datos."""
    t5 = _ns(bars.index)
    js = np.flatnonzero(sig)
    sig_close = _ns(ohlc.index[js] + tf)
    e = np.searchsorted(t5, sig_close)
    a = atr_tf.to_numpy(dtype=float)[js]
    ok = (e < len(t5) - 1) & np.isfinite(a) & (a > 0)
    ok &= t5[np.minimum(e, len(t5) - 1)] == sig_close
    return e[ok], np.asarray(sig)[js][ok].astype(np.int64), a[ok]


def _ohlc_arrays(bars: pd.DataFrame):
    return tuple(bars[k].to_numpy(dtype=float) for k in ["open", "high", "low", "close"])


def _frame(index5: pd.DatetimeIndex, e, i, d, entry, exit_px, code, exit_cost, w_fill, w_wick, dist_rel,
           costs: TradeCosts, funding: pd.Series | None) -> pd.DataFrame:
    t_in = index5[e]
    t_out = index5[i] + FIVE_MIN
    gross = d * (exit_px / entry - 1)
    fund = np.zeros(len(e))
    if funding is not None and len(e):
        ft = _ns(funding.index)
        cum = np.concatenate([[0.0], np.cumsum(funding.to_numpy(dtype=float))])
        a = np.searchsorted(ft, _ns(t_in), side="right")
        b = np.searchsorted(ft, _ns(t_out), side="right")
        fund = d * (cum[b] - cum[a])          # el largo paga funding positivo; el corto lo cobra
    cost = costs.taker + costs.slip + exit_cost
    return pd.DataFrame({
        "entrada": t_in, "salida": t_out, "dir": d, "precio_entrada": entry, "precio_salida": exit_px,
        "motivo": REASONS[code] if len(e) else np.array([], dtype=object),
        "bruto": gross, "costes": cost, "funding": fund, "neto": gross - cost - fund,
        "peor_excursion": w_fill,   # hasta que se ejecuta la salida (decide la liquidación)
        "peor_mecha": w_wick,       # incluida la mecha completa de la vela de salida (estrés)
        "distancia_stop": dist_rel,
    })


def simulate_trades_loop(bars: pd.DataFrame, ohlc: pd.DataFrame, sig: np.ndarray, atr_tf: pd.Series,
                         tf: pd.Timedelta, mgmt: Mgmt, costs: TradeCosts = TradeCosts(),
                         funding: pd.Series | None = None) -> pd.DataFrame:
    """Versión de referencia, explícita y lenta, de `simulate_trades` (se usa en los tests)."""
    o, h, lo, c = _ohlc_arrays(bars)
    n5 = len(o)
    rows = []
    busy_until = -1
    for e, d, atr_j in zip(*_entries(bars, ohlc, sig, atr_tf, tf)):
        if e <= busy_until:
            continue                                   # ya hay una operación abierta
        entry = o[e]
        dist = mgmt.k * atr_j
        stop = entry - d * dist
        be_level = entry + d * mgmt.be * dist if mgmt.be is not None else None
        trail_start = be_level if be_level is not None else entry + d * dist
        tp = entry + d * mgmt.tp_r * dist if mgmt.exit == "tp" else None
        be_price = entry * (1 + d * costs.be_offset)
        armed = trailing = False
        best, worst = entry, 0.0
        exit_px, code, exit_cost = None, -1, costs.taker + costs.slip
        last = min(e + mgmt.max_bars - 1, n5 - 1)
        for i in range(e, last + 1):
            adverse = (lo[i] / entry - 1) if d == 1 else (1 - h[i] / entry)
            if (lo[i] <= stop) if d == 1 else (h[i] >= stop):
                level = min(stop, o[i]) if d == 1 else max(stop, o[i])   # si abre ya pasado el stop, sale a la apertura
                through = max((level - lo[i]) if d == 1 else (h[i] - level), 0.0)
                exit_px = level - d * costs.overshoot * through
                code = 1 if (armed and stop == be_price) else (2 if trailing else 0)
                w_fill, w_wick = min(worst, d * (exit_px / entry - 1)), min(worst, adverse)
                break
            if tp is not None and ((h[i] >= tp) if d == 1 else (lo[i] <= tp)):
                exit_px, code, exit_cost = tp, 3, costs.maker
                w_fill = w_wick = min(worst, adverse)
                break
            worst = min(worst, adverse)
            # Actualizaciones que valen desde la vela siguiente
            best = max(best, c[i]) if d == 1 else min(best, c[i])
            if be_level is not None and not armed and ((h[i] >= be_level) if d == 1 else (lo[i] <= be_level)):
                armed = True
                stop = max(stop, be_price) if d == 1 else min(stop, be_price)
            if mgmt.exit == "trail" and not trailing and ((best >= trail_start) if d == 1 else (best <= trail_start)):
                trailing = True
            if trailing:
                candidate = best - d * dist
                floor = be_price if armed else stop
                candidate = max(candidate, floor) if d == 1 else min(candidate, floor)
                stop = max(stop, candidate) if d == 1 else min(stop, candidate)
        if exit_px is None:
            exit_px, code = c[i], 4
            w_fill = w_wick = worst
        rows.append((e, i, d, entry, exit_px, code, exit_cost, w_fill, w_wick, dist / entry))
        busy_until = i
    cols = list(zip(*rows)) if rows else [[]] * 10
    arr = [np.asarray(x) for x in cols]
    e, i, d = (x.astype(np.int64) for x in arr[:3])
    code = arr[5].astype(np.int64)
    return _frame(bars.index, e, i, d, *(x.astype(float) for x in arr[3:5]), code,
                  *(x.astype(float) for x in arr[6:]), costs=costs, funding=funding)


def _simulate_all(o, h, lo, c, e, d, atr_j, mgmt: Mgmt, costs: TradeCosts):
    """Simula cada candidata como si fuera la única, todas a la vez, avanzando vela a vela."""
    n5, M = len(o), len(e)
    lg = d == 1
    entry = o[e]
    dist = mgmt.k * atr_j
    stop = entry - d * dist
    has_be = mgmt.be is not None
    be_level = entry + d * (mgmt.be if has_be else 0.0) * dist
    trail_start = be_level if has_be else entry + d * dist
    tp = entry + d * mgmt.tp_r * dist
    use_tp, use_trail = mgmt.exit == "tp", mgmt.exit == "trail"
    be_price = entry * (1 + d * costs.be_offset)
    armed = np.zeros(M, bool)
    trailing = np.zeros(M, bool)
    best = entry.copy()
    worst = np.zeros(M)
    exit_i = np.full(M, -1, dtype=np.int64)
    exit_px = np.full(M, np.nan)
    code = np.full(M, -1, dtype=np.int64)
    exit_cost = np.full(M, costs.taker + costs.slip)
    w_fill = np.zeros(M)
    w_wick = np.zeros(M)
    last = np.minimum(e + mgmt.max_bars - 1, n5 - 1)
    act = np.arange(M)
    step = 0
    while len(act):
        i = e[act] + step
        oi, hi_, li, ci = o[i], h[i], lo[i], c[i]
        la = lg[act]
        adverse = np.where(la, li / entry[act] - 1, 1 - hi_ / entry[act])
        st = stop[act]
        hit = np.where(la, li <= st, hi_ >= st)
        if hit.any():
            q = act[hit]
            level = np.where(la[hit], np.minimum(st[hit], oi[hit]), np.maximum(st[hit], oi[hit]))
            through = np.maximum(np.where(la[hit], level - li[hit], hi_[hit] - level), 0.0)
            px = level - d[q] * costs.overshoot * through
            exit_px[q], exit_i[q] = px, i[hit]
            code[q] = np.where(armed[q] & (stop[q] == be_price[q]), 1, np.where(trailing[q], 2, 0))
            w_fill[q] = np.minimum(worst[q], d[q] * (px / entry[q] - 1))
            w_wick[q] = np.minimum(worst[q], adverse[hit])
        rest = ~hit
        if use_tp:
            th = rest & np.where(la, hi_ >= tp[act], li <= tp[act])
            if th.any():
                q = act[th]
                exit_px[q], exit_i[q], code[q], exit_cost[q] = tp[q], i[th], 3, costs.maker
                w_fill[q] = w_wick[q] = np.minimum(worst[q], adverse[th])
            rest &= ~th
        q = act[rest]
        lq = la[rest]
        worst[q] = np.minimum(worst[q], adverse[rest])
        cq = ci[rest]
        best[q] = np.where(lq, np.maximum(best[q], cq), np.minimum(best[q], cq))
        if has_be:
            arm = ~armed[q] & np.where(lq, hi_[rest] >= be_level[q], li[rest] <= be_level[q])
            if arm.any():
                qa = q[arm]
                armed[qa] = True
                stop[qa] = np.where(lg[qa], np.maximum(stop[qa], be_price[qa]), np.minimum(stop[qa], be_price[qa]))
        if use_trail:
            start = ~trailing[q] & np.where(lq, best[q] >= trail_start[q], best[q] <= trail_start[q])
            trailing[q[start]] = True
            qt = q[trailing[q]]
            if len(qt):
                lt = lg[qt]
                cand = best[qt] - d[qt] * dist[qt]
                floor = np.where(armed[qt], be_price[qt], stop[qt])
                cand = np.where(lt, np.maximum(cand, floor), np.minimum(cand, floor))
                stop[qt] = np.where(lt, np.maximum(stop[qt], cand), np.minimum(stop[qt], cand))
        ir = i[rest]
        tm = ir == last[q]
        if tm.any():
            qq = q[tm]
            exit_px[qq], exit_i[qq], code[qq] = cq[tm], ir[tm], 4
            w_fill[qq] = w_wick[qq] = worst[qq]
        finished = ~rest
        finished[np.flatnonzero(rest)[tm]] = True
        act = act[~finished]
        step += 1
    return exit_i, exit_px, code, exit_cost, w_fill, w_wick, dist / entry


def _one_at_a_time(e: np.ndarray, exit_i: np.ndarray) -> np.ndarray:
    """Marca las candidatas que se ejecutan: una operación abierta por activo."""
    take = np.zeros(len(e), bool)
    busy = -1
    for m, (ei, xi) in enumerate(zip(e.tolist(), exit_i.tolist())):
        if ei > busy:
            take[m] = True
            busy = xi
    return take


def simulate_trades(bars: pd.DataFrame, ohlc: pd.DataFrame, sig: np.ndarray, atr_tf: pd.Series,
                    tf: pd.Timedelta, mgmt: Mgmt, costs: TradeCosts = TradeCosts(),
                    funding: pd.Series | None = None) -> pd.DataFrame:
    """Simula las operaciones (sin apalancar) sobre velas de 5 minutos."""
    o, h, lo, c = _ohlc_arrays(bars)
    e, d, atr_j = _entries(bars, ohlc, sig, atr_tf, tf)
    exit_i, exit_px, code, exit_cost, w_fill, w_wick, dist_rel = _simulate_all(o, h, lo, c, e, d, atr_j, mgmt, costs)
    k = _one_at_a_time(e, exit_i)
    return _frame(bars.index, e[k], exit_i[k], d[k], o[e[k]], exit_px[k], code[k], exit_cost[k],
                  w_fill[k], w_wick[k], dist_rel[k], costs, funding)


# -------------------------------------------------------- cuenta apalancada
def liquidation_move(L, maintenance: float = 0.005):
    """Movimiento adverso del precio que liquida una posición a L× con margen aislado."""
    L = np.asarray(L, dtype=float)
    out = np.where(L > 1, (1 / np.maximum(L, 1.0) - maintenance) / (1 - maintenance), np.inf)
    return float(out) if out.ndim == 0 else out


def trade_leverage(trades: pd.DataFrame, L: float, risk: float | None = None):
    """Apalancamiento de cada operación: fijo (L) o, con `risk`, el que hace que tocar el stop
    inicial cueste `risk` del capital (riesgo fijo por operación), con tope en L."""
    if risk is None:
        return L
    return np.minimum(risk / trades["distancia_stop"].to_numpy(), L)


def trade_returns(trades: pd.DataFrame, L: float, maintenance: float = 0.005,
                  col: str = "peor_excursion", risk: float | None = None) -> np.ndarray:
    """Rentabilidad sobre el capital de la sub-cuenta de cada operación a L×.

    col="peor_excursion": liquidación si el precio llega al nivel de liquidación antes de
    ejecutarse la salida (protocolo). col="peor_mecha": estrés, como si el stop no se ejecutara
    hasta el extremo de la vela."""
    lev = trade_leverage(trades, L, risk)
    liq = trades[col].to_numpy() <= -liquidation_move(lev, maintenance)
    r = lev * trades["neto"].to_numpy()
    return np.where(liq, -1.0, np.maximum(r, -1.0))


def month_paths(trades_by_asset: dict[str, pd.DataFrame], L: float, months: np.ndarray,
                maintenance: float = 0.005, col: str = "peor_excursion",
                risk: float | None = None) -> list[dict]:
    """Capital relativo tras cada operación, mes a mes.

    Una sub-cuenta con margen aislado por activo. Cada mes natural empieza con el capital
    repartido a partes iguales (así se rellena una sub-cuenta liquidada). Devuelve, por mes,
    las horas de salida, el capital relativo (empieza en 1) y las liquidaciones."""
    n_assets = len(trades_by_asset)
    t, a, r = [], [], []
    for k, tr in enumerate(trades_by_asset.values()):
        t.append(_ns(tr["salida"]))
        a.append(np.full(len(tr), k))
        r.append(trade_returns(tr, L, maintenance, col, risk))
    t, a, r = np.concatenate(t), np.concatenate(a), np.concatenate(r)
    order = np.argsort(t, kind="stable")
    t, a, r = t[order], a[order], r[order]
    mkey = t.astype("datetime64[ns]").astype("datetime64[M]")
    out = []
    for m in np.asarray(months, dtype="datetime64[M]"):
        lo_, hi_ = np.searchsorted(mkey, m, "left"), np.searchsorted(mkey, m, "right")
        sub = [1.0 / n_assets] * n_assets
        vals = np.empty(hi_ - lo_ + 1)
        vals[0] = 1.0
        for q in range(lo_, hi_):
            sub[a[q]] *= 1 + r[q]
            vals[q - lo_ + 1] = sum(sub)
        out.append({"mes": m, "t": t[lo_:hi_], "capital": vals, "liq": int((r[lo_:hi_] <= -1.0).sum())})
    return out


def months_between(start: str, end: str) -> np.ndarray:
    return np.arange(np.datetime64(start, "M"), np.datetime64(end, "M") + 1)


def path_equity(paths: list[dict]) -> np.ndarray:
    """Capital encadenando los meses (empieza en 1)."""
    scale, chunks = 1.0, [np.array([1.0])]
    for p in paths:
        chunks.append(scale * p["capital"][1:])
        scale *= p["capital"][-1]
    return np.concatenate(chunks)


def path_curve(paths: list[dict]) -> pd.Series:
    """Serie temporal del capital (en cada salida de operación)."""
    eq = path_equity(paths)[1:]
    t = np.concatenate([p["t"] for p in paths]) if paths else np.array([], dtype=np.int64)
    return pd.Series(eq, index=pd.to_datetime(t, utc=True))


def max_drawdown(eq: np.ndarray) -> float:
    eq = np.asarray(eq, dtype=float)
    return float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else 0.0


def bootstrap_year(paths: list[dict], n_sims: int = 2000, seed: int = 0, months: int = 12) -> dict:
    """Años simulados juntando meses reales al azar (con reemplazo): conserva las rachas
    dentro de cada mes. Devuelve la peor caída, el multiplicador y las liquidaciones."""
    rng = np.random.default_rng(seed)
    vals = [p["capital"] for p in paths]
    liq = np.array([p["liq"] for p in paths])
    dd, mult, nliq = np.empty(n_sims), np.empty(n_sims), np.empty(n_sims, dtype=int)
    for s in range(n_sims):
        pick = rng.integers(0, len(vals), months)
        scale, chunks = 1.0, [np.array([1.0])]
        for j in pick:
            chunks.append(scale * vals[j][1:])
            scale *= vals[j][-1]
        eq = np.concatenate(chunks)
        dd[s], mult[s], nliq[s] = max_drawdown(eq), scale, liq[pick].sum()
    return {"caida": dd, "multiplicador": mult, "liquidaciones": nliq}


# ------------------------------------------------------------------ resumen
def summarize(trades: pd.DataFrame, years: float) -> dict:
    """Estadísticas por operación (sin apalancar)."""
    n = len(trades)
    if n == 0:
        return {"operaciones": 0}
    net = trades["neto"].to_numpy()
    sd = net.std(ddof=1) if n > 1 else np.nan
    dur = (trades["salida"] - trades["entrada"]).dt.total_seconds() / 3600
    motivo = trades["motivo"].value_counts(normalize=True)
    return {
        "operaciones": n,
        "por_año": n / years,
        "media_neta": net.mean(),
        "t": net.mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan,
        "media_bruta": trades["bruto"].mean(),
        "costes_medios": trades["costes"].mean(),
        "funding_medio": trades["funding"].mean(),
        "acierto": (net > 0).mean(),
        "ganancia_media": net[net > 0].mean() if (net > 0).any() else np.nan,
        "perdida_media": net[net <= 0].mean() if (net <= 0).any() else np.nan,
        "distancia_stop": trades["distancia_stop"].mean(),
        "duracion_h": dur.mean(),
        **{f"% {m}": motivo.get(m, 0.0) for m in REASONS},
    }
