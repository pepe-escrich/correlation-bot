"""Validación de la estrategia A (tendencia) en el periodo de DESARROLLO (hasta 2024).

Aplica los criterios 1-5 del protocolo pre-registrado (docs/validacion_A_B.md).
El examen final (2025-2026) NO se toca aquí: está en scripts/final_exam.py.

Uso: python scripts/validate_a.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot.data import load_closes  # noqa: E402
from corrbot.trend import (  # noqa: E402
    backtest_position, block_bootstrap_max_dd, perf, random_trend_null, strategy_a, trend_exposure,
)

OUT = Path(__file__).resolve().parent.parent / "results" / "validacion"
DEV_END = pd.Timestamp("2024-12-31", tz="UTC")
COST = 0.0015
WINDOWS, TARGET_VOL, BAND = (50, 100, 200), 0.40, 0.10
OTHER_TOKENS = ["BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "LINK", "AVAX", "DOT", "LTC",
                "BCH", "XLM", "ATOM", "ETC", "NEAR", "UNI", "FIL", "AAVE"]


def daily_close(token: str) -> pd.Series:
    return load_closes([f"{token}USDT"], "1d").dropna().iloc[:, 0]


def dev_window(close: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    first = trend_exposure(close, WINDOWS).first_valid_index()
    return first + pd.Timedelta(days=1), DEV_END


def run_a(close: pd.Series, cost: float = COST, delay: int = 0, windows=WINDOWS,
          target_vol=TARGET_VOL) -> pd.DataFrame:
    return backtest_position(close, strategy_a(close, windows, target_vol, BAND), cost, delay)


def sl(s: pd.Series | pd.DataFrame, start, end):
    return s[(s.index >= start) & (s.index <= end)]


def hodl_ret(close: pd.Series) -> pd.Series:
    return close.pct_change().fillna(0.0)


def portfolio(rets: list[pd.Series]) -> pd.Series:
    """Cartera con el capital repartido a partes iguales y sin reequilibrar."""
    eqs = [(1 + r).cumprod() for r in rets]
    total = sum(eqs) / len(eqs)
    return total.pct_change().fillna(total.iloc[0] - 1)


def verdict(ok: bool) -> str:
    return "APRUEBA" if ok else "SUSPENDE"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    btc, eth = daily_close("BTC"), daily_close("ETH")
    start = max(dev_window(btc)[0], dev_window(eth)[0])
    print(f"Desarrollo: {start:%Y-%m-%d} → {DEV_END:%Y-%m-%d}\n")

    # ---------------------------------------------------------- criterio 1
    rows = {}
    a_btc, a_eth = run_a(btc), run_a(eth)
    series = {
        "A BTC": sl(a_btc["ret"], start, DEV_END), "HODL BTC": sl(hodl_ret(btc), start, DEV_END),
        "A ETH": sl(a_eth["ret"], start, DEV_END), "HODL ETH": sl(hodl_ret(eth), start, DEV_END),
    }
    series["A 50/50"] = portfolio([series["A BTC"], series["A ETH"]])
    series["HODL 50/50"] = portfolio([series["HODL BTC"], series["HODL ETH"]])
    for name, r in series.items():
        turnover = None
        if name == "A BTC":
            turnover = sl(a_btc["turnover"], start, DEV_END)
        elif name == "A ETH":
            turnover = sl(a_eth["turnover"], start, DEV_END)
        rows[name] = perf(r, turnover)
    c1 = pd.DataFrame(rows).T
    c1.to_csv(OUT / "A_c1_desarrollo.csv", float_format="%.4f")
    print(c1.round(3).to_string())
    ok1 = all(c1.loc[f"A {k}", "sharpe"] > c1.loc[f"HODL {k}", "sharpe"] and c1.loc[f"A {k}", "max_caida"] >= -0.50
              for k in ["BTC", "ETH", "50/50"])
    print(f"\nCriterio 1 (Sharpe > HODL y caída ≤ 50 % en BTC, ETH y 50/50): {verdict(ok1)}\n")

    # ---------------------------------------------------------- criterio 2
    grid_rows = []
    for token, close in [("BTC", btc), ("ETH", eth)]:
        hodl_sh = perf(sl(hodl_ret(close), start, DEV_END))["sharpe"]
        for n in [20, 30, 50, 75, 100, 150, 200]:
            for tv in [0.30, 0.40, 0.60, None]:
                r = sl(run_a(close, windows=(n,), target_vol=tv)["ret"], start, DEV_END)
                p = perf(r)
                grid_rows.append({"token": token, "media": n, "vol_objetivo": tv if tv else "sin",
                                  "sharpe": p["sharpe"], "max_caida": p["max_caida"], "CAGR": p["CAGR"],
                                  "supera_HODL": p["sharpe"] > hodl_sh})
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "A_c2_rejilla.csv", index=False, float_format="%.4f")
    share = grid.groupby("token")["supera_HODL"].mean()
    ok2 = bool((share >= 0.70).all())
    print("Criterio 2: % de combinaciones que superan el Sharpe de HODL:", share.round(2).to_dict(), "→", verdict(ok2))
    print("  peor caída de la rejilla:", grid.groupby("token")["max_caida"].min().round(2).to_dict(), "\n")

    # ---------------------------------------------------------- criterio 3
    null_rows = []
    for token, close, bt in [("BTC", btc, a_btc), ("ETH", eth, a_eth)]:
        actual = perf(sl(bt["ret"], start, DEV_END))["sharpe"]
        sims = random_trend_null(close, trend_exposure(close, WINDOWS), TARGET_VOL, BAND, COST,
                                 start, DEV_END, n_sims=1000, seed=1)
        null_rows.append({"token": token, "sharpe_real": actual, "azar_mediana": np.median(sims),
                          "azar_p95": np.quantile(sims, 0.95), "percentil": (sims < actual).mean()})
    null = pd.DataFrame(null_rows)
    null.to_csv(OUT / "A_c3_azar.csv", index=False, float_format="%.4f")
    ok3 = bool((null["percentil"] >= 0.95).all())
    print(null.round(3).to_string(index=False))
    print(f"Criterio 3 (timing mejor que el 95 % del azar): {verdict(ok3)}\n")

    # ---------------------------------------------------------- criterio 4
    tok_rows = []
    for token in OTHER_TOKENS:
        close = daily_close(token)
        t0, t1 = dev_window(close)
        if (t1 - t0).days < 365:
            continue
        pa = perf(sl(run_a(close)["ret"], t0, t1))
        ph = perf(sl(hodl_ret(close), t0, t1))
        tok_rows.append({"token": token, "desde": f"{t0:%Y-%m}", "sharpe_A": pa["sharpe"], "sharpe_HODL": ph["sharpe"],
                         "caida_A": pa["max_caida"], "caida_HODL": ph["max_caida"],
                         "CAGR_A": pa["CAGR"], "CAGR_HODL": ph["CAGR"]})
    toks = pd.DataFrame(tok_rows)
    toks["mejora_sharpe"] = toks.sharpe_A > toks.sharpe_HODL
    toks["reduce_caida"] = toks.caida_A > toks.caida_HODL
    toks.to_csv(OUT / "A_c4_otros_tokens.csv", index=False, float_format="%.4f")
    ok4 = toks.mejora_sharpe.mean() >= 2 / 3 and toks.reduce_caida.mean() >= 0.80
    print(toks.round(2).to_string(index=False))
    print(f"Criterio 4: mejora Sharpe en {toks.mejora_sharpe.sum()}/{len(toks)}, reduce caída en "
          f"{toks.reduce_caida.sum()}/{len(toks)} → {verdict(ok4)}\n")

    # ---------------------------------------------------------- criterio 5
    s_btc = sl(run_a(btc, cost=2 * COST, delay=1)["ret"], start, DEV_END)
    s_eth = sl(run_a(eth, cost=2 * COST, delay=1)["ret"], start, DEV_END)
    stress = perf(portfolio([s_btc, s_eth]))
    ok5 = stress["sharpe"] > c1.loc["HODL 50/50", "sharpe"] and stress["max_caida"] >= -0.50
    pd.DataFrame({"A 50/50 costes x2 + 1 día de retraso": stress}).T.to_csv(OUT / "A_c5_estres.csv", float_format="%.4f")
    print(f"Criterio 5 (costes x2 + retraso): Sharpe {stress['sharpe']:.2f} vs HODL {c1.loc['HODL 50/50', 'sharpe']:.2f}, "
          f"caída {stress['max_caida']:.1%} → {verdict(ok5)}\n")

    # ---------------------------------------------------------- informativo
    wf_rows = []
    for token, close in [("BTC", btc), ("ETH", eth)]:
        cands = {(n, tv): run_a(close, windows=(n,), target_vol=tv)["ret"]
                 for n in [20, 30, 50, 75, 100, 150, 200] for tv in [0.30, 0.40, 0.60, None]}
        ens = run_a(close)["ret"]
        for year in range(2021, 2025):
            tr0, tr1 = pd.Timestamp(f"{year - 3}-01-01", tz="UTC"), pd.Timestamp(f"{year - 1}-12-31", tz="UTC")
            te0, te1 = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year}-12-31", tz="UTC")
            best = max(cands, key=lambda c: perf(sl(cands[c], max(tr0, start), tr1))["sharpe"])
            wf_rows.append({"token": token, "año": year, "elegida": f"media {best[0]}, vol {best[1] or 'sin'}",
                            "rent_elegida": (1 + sl(cands[best], te0, te1)).prod() - 1,
                            "rent_conjunto_a_priori": (1 + sl(ens, te0, te1)).prod() - 1,
                            "rent_HODL": (1 + sl(hodl_ret(close), te0, te1)).prod() - 1})
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "A_info_walk_forward.csv", index=False, float_format="%.4f")
    print("Informativo - walk-forward (elegir la mejor media cada año) vs conjunto a priori:")
    print(wf.round(3).to_string(index=False))

    dd_a = block_bootstrap_max_dd(series["A 50/50"], seed=1)
    dd_h = block_bootstrap_max_dd(series["HODL 50/50"], seed=1)
    mc = pd.DataFrame({"A 50/50": {"P(caída>50% en 3 años)": (dd_a < -0.5).mean(), "caída mediana": np.median(dd_a),
                                   "caída p95": np.quantile(dd_a, 0.05)},
                       "HODL 50/50": {"P(caída>50% en 3 años)": (dd_h < -0.5).mean(), "caída mediana": np.median(dd_h),
                                      "caída p95": np.quantile(dd_h, 0.05)}}).T
    mc.to_csv(OUT / "A_info_montecarlo_caidas.csv", float_format="%.4f")
    print("\nInformativo - simulación de caídas en 3 años (bootstrap por bloques de 30 días):")
    print(mc.round(3).to_string())

    summary = pd.DataFrame({"criterio": ["1 desarrollo", "2 robustez", "3 azar", "4 otros tokens", "5 estrés"],
                            "resultado": [verdict(x) for x in [ok1, ok2, ok3, ok4, ok5]]})
    summary.to_csv(OUT / "A_resumen_desarrollo.csv", index=False)
    print("\nRESUMEN A (desarrollo):", dict(zip(summary.criterio, summary.resultado)))


if __name__ == "__main__":
    main()
