"""Controles de protección ante caídas y apalancamiento máximo aceptable (BTC y ETH).

Regla de aceptación (fijada antes de ver resultados): un apalancamiento es aceptable si
  1) la peor caída histórica (mar 2018 – oct 2026) no supera el −50 %,
  2) en la simulación de 3 años la probabilidad de caer más de un 50 % es ≤ 5 %, y
  3) la probabilidad de alguna liquidación es ≤ 1 %.
Los parámetros de los controles se fijan por criterio, no optimizando sobre los datos.

Uso: python scripts/protection_analysis.py [--mc 400]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corrbot.leverage import bootstrap_paths, daily_funding, equity_metrics, month_starts  # noqa: E402
from corrbot.protect import Controls, prepare_asset, simulate_protected  # noqa: E402
from leverage_analysis import CFG, daily_bars, funding_series  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "proteccion"
START, EXAM, END = (pd.Timestamp(x, tz="UTC") for x in ["2018-03-05", "2025-01-01", "2026-10-21"])
LEVELS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
BASE = Controls()
ALL = dict(fast_vol=True, stop_k=3.0, dd_floor=0.40, strong_only=True)
VARIANTS = [
    BASE,
    BASE.with_(name="Volatilidad rápida", fast_vol=True),
    BASE.with_(name="Stop intradía (3σ)", stop_k=3.0),
    BASE.with_(name="Freno por caída (suelo −40 %)", dd_floor=0.40),
    BASE.with_(name="Freno con reinicio anual", dd_floor=0.40, dd_reset_days=365),
    BASE.with_(name="Apalancar solo con tendencia fuerte", strong_only=True),
    BASE.with_(name="Todo junto (freno permanente)", **ALL),
    BASE.with_(name="Todo junto (freno con reinicio anual)", **ALL, dd_reset_days=365),
    # Combinaciones elegidas DESPUÉS de ver los resultados anteriores (exploratorias: sesgo optimista).
    BASE.with_(name="Tendencia fuerte + freno con reinicio (a posteriori)", strong_only=True, dd_floor=0.40,
               dd_reset_days=365),
    BASE.with_(name="Tendencia fuerte + freno permanente (a posteriori)", strong_only=True, dd_floor=0.40),
]


def assets_full() -> tuple[list[dict], pd.DatetimeIndex]:
    out = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        bars = daily_bars(sym)
        a = prepare_asset(bars["close"], bars["low"], daily_funding(funding_series(sym), bars.index))
        keep = (bars.index >= START) & (bars.index <= END)
        out.append({k: v[keep] for k, v in a.items()})
        idx = bars.index[keep]
    return out, idx


def slice_assets(assets, idx, start, end):
    keep = (idx >= start) & (idx <= end)
    return [{k: v[keep] for k, v in a.items()} for a in assets], idx[keep]


def run(assets, idx, L, ctl) -> dict:
    res = simulate_protected(assets, L, ctl, CFG, month_starts(idx))
    m = equity_metrics(res["equity"], idx, res["liquidaciones"])
    m.update({"stops": res["stops"], "dias_en_suelo": res["dias_en_suelo"]})
    return m


def monte_carlo(assets, L, ctl, paths) -> dict:
    reb = np.zeros(3 * 365, dtype=bool)
    reb[::30] = True
    dd, liq, final = [], [], []
    for p in paths:
        res = simulate_protected(p, L, ctl, CFG, reb)
        eq = res["equity"]
        dd.append((eq / np.maximum.accumulate(eq) - 1).min())
        liq.append(res["liquidaciones"] > 0)
        final.append(eq[-1])
    dd, final = np.array(dd), np.array(final)
    return {"P(caída>50%)": (dd < -0.5).mean(), "P(liquidación)": np.mean(liq), "P(perder>90%)": (final < 0.1).mean(),
            "mediana_3a": np.median(final), "p10_3a": np.quantile(final, 0.10)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mc", type=int, default=400)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    assets, idx = assets_full()
    exam_assets, exam_idx = slice_assets(assets, idx, EXAM, END)
    rng = np.random.default_rng(7)
    paths = [bootstrap_paths(assets, 3 * 365, 30, rng) for _ in range(args.mc)]

    rows = []
    for ctl in VARIANTS:
        for L in LEVELS:
            hist = run(assets, idx, L, ctl)
            exam = run(exam_assets, exam_idx, L, ctl)
            mc = monte_carlo(assets, L, ctl, paths)
            rows.append({"variante": ctl.name, "apalancamiento": L, **{f"hist_{k}": v for k, v in hist.items()},
                         "examen_multiplicador": exam["multiplicador"], "examen_max_caida": exam["max_caida"], **mc})
            print(f"{ctl.name:40s} {L:4.1f}x  hist ×{hist['multiplicador']:9.2f} CAGR {hist['CAGR']:+.0%} "
                  f"caída {hist['max_caida']:.0%}  examen ×{exam['multiplicador']:.2f} ({exam['max_caida']:.0%})  "
                  f"P(caída>50%) {mc['P(caída>50%)']:.0%} P(liq) {mc['P(liquidación)']:.1%}", flush=True)
    tab = pd.DataFrame(rows)
    tab["aceptable"] = (tab["hist_max_caida"] >= -0.50) & (tab["P(caída>50%)"] <= 0.05) & (tab["P(liquidación)"] <= 0.01)
    tab.to_csv(OUT / "variantes_apalancamiento.csv", index=False, float_format="%.4f")

    best = []
    for name, g in tab.groupby("variante", sort=False):
        ok = g[g["aceptable"]]
        top = ok.loc[ok["apalancamiento"].idxmax()] if len(ok) else None
        row = ok.loc[ok["hist_CAGR"].idxmax()] if len(ok) else None   # el mejor aceptable por rentabilidad
        best.append({"variante": name,
                     "apalanc_max_aceptable": top["apalancamiento"] if top is not None else 0.0,
                     "apalanc_mejor_aceptable": row["apalancamiento"] if row is not None else 0.0,
                     "CAGR_hist": row["hist_CAGR"] if row is not None else np.nan,
                     "caida_hist": row["hist_max_caida"] if row is not None else np.nan,
                     "examen": row["examen_multiplicador"] - 1 if row is not None else np.nan,
                     "examen_caida": row["examen_max_caida"] if row is not None else np.nan,
                     "P(caída>50%)": row["P(caída>50%)"] if row is not None else np.nan,
                     "mediana_3a": row["mediana_3a"] if row is not None else np.nan})
    best = pd.DataFrame(best)
    best.to_csv(OUT / "apalancamiento_maximo_por_variante.csv", index=False, float_format="%.4f")
    print("\nApalancamiento máximo y mejor aceptable por variante:\n", best.round(3).to_string(index=False))

    # Sensibilidad de la combinación completa a sus parámetros (para ver robustez, no para elegir)
    sens = []
    small = paths[: max(100, args.mc // 2)]
    for stop_k in [2.0, 3.0, 4.0]:
        for floor in [0.30, 0.40]:
            for tv in [0.30, 0.40, 0.60]:
                ctl = BASE.with_(name="sens", fast_vol=True, strong_only=True, stop_k=stop_k, dd_floor=floor, target_vol=tv)
                for L in [2, 3, 5]:
                    hist = run(assets, idx, L, ctl)
                    mc = monte_carlo(assets, L, ctl, small)
                    sens.append({"stop_k": stop_k, "suelo": floor, "vol_objetivo": tv, "apalancamiento": L,
                                 "CAGR_hist": hist["CAGR"], "caida_hist": hist["max_caida"],
                                 "P(caída>50%)": mc["P(caída>50%)"], "P(liquidación)": mc["P(liquidación)"],
                                 "mediana_3a": mc["mediana_3a"]})
    pd.DataFrame(sens).to_csv(OUT / "sensibilidad_todo_junto.csv", index=False, float_format="%.4f")
    print("Sensibilidad guardada.")


if __name__ == "__main__":
    main()
