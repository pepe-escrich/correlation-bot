"""Análisis con apalancamiento de 0x a 10x (estrategia A, HODL y estrategias descartadas).

Uso: python scripts/leverage_analysis.py [--mc N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot.backtest import target_time_rule  # noqa: E402
from corrbot.data import DATA_DIR, load_klines  # noqa: E402
from corrbot.leverage import (  # noqa: E402
    LevConfig, asset_arrays, bootstrap_paths, daily_funding, equity_metrics, month_starts, simulate_portfolio,
)
from corrbot.trend import trend_exposure, vol_scale  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "apalancamiento"
LEVERAGES = [float(x) for x in np.arange(0, 10.01, 0.5)]
CFG = LevConfig()
PERIODS = {
    "desarrollo": ("2018-03-05", "2024-12-31"),
    "examen": ("2025-01-01", "2026-10-21"),
    "completo": ("2018-03-05", "2026-10-21"),
}


# ------------------------------------------------------------------ datos
def daily_bars(symbol: str) -> pd.DataFrame:
    k = load_klines(symbol, "1d")[["close", "low"]]
    grid = pd.date_range(k.index[0], k.index[-1], freq="1D")
    return k.reindex(grid).ffill(limit=3).dropna()


def funding_series(symbol: str) -> pd.Series | None:
    path = DATA_DIR.parent / "funding" / f"{symbol}.parquet"
    return pd.read_parquet(path)["rate"] if path.exists() else None


def exposure_a(close: pd.Series) -> pd.Series:
    """Exposición objetivo de A sin apalancar (la banda la aplica el simulador)."""
    return (trend_exposure(close) * vol_scale(close, 0.40)).fillna(0.0)


def build(symbols: list[str], strategy: str, index: pd.DatetimeIndex) -> list[dict[str, np.ndarray]]:
    out = []
    for sym in symbols:
        bars = daily_bars(sym)
        expo = exposure_a(bars["close"]) if strategy == "A" else pd.Series(1.0, index=bars.index)
        b = bars.reindex(index)
        valid = b["close"].notna().to_numpy()
        b = b.ffill().bfill()
        arr = asset_arrays(b["close"], b["low"], expo.reindex(index).fillna(0.0),
                           daily_funding(funding_series(sym), index, CFG.default_funding_8h))
        arr["e"] = np.where(valid, arr["e"], 0.0)
        out.append(arr)
    return out


def sweep(symbols: list[str], strategy: str, period: str, members: np.ndarray | None = None,
          index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS[period])
    if index is None:
        index = pd.date_range(start, end, freq="1D")
    assets = build(symbols, strategy, index)
    reb = month_starts(index)
    rows = []
    for L in LEVERAGES:
        res = simulate_portfolio(assets, L, CFG, rebalance=reb, members=members)
        rows.append({"apalancamiento": L, **equity_metrics(res["equity"], index, res["liquidations"])})
    return pd.DataFrame(rows)


def monte_carlo(symbols: list[str], strategy: str, levels: list[float], n_paths: int,
                horizon: int = 3 * 365, block: int = 30, seed: int = 0) -> pd.DataFrame:
    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS["completo"])
    index = pd.date_range(start, end, freq="1D")
    assets = build(symbols, strategy, index)
    rng = np.random.default_rng(seed)
    paths = [bootstrap_paths(assets, horizon, block, rng) for _ in range(n_paths)]
    reb = np.zeros(horizon, dtype=bool)
    reb[::30] = True
    rows = []
    for L in levels:
        dd, liq, final = [], [], []
        for p in paths:
            res = simulate_portfolio(p, L, CFG, rebalance=reb)
            eq = res["equity"]
            dd.append((eq / np.maximum.accumulate(eq) - 1).min())
            liq.append(res["liquidations"] > 0)
            final.append(eq[-1])
        dd, final = np.array(dd), np.array(final)
        rows.append({"apalancamiento": L, "P(caída>50%)": (dd < -0.5).mean(), "P(alguna liquidación)": np.mean(liq),
                     "P(perder >90%)": (final < 0.1).mean(), "mediana_multiplicador_3a": np.median(final),
                     "p10_multiplicador_3a": np.quantile(final, 0.10)})
    return pd.DataFrame(rows)


# --------------------------------------------------- estrategias descartadas
def rotation_sweep(period: str) -> pd.DataFrame:
    """Idea original (tras subida -> BTC, tras bajada -> ETH, velas diarias) apalancada."""
    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS[period])
    index = pd.date_range(start - pd.Timedelta(days=5), end, freq="1D")
    btc, eth = daily_bars("BTCUSDT").reindex(index).ffill(), daily_bars("ETHUSDT").reindex(index).ffill()
    tgt = target_time_rule(btc["close"].pct_change().fillna(0).to_numpy(), contrarian=True)
    held = np.concatenate([[tgt[0]], tgt[:-1]])            # 1 = ETH durante el día
    fb = daily_funding(funding_series("BTCUSDT"), index)
    fe = daily_funding(funding_series("ETHUSDT"), index)
    a_b = asset_arrays(btc["close"], btc["low"], pd.Series(1.0, index=index), fb)
    a_e = asset_arrays(eth["close"], eth["low"], pd.Series(1.0, index=index), fe)
    switch = np.concatenate([[0.0], np.abs(np.diff(held))])
    synth = {k: np.where(held == 1, a_e[k], a_b[k]) for k in ["r", "r_low", "f"]}
    synth["e"] = np.ones(len(index))
    rows = []
    for L in LEVERAGES:
        # Spot (L <= 1): una sola operación en el par ETH/BTC. Futuros: cerrar uno y abrir el otro.
        switch_cost = 2 * CFG.perp_cost if L > 1 else CFG.spot_cost
        s = dict(synth)
        s["r"] = synth["r"] - switch * switch_cost
        s["r_low"] = np.minimum(s["r_low"], s["r"])
        keep = index >= start
        s = {k: v[keep] for k, v in s.items()}
        res = simulate_portfolio([s], L, CFG, rebalance=month_starts(index[keep]))
        rows.append({"apalancamiento": L, **equity_metrics(res["equity"], index[keep], res["liquidations"])})
    return pd.DataFrame(rows)


def dips_sweep(period: str) -> pd.DataFrame:
    """Estrategia B (comprar caídas) apalancada: cada operación usa toda la sub-cuenta."""
    from corrbot.dips import DipCosts, DipParams, dip_trades

    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS[period])
    rows = []
    trades_all = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        bars = load_klines(sym, "5m")[["close", "low"]]
        daily = daily_bars(sym)["close"]
        tr = dip_trades(bars, trend_exposure(daily), DipParams(), DipCosts(), funding_series(sym))
        tr = tr[(tr["entrada"] >= start) & (tr["entrada"] <= end + pd.Timedelta(days=1))].copy()
        lows = bars["low"].to_numpy()
        pos_in = bars.index.get_indexer(tr["entrada"] - pd.Timedelta(minutes=5))
        pos_out = bars.index.get_indexer(tr["salida"] - pd.Timedelta(minutes=5))
        entry_px = (tr["bruto"].to_numpy() + 1) ** -1 * bars["close"].to_numpy()[pos_out]
        tr["peor"] = [lows[a:b + 1].min() / px - 1 for a, b, px in zip(pos_in, pos_out, entry_px)]
        tr["activo"] = sym
        trades_all.append(tr)
    trades = pd.concat(trades_all).sort_values("entrada")
    costs = DipCosts().total
    for L in LEVERAGES:
        sleeves = {}
        liqs = 0
        for sym, g in trades.groupby("activo"):
            eq = 1.0
            for _, t in g.iterrows():
                if L == 0:
                    continue
                if L > 1 and L * t["peor"] <= -(1 - CFG.maintenance * L):
                    eq, liqs = 0.0, liqs + 1
                    break
                eq *= 1 + L * (t["bruto"] - costs - t["funding"])
                if eq <= 0:
                    eq, liqs = 0.0, liqs + 1
                    break
            sleeves[sym] = eq
        final = np.mean(list(sleeves.values()))
        rows.append({"apalancamiento": L, "multiplicador": final, "liquidaciones": liqs,
                     "operaciones": len(trades)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mc", type=int, default=400, help="trayectorias del Monte Carlo")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = ["BTCUSDT", "ETHUSDT"]
    for period in PERIODS:
        for strategy in ["A", "HODL"]:
            for label, syms in [("BTC_ETH", pairs), ("BTC", ["BTCUSDT"]), ("ETH", ["ETHUSDT"])]:
                tab = sweep(syms, strategy, period)
                tab.to_csv(OUT / f"{label}_{strategy}_{period}.csv", index=False, float_format="%.4f")
                if label == "BTC_ETH":
                    show = tab[tab.apalancamiento.isin([0, 0.5, 1, 1.5, 2, 3, 5, 10])]
                    print(f"\n== {strategy} 50/50 BTC-ETH · {period}")
                    print(show.round(3).to_string(index=False))
    for strategy in ["A", "HODL"]:
        mc = monte_carlo(pairs, strategy, [0.5, 1, 1.5, 2, 3, 5, 10], args.mc)
        mc.to_csv(OUT / f"BTC_ETH_{strategy}_montecarlo.csv", index=False, float_format="%.4f")
        print(f"\n== Monte Carlo 3 años · {strategy} 50/50\n", mc.round(3).to_string(index=False))
    for period in ["desarrollo", "examen"]:
        rot = rotation_sweep(period)
        rot.to_csv(OUT / f"rotacion_idea_original_{period}.csv", index=False, float_format="%.4f")
        dips = dips_sweep(period)
        dips.to_csv(OUT / f"B_caidas_{period}.csv", index=False, float_format="%.4f")
        print(f"\n== Rotación original · {period}\n",
              rot[rot.apalancamiento.isin([0, 1, 2, 3, 5, 10])][["apalancamiento", "multiplicador", "CAGR", "max_caida", "liquidaciones"]].round(3).to_string(index=False))
        print(f"\n== B caídas · {period}\n", dips[dips.apalancamiento.isin([0, 1, 2, 3, 5, 10])].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
