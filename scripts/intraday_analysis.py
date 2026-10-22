"""Estrategia intradía con stop escalonado y apalancamiento (protocolo: docs/intradia_10x.md).

1) Desarrollo (1-6-2018 → 31-12-2023): 96 configuraciones en BTC y ETH, y entradas al azar
   (20 semillas) con cada una de las 48 gestiones.
2) Selección fijada de antemano: mayor rentabilidad neta media por operación con ≥ 150 operaciones.
3) Criterios 1-3 en desarrollo; 4-5 en el examen (1-1-2024 → 21-10-2026), una sola vez.
4) Informativo, después del veredicto: breakeven, largos/cortos, BTC/ETH, años, barrido de
   apalancamiento, riesgo fijo por operación y las 96 configuraciones en el examen.

Uso:
  python scripts/intraday_analysis.py                     # protocolo original: velas de 5 min, señales 15m y 1h
  python scripts/intraday_analysis.py --velas 1m --temporalidades 15m,1h --sin-azar \
         --salida results/intradia_gestion_1min           # ampliación A: misma rejilla gestionada con velas de 1 min
  python scripts/intraday_analysis.py --velas 1m --temporalidades 1m,5m \
         --salida results/intradia_1min                   # ampliación B: señales en velas de 1 y 5 min
Opción --procesos N para repartir el trabajo entre varios núcleos (mismo resultado).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
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
RULES = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h"}
TFS = {"15m": "15min", "1h": "1h"}     # temporalidades de señal (se cambian con --temporalidades)
BAR_INTERVAL = "5m"                    # velas de gestión (se cambian con --velas)
BAR = pd.Timedelta(minutes=5)
WITH_RANDOM = True
PROCS = 1
_DATA: dict | None = None              # datos compartidos con los procesos hijos
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
        bars = load_klines(sym, BAR_INTERVAL)[["open", "high", "low", "close"]]
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
        tr = simulate_trades(d["bars"], t["ohlc"], sig, t["atr"], pd.Timedelta(TFS[tf]), m, COSTS, d["funding"],
                             bar=BAR)
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
def pmap(fn, tasks: list) -> list:
    """Aplica fn a cada tarea, en paralelo si --procesos > 1 (el orden se conserva)."""
    if PROCS <= 1:
        return [fn(t) for t in tasks]
    with multiprocessing.get_context("fork").Pool(PROCS) as pool:
        return pool.map(fn, tasks, chunksize=1)


def _dev_task(cfg) -> dict:
    tf, kind, m = cfg
    tr = run(_DATA, tf, kind, m, START, EXAM)
    return {"config": config_name(tf, kind, m), "temporalidad": tf, "entrada": ENTRIES[kind], "k": m.k,
            "breakeven": be_label(m.be), "be_paso": BES.index(m.be), "salida": EXITS[m.exit],
            **stats(tr, DEV_YEARS)}


def _random_task(task) -> dict:
    tf, m, seed = task
    tr = pooled(run(_DATA, tf, "random", m, START, EXAM, seed=seed))
    return {"temporalidad": tf, "k": m.k, "breakeven": be_label(m.be), "salida": EXITS[m.exit],
            "semilla": seed, "operaciones": len(tr), "media_neta": tr["neto"].mean(),
            "media_bruta": tr["bruto"].mean(), "media_neta_R": (tr["neto"] / tr["distancia_stop"]).mean()}


def _exam_task(cfg) -> dict:
    tf, kind, m = cfg
    s = stats(run(_DATA, tf, kind, m, EXAM, END), EXAM_YEARS)
    return {"config": config_name(tf, kind, m), "examen_operaciones": s["operaciones"],
            "examen_media_neta": s["media_neta"], "examen_media_bruta": s["media_bruta"], "examen_t": s["t"]}


def development() -> pd.DataFrame:
    return pd.DataFrame(pmap(_dev_task, list(all_configs())))


def random_null() -> pd.DataFrame:
    tasks = [(tf, Mgmt(k=k, be=be, exit=ex), seed) for tf in TFS for k in KS for be in BES for ex in EXITS
             for seed in range(SEEDS)]
    return pd.DataFrame(pmap(_random_task, tasks))


def neighbours(grid: pd.DataFrame, row: pd.Series) -> tuple[float, int]:
    """Fracción de vecinas con rentabilidad neta media positiva: misma entrada y temporalidad,
    stop y breakeven a un paso, ambas salidas."""
    k_step = {k: i for i, k in enumerate(KS)}
    same = grid[(grid["temporalidad"] == row["temporalidad"]) & (grid["entrada"] == row["entrada"])]
    near = ((same["k"].map(k_step) - k_step[row["k"]]).abs() <= 1) & \
           ((same["be_paso"] - row["be_paso"]).abs() <= 1) & (same["config"] != row["config"])
    nb = same[near]
    return float((nb["media_neta"] > 0).mean()), len(nb)


def parse_args() -> None:
    global TFS, BAR_INTERVAL, BAR, OUT, WITH_RANDOM, PROCS
    ap = argparse.ArgumentParser()
    ap.add_argument("--velas", choices=["5m", "1m"], default="5m", help="velas con las que se gestiona cada operación")
    ap.add_argument("--temporalidades", default="15m,1h", help="temporalidades de señal, separadas por comas")
    ap.add_argument("--salida", default=str(OUT.relative_to(ROOT)), help="carpeta de resultados")
    ap.add_argument("--sin-azar", action="store_true", help="no simular las entradas al azar (criterio 2 sin evaluar)")
    ap.add_argument("--procesos", type=int, default=1)
    args = ap.parse_args()
    TFS = {tf: RULES[tf] for tf in args.temporalidades.split(",")}
    BAR_INTERVAL, BAR = args.velas, pd.Timedelta(RULES[args.velas])
    OUT = ROOT / args.salida
    WITH_RANDOM = not args.sin_azar
    PROCS = args.procesos


def main() -> None:
    global _DATA
    parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    data = _DATA = prepare()
    print(f"velas de gestión {BAR_INTERVAL}, señales {list(TFS)}, salida {OUT}", flush=True)
    for asset, d in data.items():
        print(asset, {tf: round(v["p"], 4) for tf, v in d["tf"].items()}, "prob. de entrada al azar", flush=True)

    # 1) Desarrollo ------------------------------------------------------------
    grid = development()
    print(f"rejilla de desarrollo: {len(grid)} configuraciones ({time.time() - t0:.0f}s)", flush=True)
    if WITH_RANDOM:
        rand = random_null()
        rand.to_csv(OUT / "azar_desarrollo.csv", index=False)
        print(f"entradas al azar: {len(rand)} simulaciones ({time.time() - t0:.0f}s)", flush=True)
        keys = ["temporalidad", "k", "breakeven", "salida"]
        g = rand.groupby(keys)["media_neta"]
        ref = pd.DataFrame({"azar_mediana": g.median(), "azar_p95": g.quantile(0.95),
                            "azar_max": g.max()}).reset_index()
        grid = grid.merge(ref, on=keys, how="left")
        grid["fraccion_azar_por_debajo"] = [
            float((rand.loc[(rand[keys] == r[keys].to_numpy()).all(axis=1), "media_neta"] < r["media_neta"]).mean())
            for _, r in grid.iterrows()]
    else:
        grid["azar_p95"] = np.nan
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
        "2_mejor_que_azar_p95": bool(sel["media_neta"] > sel["azar_p95"]) if WITH_RANDOM else None,
        "3_vecinas_positivas>=50%": bool(sel["vecinas_positivas"] >= 0.5),
    }

    # 3) Examen, una sola vez con la configuración congelada ------------------
    # (las operaciones de desarrollo de la elegida y de sus variantes de breakeven se recalculan:
    #  la simulación es determinista)
    dev_family = {be: run(data, tf, kind, Mgmt(k=m.k, be=be, exit=m.exit), START, EXAM) for be in BES}
    dev_tr = dev_family[m.be]
    exam_tr = run(data, tf, kind, m, EXAM, END)
    exam_stats = stats(exam_tr, EXAM_YEARS)
    crit["4_examen_positiva"] = bool(exam_stats["media_neta"] > 0)
    lev = pd.DataFrame([leverage_row(dev_tr, exam_tr, L) for L in LEVELS_FINE])
    crit["5_riesgo_10x"] = bool(lev.loc[lev["apalancamiento"] == 10, "cumple_riesgo"].iloc[0])
    passing = lev.loc[lev["cumple_riesgo"], "apalancamiento"]
    verdict = {
        "seleccionada": sel["config"],
        "criterios": crit,
        "aprobada": all(v for v in crit.values() if v is not None),
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
        ex_tr = exam_tr if be == m.be else run(data, tf, kind, mb, EXAM, END)
        for period, tr, years in [("desarrollo", dev_family[be], DEV_YEARS), ("examen", ex_tr, EXAM_YEARS)]:
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
    rows = pmap(_exam_task, list(all_configs()))
    exam_grid = grid[["config", "temporalidad", "entrada", "k", "breakeven", "salida", "operaciones", "media_neta",
                      "media_bruta"]].merge(pd.DataFrame(rows), on="config")
    exam_grid.to_csv(OUT / "examen_rejilla.csv", index=False)
    print(f"examen de las 96 (informativo): {int((exam_grid['examen_media_neta'] > 0).sum())} positivas", flush=True)
    print(f"terminado en {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
