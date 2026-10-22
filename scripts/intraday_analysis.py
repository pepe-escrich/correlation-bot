"""Estrategia intradía con stop escalonado y apalancamiento (protocolo: docs/intradia_10x.md).

1) Desarrollo (1-6-2018 → 31-12-2023): 96 configuraciones en BTC y ETH, y entradas al azar
   (20 semillas) con cada una de las 48 gestiones.
2) Selección fijada de antemano: mayor rentabilidad neta media por operación con ≥ 150 operaciones.
3) Criterios 1-3 en desarrollo; 4-5 en el examen (1-1-2024 → 21-10-2026), una sola vez.
4) Informativo, después del veredicto: breakeven, largos/cortos, BTC/ETH, años, barrido de
   apalancamiento, riesgo fijo por operación y las 96 configuraciones en el examen.

Uso: python scripts/intraday_analysis.py   (~10 minutos)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corrbot.data import load_klines  # noqa: E402
from corrbot.intraday import (  # noqa: E402
    Mgmt, TradeCosts, atr, bootstrap_year, direction_allowed, max_drawdown, month_paths,
    months_between, path_curve, path_equity, resample_ohlc, signals, simulate_trades, summarize,
)
from corrbot.trend import trend_exposure  # noqa: E402

OUT = ROOT / "results" / "intradia"
FUNDING_DIR = ROOT / "data" / "funding"
ASSETS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
WARMUP, START, EXAM, END = (pd.Timestamp(x, tz="UTC") for x in
                            ["2018-03-01", "2018-06-01", "2024-01-01", "2026-10-22"])
DEV_MONTHS = months_between("2018-06", "2023-12")
EXAM_MONTHS = months_between("2024-01", "2026-10")
ALL_MONTHS = months_between("2018-06", "2026-10")
DEV_YEARS = (EXAM - START).days / 365.25
EXAM_YEARS = (END - EXAM).days / 365.25
TFS = {"15m": "15min", "1h": "1h"}
ENTRIES = {"breakout": "ruptura", "pullback": "retroceso"}
KS = [1.0, 2.0, 3.0]
BES = [0.5, 1.0, 2.0, None]            # orden de "vecinas": sin breakeven = breakeven en el infinito
EXITS = {"tp": "objetivo 3R", "trail": "stop que persigue"}
SEEDS = 20
MIN_TRADES = 150
LEVELS_FINE = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
CURVE_LEVELS = [1, 2, 3, 5, 10]
RISKS = [0.005, 0.01, 0.02]            # riesgo fijo por operación (informativo), con tope en 10x
N_BOOT = 2000
COSTS = TradeCosts()
DEFAULT_FUNDING_8H = 0.0001            # antes de 2020 (sin datos de perpetuos) y tras el último dato


def be_label(be: float | None) -> str:
    if be is None:
        return "sin breakeven"
    return f"breakeven a {f'{be:g}'.replace('.', ',')}R"


def config_name(tf: str, kind: str, m: Mgmt) -> str:
    return f"{tf} · {ENTRIES[kind]} · stop {m.k:g} ATR · {be_label(m.be)} · {EXITS[m.exit]}"


def all_configs():
    for tf in TFS:
        for kind in ENTRIES:
            for k in KS:
                for be in BES:
                    for ex in EXITS:
                        yield tf, kind, Mgmt(k=k, be=be, exit=ex)


# ------------------------------------------------------------------- datos
def funding_full(symbol: str) -> pd.Series:
    real = pd.read_parquet(FUNDING_DIR / f"{symbol}.parquet")["rate"]
    grid = pd.date_range(pd.Timestamp("2017-08-01", tz="UTC"), END, freq="8h")
    fill = pd.Series(DEFAULT_FUNDING_8H, index=grid)
    fill = fill[(fill.index < real.index[0]) | (fill.index > real.index[-1] + pd.Timedelta(hours=1))]
    return pd.concat([fill, real]).sort_index()


def prepare() -> dict:
    data = {}
    for asset, sym in ASSETS.items():
        bars = load_klines(sym, "5m")[["open", "high", "low", "close"]]
        bars = bars[(bars.index >= WARMUP) & (bars.index < END)]
        expo = trend_exposure(load_klines(sym, "1d")["close"])
        per_tf = {}
        for tf, rule in TFS.items():
            ohlc = resample_ohlc(bars, rule)
            allowed = direction_allowed(ohlc, expo)
            close_t = ohlc.index + pd.Timedelta(rule)
            dev = (close_t >= START) & (close_t < EXAM)
            sig = {kind: signals(ohlc, kind, allowed) for kind in ENTRIES}
            # Entradas al azar: misma probabilidad media que la ruptura (en desarrollo)
            p_rand = float((sig["breakout"][dev & (allowed != 0)] != 0).mean())
            per_tf[tf] = {"ohlc": ohlc, "atr": atr(ohlc), "allowed": allowed, "close_t": close_t,
                          "sig": sig, "p": p_rand}
        data[asset] = {"bars": bars, "funding": funding_full(sym), "tf": per_tf}
    return data


def run(data: dict, tf: str, kind: str, m: Mgmt, start, end, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Operaciones de cada activo con señal (cierre de vela) entre start y end."""
    out = {}
    for n_asset, (asset, d) in enumerate(data.items()):
        t = d["tf"][tf]
        if kind == "random":
            sig = signals(t["ohlc"], "random", t["allowed"], p=t["p"], seed=1000 * n_asset + seed)
        else:
            sig = t["sig"][kind]
        sig = np.where((t["close_t"] >= start) & (t["close_t"] < end), sig, 0)
        tr = simulate_trades(d["bars"], t["ohlc"], sig, t["atr"], pd.Timedelta(TFS[tf]), m, COSTS, d["funding"])
        tr["activo"] = asset
        out[asset] = tr
    return out


def pooled(trades: dict) -> pd.DataFrame:
    return pd.concat(trades.values(), ignore_index=True)


def stats(trades: dict, years: float) -> dict:
    allt = pooled(trades)
    s = summarize(allt, years)
    if len(allt):
        s["media_neta_R"] = (allt["neto"] / allt["distancia_stop"]).mean()
        s["media_bruta_R"] = (allt["bruto"] / allt["distancia_stop"]).mean()
        s["costes_y_funding_R"] = ((allt["costes"] + allt["funding"]) / allt["distancia_stop"]).mean()
    for asset, tr in trades.items():
        s[f"operaciones_{asset}"] = len(tr)
        s[f"media_neta_{asset}"] = tr["neto"].mean() if len(tr) else np.nan
    return s


# ------------------------------------------------------------------ cuenta
def account(trades: dict, L: float, months: np.ndarray, years: float, col: str = "peor_excursion",
            risk: float | None = None) -> tuple[list[dict], dict]:
    paths = month_paths(trades, L, months, col=col, risk=risk)
    eq = path_equity(paths)
    mult = float(eq[-1])
    return paths, {"multiplicador": mult, "CAGR": mult ** (1 / years) - 1 if mult > 0 else -1.0,
                   "max_caida": max_drawdown(eq), "liquidaciones": int(sum(p["liq"] for p in paths))}


def leverage_row(dev_tr: dict, exam_tr: dict, L: float, risk: float | None = None) -> dict:
    dev_paths, dv = account(dev_tr, L, DEV_MONTHS, DEV_YEARS, risk=risk)
    _, ex = account(exam_tr, L, EXAM_MONTHS, EXAM_YEARS, risk=risk)
    _, dv_s = account(dev_tr, L, DEV_MONTHS, DEV_YEARS, col="peor_mecha", risk=risk)
    _, ex_s = account(exam_tr, L, EXAM_MONTHS, EXAM_YEARS, col="peor_mecha", risk=risk)
    boot = bootstrap_year(dev_paths, N_BOOT, seed=0)
    p50 = float((boot["caida"] < -0.5).mean())
    row = {"apalancamiento": L, "riesgo_por_operacion": risk}
    row.update({f"des_{k}": v for k, v in dv.items()})
    row.update({f"exa_{k}": v for k, v in ex.items()})
    row["des_liquidaciones_estres"] = dv_s["liquidaciones"]
    row["exa_liquidaciones_estres"] = ex_s["liquidaciones"]
    row.update({"sim_P(caída>50%)": p50, "sim_P(liquidación)": float((boot["liquidaciones"] > 0).mean()),
                "sim_P(perder)": float((boot["multiplicador"] < 1).mean()),
                "sim_multiplicador_mediano": float(np.median(boot["multiplicador"]))})
    row["cumple_riesgo"] = bool(ex["max_caida"] >= -0.5 and ex["liquidaciones"] == 0 and p50 <= 0.05)
    return row


# --------------------------------------------------------------- desarrollo
def development(data: dict) -> tuple[pd.DataFrame, dict]:
    rows, trades = [], {}
    for tf, kind, m in all_configs():
        tr = run(data, tf, kind, m, START, EXAM)
        name = config_name(tf, kind, m)
        trades[name] = tr
        rows.append({"config": name, "temporalidad": tf, "entrada": ENTRIES[kind], "k": m.k,
                     "breakeven": be_label(m.be), "be_paso": BES.index(m.be), "salida": EXITS[m.exit],
                     **stats(tr, DEV_YEARS)})
    return pd.DataFrame(rows), trades


def random_null(data: dict) -> pd.DataFrame:
    rows = []
    for tf in TFS:
        for k in KS:
            for be in BES:
                for ex in EXITS:
                    m = Mgmt(k=k, be=be, exit=ex)
                    for seed in range(SEEDS):
                        tr = pooled(run(data, tf, "random", m, START, EXAM, seed=seed))
                        rows.append({"temporalidad": tf, "k": k, "breakeven": be_label(be), "salida": EXITS[ex],
                                     "semilla": seed, "operaciones": len(tr), "media_neta": tr["neto"].mean(),
                                     "media_bruta": tr["bruto"].mean(),
                                     "media_neta_R": (tr["neto"] / tr["distancia_stop"]).mean()})
    return pd.DataFrame(rows)


def neighbours(grid: pd.DataFrame, row: pd.Series) -> tuple[float, int]:
    """Fracción de vecinas con rentabilidad neta media positiva: misma entrada y temporalidad,
    stop y breakeven a un paso, ambas salidas."""
    k_step = {k: i for i, k in enumerate(KS)}
    same = grid[(grid["temporalidad"] == row["temporalidad"]) & (grid["entrada"] == row["entrada"])]
    near = ((same["k"].map(k_step) - k_step[row["k"]]).abs() <= 1) & \
           ((same["be_paso"] - row["be_paso"]).abs() <= 1) & (same["config"] != row["config"])
    nb = same[near]
    return float((nb["media_neta"] > 0).mean()), len(nb)


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    data = prepare()
    for asset, d in data.items():
        print(asset, {tf: round(v["p"], 4) for tf, v in d["tf"].items()}, "prob. de entrada al azar", flush=True)

    # 1) Desarrollo ------------------------------------------------------------
    grid, dev_trades = development(data)
    print(f"rejilla de desarrollo: {len(grid)} configuraciones ({time.time() - t0:.0f}s)", flush=True)
    rand = random_null(data)
    rand.to_csv(OUT / "azar_desarrollo.csv", index=False)
    print(f"entradas al azar: {len(rand)} simulaciones ({time.time() - t0:.0f}s)", flush=True)
    keys = ["temporalidad", "k", "breakeven", "salida"]
    g = rand.groupby(keys)["media_neta"]
    ref = pd.DataFrame({"azar_mediana": g.median(), "azar_p95": g.quantile(0.95), "azar_max": g.max()}).reset_index()
    grid = grid.merge(ref, on=keys, how="left")
    grid["fraccion_azar_por_debajo"] = [
        float((rand.loc[(rand[keys] == r[keys].to_numpy()).all(axis=1), "media_neta"] < r["media_neta"]).mean())
        for _, r in grid.iterrows()]
    nb = [neighbours(grid, r) for _, r in grid.iterrows()]
    grid["vecinas_positivas"] = [f for f, _ in nb]
    grid["n_vecinas"] = [n for _, n in nb]
    grid.to_csv(OUT / "desarrollo_rejilla.csv", index=False)

    # 2) Selección (regla fijada) ---------------------------------------------
    eligible = grid[grid["operaciones"] >= MIN_TRADES]
    sel = eligible.loc[eligible["media_neta"].idxmax()]
    tf = sel["temporalidad"]
    kind = {v: k for k, v in ENTRIES.items()}[sel["entrada"]]
    m = Mgmt(k=float(sel["k"]), be=BES[int(sel["be_paso"])], exit={v: k for k, v in EXITS.items()}[sel["salida"]])
    print("SELECCIONADA:", sel["config"], f"media neta {sel['media_neta']:.5f}, t {sel['t']:.2f}", flush=True)

    crit = {
        "1_desarrollo_positiva_t>=2": bool(sel["media_neta"] > 0 and sel["t"] >= 2),
        "2_mejor_que_azar_p95": bool(sel["media_neta"] > sel["azar_p95"]),
        "3_vecinas_positivas>=50%": bool(sel["vecinas_positivas"] >= 0.5),
    }

    # 3) Examen, una sola vez con la configuración congelada ------------------
    dev_tr = dev_trades[sel["config"]]
    exam_tr = run(data, tf, kind, m, EXAM, END)
    exam_stats = stats(exam_tr, EXAM_YEARS)
    crit["4_examen_positiva"] = bool(exam_stats["media_neta"] > 0)
    lev = pd.DataFrame([leverage_row(dev_tr, exam_tr, L) for L in LEVELS_FINE])
    crit["5_riesgo_10x"] = bool(lev.loc[lev["apalancamiento"] == 10, "cumple_riesgo"].iloc[0])
    passing = lev.loc[lev["cumple_riesgo"], "apalancamiento"]
    verdict = {
        "seleccionada": sel["config"],
        "criterios": crit,
        "aprobada": all(crit.values()),
        "apalancamiento_max_que_cumple_riesgo": float(passing.max()) if len(passing) else 0.0,
        "desarrollo": {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v)
                       for k, v in sel.items()},
        "examen": {k: float(v) for k, v in exam_stats.items()},
    }
    (OUT / "veredicto.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({"criterios": crit, "aprobada": verdict["aprobada"]}, ensure_ascii=False), flush=True)

    # 4) Informativo (después del veredicto) ----------------------------------
    risk_rows = [leverage_row(dev_tr, exam_tr, 10.0, risk=r) for r in RISKS]
    pd.concat([lev, pd.DataFrame(risk_rows)], ignore_index=True).to_csv(OUT / "apalancamiento.csv", index=False)

    # Efecto del breakeven: la misma configuración con cada opción de breakeven
    rows = []
    for be in BES:
        mb = Mgmt(k=m.k, be=be, exit=m.exit)
        name = config_name(tf, kind, mb)
        ex_tr = exam_tr if be == m.be else run(data, tf, kind, mb, EXAM, END)
        for period, tr, years in [("desarrollo", dev_trades[name], DEV_YEARS), ("examen", ex_tr, EXAM_YEARS)]:
            rows.append({"breakeven": be_label(be), "periodo": period, **stats(tr, years)})
    pd.DataFrame(rows).to_csv(OUT / "efecto_breakeven.csv", index=False)

    # Largos/cortos y BTC/ETH
    rows = []
    for period, trades, years in [("desarrollo", dev_tr, DEV_YEARS), ("examen", exam_tr, EXAM_YEARS)]:
        allt = pooled(trades)
        for label, part in [("largos", allt[allt["dir"] == 1]), ("cortos", allt[allt["dir"] == -1]),
                            ("BTC", allt[allt["activo"] == "BTC"]), ("ETH", allt[allt["activo"] == "ETH"])]:
            rows.append({"grupo": label, "periodo": period, **summarize(part, years)})
    pd.DataFrame(rows).to_csv(OUT / "lados_y_activos.csv", index=False)

    # Por año y curvas de capital (desarrollo + examen seguidos)
    both = {a: pd.concat([dev_tr[a], exam_tr[a]], ignore_index=True) for a in ASSETS}
    allt = pooled(both)
    year_rows = []
    curves = {}
    paths_by_level = {}
    for L in CURVE_LEVELS:
        paths, _ = account(both, L, ALL_MONTHS, DEV_YEARS + EXAM_YEARS)
        paths_by_level[L] = paths
        c = path_curve(paths)
        curves[f"{L}x"] = c.resample("1D").last().ffill()
    for year in range(2018, 2027):
        part = allt[allt["entrada"].dt.year == year]
        row = {"año": year, **summarize(part, 1.0)}
        for L, paths in paths_by_level.items():
            mult = np.prod([p["capital"][-1] for p in paths if str(p["mes"])[:4] == str(year)])
            row[f"rentabilidad_{L}x"] = mult - 1
        year_rows.append(row)
    pd.DataFrame(year_rows).to_csv(OUT / "por_año.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / "curvas.csv")

    # Las 96 configuraciones en el examen (solo informativo: no cambia la selección)
    rows = []
    for tf_, kind_, m_ in all_configs():
        name = config_name(tf_, kind_, m_)
        tr = exam_tr if name == sel["config"] else run(data, tf_, kind_, m_, EXAM, END)
        s = stats(tr, EXAM_YEARS)
        rows.append({"config": name, "examen_operaciones": s["operaciones"], "examen_media_neta": s["media_neta"],
                     "examen_media_bruta": s["media_bruta"], "examen_t": s["t"]})
    exam_grid = grid[["config", "temporalidad", "entrada", "k", "breakeven", "salida", "operaciones", "media_neta",
                      "media_bruta"]].merge(pd.DataFrame(rows), on="config")
    exam_grid.to_csv(OUT / "examen_rejilla.csv", index=False)
    print(f"examen de las 96 (informativo): {int((exam_grid['examen_media_neta'] > 0).sum())} positivas", flush=True)
    print(f"terminado en {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
