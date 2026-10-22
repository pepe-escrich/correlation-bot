"""Validación de la estrategia B (comprar caídas bruscas con tendencia alcista) en DESARROLLO.

Aplica los criterios 1-4 de B del protocolo pre-registrado (docs/validacion_A_B.md).
El examen final (2025-2026) está en scripts/final_exam.py.

Uso: python scripts/validate_b.py   (necesita velas de 5 min y funding descargados)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot.data import DATA_DIR, load_closes, load_klines  # noqa: E402
from corrbot.dips import DipCosts, DipParams, dip_trades, trade_stats, zscore_drop  # noqa: E402
from corrbot.trend import trend_exposure  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "validacion"
DEV_START = pd.Timestamp("2018-03-05", tz="UTC")
DEV_END = pd.Timestamp("2025-01-01", tz="UTC")       # exclusivo
A_PRIORI = DipParams(window_bars=48, k=3.0, hold_bars=48, trend_min=2 / 3)
COSTS = DipCosts()
OTHER = ["SOL", "BNB", "XRP", "DOGE", "ADA", "LINK"]
GRID_W, GRID_K, GRID_H, GRID_F = [12, 48, 144], [2.0, 2.5, 3.0], [12, 24, 48, 96], [2 / 3, None]


def bars(token: str) -> pd.DataFrame:
    return load_klines(f"{token}USDT", "5m")[["close", "low"]]


def funding(token: str) -> pd.Series | None:
    path = DATA_DIR.parent / "funding" / f"{token}USDT.parquet"
    return pd.read_parquet(path)["rate"] if path.exists() else None


def exposure(token: str) -> pd.Series:
    return trend_exposure(load_closes([f"{token}USDT"], "1d").dropna().iloc[:, 0])


def in_period(trades: pd.DataFrame, start, end) -> pd.DataFrame:
    return trades[(trades["entrada"] >= start) & (trades["entrada"] < end)]


def years(start, end) -> float:
    return (end - start).days / 365.25


def verdict(ok: bool) -> str:
    return "APRUEBA" if ok else "SUSPENDE"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {t: (bars(t), exposure(t), funding(t)) for t in ["BTC", "ETH"]}
    zs = {(t, w): zscore_drop(data[t][0]["close"].to_numpy(), w, 30) for t in data for w in GRID_W}

    def trades(token: str, p: DipParams, costs: DipCosts = COSTS) -> pd.DataFrame:
        b, e, f = data[token]
        return dip_trades(b, e, p, costs, f, z=zs[(token, p.window_bars)])

    # ------------------------------------------------------------ criterio 1
    both = pd.concat([trades(t, A_PRIORI) for t in data])
    dev = in_period(both, DEV_START, DEV_END)
    s1 = trade_stats(dev, years(DEV_START, DEV_END))
    per_year = dev.groupby(dev["entrada"].dt.year)["neto"].agg(["count", "mean", "sum"])
    per_year.to_csv(OUT / "B_c1_por_anio.csv", float_format="%.5f")
    ok1 = s1["neto_medio_pb"] > 0 and s1["t"] >= 2
    print(f"Criterio 1 (BTC+ETH, a priori): {s1['operaciones_año']:.1f} op/año, neto medio {s1['neto_medio_pb']:.1f} pb, "
          f"t = {s1['t']:.2f}, aciertos {s1['aciertos']:.0%} → {verdict(ok1)}")
    print(per_year.assign(mean=lambda x: x["mean"] * 1e4).rename(columns={"mean": "neto_medio_pb"}).round(2).to_string(), "\n")

    # Sensibilidad a costes (informativo)
    cost_rows = []
    for name, c in {"futuros límite+mercado (a priori)": COSTS,
                    "futuros todo a mercado": DipCosts(0.0005, 0.0005, 0.0004),
                    "spot límite+mercado": DipCosts(0.0008, 0.0010, 0.0002),
                    "sin costes": DipCosts(0.0, 0.0, 0.0)}.items():
        tr = in_period(pd.concat([trades(t, A_PRIORI, c) for t in data]), DEV_START, DEV_END)
        cost_rows.append({"costes": name, **trade_stats(tr, years(DEV_START, DEV_END))})
    costs_tab = pd.DataFrame(cost_rows)
    costs_tab.to_csv(OUT / "B_info_costes.csv", index=False, float_format="%.4f")
    print(costs_tab.round(3).to_string(index=False), "\n")

    # ------------------------------------------------------------ rejilla
    grid_rows, grid_trades = [], {}
    for w in GRID_W:
        for k in GRID_K:
            for h in GRID_H:
                for f in GRID_F:
                    p = DipParams(w, k, h, f)
                    tr = pd.concat([trades(t, p) for t in data])
                    grid_trades[p] = tr
                    st = trade_stats(in_period(tr, DEV_START, DEV_END), years(DEV_START, DEV_END))
                    grid_rows.append({"ventana_h": w / 12, "k": k, "salida_h": h / 12,
                                      "filtro": "sí" if f else "no", **st})
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "B_info_rejilla.csv", index=False, float_format="%.4f")
    print(f"Rejilla ({len(grid)} combinaciones): neto medio > 0 en {(grid.neto_medio_pb > 0).mean():.0%}, "
          f"t ≥ 2 en {(grid.t >= 2).mean():.0%}")

    # ------------------------------------------------------------ criterio 2
    wf_rows = []
    for year in range(2020, 2025):
        tr0, tr1 = pd.Timestamp(f"{year - 2}-01-01", tz="UTC"), pd.Timestamp(f"{year}-01-01", tz="UTC")
        te1 = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        best = max(grid_trades, key=lambda p: in_period(grid_trades[p], tr0, tr1)["neto"].sum())
        test = in_period(grid_trades[best], tr1, te1)
        wf_rows.append({"año": year, "elegida": f"{best.window_bars / 12:g}h, k={best.k}, salida {best.hold_bars / 12:g}h, "
                                               f"filtro {'sí' if best.trend_min else 'no'}",
                        "operaciones": len(test), "neto_total": test["neto"].sum()})
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "B_c2_walk_forward.csv", index=False, float_format="%.4f")
    ok2 = wf["neto_total"].sum() > 0
    print(wf.round(4).to_string(index=False))
    print(f"Criterio 2 (walk-forward 2020-2024): neto total {wf['neto_total'].sum():+.2%} → {verdict(ok2)}\n")

    # ------------------------------------------------------------ criterio 3
    no_filter = DipParams(A_PRIORI.window_bars, A_PRIORI.k, A_PRIORI.hold_bars, None)
    s_nf = trade_stats(in_period(pd.concat([trades(t, no_filter) for t in data]), DEV_START, DEV_END),
                       years(DEV_START, DEV_END))
    ok3 = s1["neto_medio_pb"] > s_nf["neto_medio_pb"]
    print(f"Criterio 3 (filtro): con filtro {s1['neto_medio_pb']:.1f} pb/op ({s1['operaciones_año']:.0f}/año) vs sin filtro "
          f"{s_nf['neto_medio_pb']:.1f} pb/op ({s_nf['operaciones_año']:.0f}/año) → {verdict(ok3)}\n")

    # ------------------------------------------------------------ criterio 4
    tok_rows = []
    for t in OTHER:
        b, e, f = bars(t), exposure(t), funding(t)
        tr = dip_trades(b, e, A_PRIORI, COSTS, f)
        start = max(DEV_START, b.index[0] + pd.Timedelta(days=30))
        d = in_period(tr, start, DEV_END)
        tok_rows.append({"token": t, "desde": f"{start:%Y-%m}", **trade_stats(d, years(start, DEV_END)),
                         "neto_total": d["neto"].sum()})
    toks = pd.DataFrame(tok_rows)
    toks.to_csv(OUT / "B_c4_otros_tokens.csv", index=False, float_format="%.4f")
    ok4 = (toks["neto_total"] > 0).sum() >= 4
    print(toks.round(3).to_string(index=False))
    print(f"Criterio 4 (neto positivo en ≥ 4 de 6): {(toks['neto_total'] > 0).sum()}/6 → {verdict(ok4)}\n")

    summary = pd.DataFrame({"criterio": ["1 desarrollo", "2 walk-forward", "3 filtro", "4 otros tokens"],
                            "resultado": [verdict(x) for x in [ok1, ok2, ok3, ok4]]})
    summary.to_csv(OUT / "B_resumen_desarrollo.csv", index=False)
    print("RESUMEN B (desarrollo):", dict(zip(summary.criterio, summary.resultado)))


if __name__ == "__main__":
    main()
