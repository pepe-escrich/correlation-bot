"""Ampliación al top 10, con apalancamiento de 0x a 10x.

1) Top 10 ACTUAL por capitalización (CoinGecko, 22-10-2026, sin stablecoins ni activos
   tokenizados). Ojo: tiene sesgo de supervivencia (son los que han llegado arriba).
2) Top 10 "EN SU MOMENTO" por liquidez: cada mes, los 10 tokens con más volumen en
   Binance (USDT) en los 90 días anteriores, incluidos los que luego se hundieron o se
   deslistaron. Es la versión sin sesgo (no hay histórico gratuito de capitalización).

Uso: python scripts/top10_analysis.py   (requiere scripts/download_universe.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corrbot.data import DATA_DIR, load_klines  # noqa: E402
from corrbot.leverage import (  # noqa: E402
    asset_arrays, daily_funding, equity_metrics, month_starts, simulate_portfolio,
)
from leverage_analysis import CFG, LEVERAGES, exposure_a, funding_series  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "top10"
SNAPSHOT = OUT / "coingecko_top30_2026-10-22.json"
PERIODS = {"desarrollo": ("2019-01-01", "2024-12-31"), "examen": ("2025-01-01", "2026-10-21"),
           "completo": ("2019-01-01", "2026-10-21")}
MIN_HISTORY = 200   # días: lo que necesita la media de 200 de la estrategia A
VOLUME_DAYS = 90
NOT_CRYPTO = {"figr_heloc"}  # activo tokenizado (línea de crédito), no una cripto negociable
WRAPPED = {"wbtc", "steth", "wsteth", "weth", "weeth", "cbbtc", "wbeth", "reth", "meth", "lbtc", "bnsol"}
STABLE_OR_FIAT = {
    "USDC", "BUSD", "TUSD", "PAX", "USDP", "USDS", "USDSB", "FDUSD", "DAI", "EUR", "GBP", "AUD", "EURI",
    "AEUR", "XUSD", "USD1", "USDE", "PYUSD", "RLUSD", "BFUSD", "UST", "USTC", "GUSD", "SUSD", "PAXG",
    "XAUT", "WBTC", "WBETH", "BETH", "BKRW", "BVND", "IDRT", "BIDR", "BRL", "TRY", "RUB", "UAH", "NGN",
    "ZAR", "USDD", "FRAX", "LUSD", "EURC", "ARS", "MXN", "JPY", "PLN", "RON", "CZK", "USDQ", "U",
}
NOT_ON_OKX = {"ZEC", "XMR"}  # monedas de privacidad: OKX las deslistó en enero de 2024


# --------------------------------------------------------------- datos
def current_top10() -> list[str]:
    coins = json.loads(SNAPSHOT.read_text())
    picked = []
    for c in coins:
        sym = c["symbol"].lower()
        if sym in NOT_CRYPTO or sym in WRAPPED or sym.startswith("usd") or sym.endswith("usd") or sym == "dai":
            continue
        picked.append(sym.upper())
        if len(picked) == 10:
            break
    return picked


def segments(symbol: str) -> list[tuple[str, pd.DataFrame]]:
    """Velas diarias partidas en tramos si hay huecos > 7 días (un ticker reutilizado,
    como LUNA tras el hundimiento, es otro activo)."""
    k = load_klines(symbol, "1d")[["close", "low", "quote_volume"]]
    k = k[k["close"] > 0]
    gaps = np.flatnonzero(np.diff(k.index.values).astype("timedelta64[D]").astype(int) > 7)
    bounds = np.concatenate([[0], gaps + 1, [len(k)]])
    out = []
    for j, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        seg = k.iloc[a:b]
        grid = pd.date_range(seg.index[0], seg.index[-1], freq="1D")
        out.append((symbol if j == len(bounds) - 2 else f"{symbol}#{j + 1}", seg.reindex(grid).ffill()))
    return out


def eligible_symbol(symbol: str, bases: set[str]) -> bool:
    base = symbol[:-4]
    if base in STABLE_OR_FIAT:
        return False
    for suffix in ("UP", "DOWN", "BULL", "BEAR"):
        if base.endswith(suffix) and base[: -len(suffix)] in bases:
            return False        # tokens apalancados (BTCUP, ETHBEAR...)
    return True


def point_in_time_universe() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    files = sorted(p.stem for p in (DATA_DIR / "1d").glob("*USDT.parquet"))
    bases = {f[:-4] for f in files}
    segs: dict[str, pd.DataFrame] = {}
    for sym in files:
        if eligible_symbol(sym, bases):
            for name, df in segments(sym):
                segs[name] = df
    vol = pd.DataFrame({k: v["quote_volume"] for k, v in segs.items()})
    age = pd.DataFrame({k: pd.Series(np.arange(len(v)), index=v.index) for k, v in segs.items()})
    avg_vol = vol.rolling(f"{VOLUME_DAYS}D", min_periods=30).mean().shift(1)
    months = pd.date_range(PERIODS["completo"][0], PERIODS["completo"][1], freq="MS", tz="UTC")
    rows = []
    for m in months:
        day = m - pd.Timedelta(days=1)
        ok = (age.loc[day] >= MIN_HISTORY) & vol.loc[day - pd.Timedelta(days=4):day].notna().all()
        ranking = avg_vol.loc[m][ok[ok].index].dropna().sort_values(ascending=False)
        rows.append({"mes": m, **{f"#{i + 1}": s for i, s in enumerate(ranking.index[:10])}})
    return pd.DataFrame(rows).set_index("mes"), segs


# ------------------------------------------------------------ simulación
def assets_for(frames: dict[str, pd.DataFrame], strategy: str, index: pd.DatetimeIndex) -> list[dict]:
    out = []
    for name, df in frames.items():
        sym = name.split("#")[0]
        expo = exposure_a(df["close"]) if strategy == "A" else pd.Series(1.0, index=df.index)
        b = df.reindex(index)
        valid = b["close"].notna().to_numpy()
        b = b.ffill().bfill()
        fund = funding_series(sym) if "#" not in name else None
        arr = asset_arrays(b["close"], b["low"], expo.reindex(index).fillna(0.0),
                           daily_funding(fund, index, CFG.default_funding_8h))
        arr["e"] = np.where(valid, arr["e"], 0.0)
        out.append(arr)
    return out


def run_sweep(frames: dict[str, pd.DataFrame], members: pd.DataFrame, strategy: str, period: str) -> pd.DataFrame:
    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS[period])
    index = pd.date_range(start, end, freq="1D")
    assets = assets_for(frames, strategy, index)
    mem = members.reindex(index).fillna(False).to_numpy(dtype=bool)
    reb = month_starts(index)
    rows = []
    for L in LEVERAGES:
        res = simulate_portfolio(assets, L, CFG, rebalance=reb, members=mem)
        rows.append({"apalancamiento": L, **equity_metrics(res["equity"], index, res["liquidations"])})
    return pd.DataFrame(rows)


def equity_curve(frames, members, strategy, L=1.0) -> pd.Series:
    start, end = (pd.Timestamp(x, tz="UTC") for x in PERIODS["completo"])
    index = pd.date_range(start, end, freq="1D")
    res = simulate_portfolio(assets_for(frames, strategy, index), L, CFG, rebalance=month_starts(index),
                             members=members.reindex(index).fillna(False).to_numpy(dtype=bool))
    return pd.Series(res["equity"], index=index)


def max_leverage_within(tab: pd.DataFrame, limit: float = -0.50) -> tuple[float, float]:
    ok = tab[(tab["max_caida"] >= limit) & (tab["apalancamiento"] > 0)]
    if ok.empty:
        return 0.0, 0.0
    best = ok["apalancamiento"].max()
    return best, float(ok.loc[ok["apalancamiento"] == best, "CAGR"].iloc[0])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------- 1) top 10 actual (sesgado)
    top = current_top10()
    print("Top 10 actual por capitalización (sin stablecoins):", top)
    frames, rows = {}, []
    for t in top:
        sym = f"{t}USDT"
        if not (DATA_DIR / "1d" / f"{sym}.parquet").exists():
            rows.append({"token": t, "nota": "sin datos en Binance"})
            continue
        name, df = segments(sym)[-1]
        frames[t] = df
        first_ok = df.index[0] + pd.Timedelta(days=MIN_HISTORY)
        row = {"token": t, "datos_desde": f"{df.index[0]:%Y-%m}", "hasta": f"{df.index[-1]:%Y-%m}",
               "en_OKX": "no" if t in NOT_ON_OKX else "sí"}
        for strategy in ["A", "HODL"]:
            single = {t: df}
            mem = pd.DataFrame({t: (df.index >= first_ok)}, index=df.index)
            start = max(pd.Timestamp(PERIODS["completo"][0], tz="UTC"), first_ok)
            idx = pd.date_range(start, min(df.index[-1], pd.Timestamp(PERIODS["completo"][1], tz="UTC")), freq="1D")
            if len(idx) < 180:
                row["nota"] = "historia demasiado corta"
                continue
            tab = []
            for L in LEVERAGES:
                res = simulate_portfolio(assets_for(single, strategy, idx), L, CFG,
                                         rebalance=month_starts(idx), members=mem.reindex(idx).fillna(False).to_numpy())
                tab.append({"apalancamiento": L, **equity_metrics(res["equity"], idx, res["liquidations"])})
            tab = pd.DataFrame(tab)
            tab.to_csv(OUT / f"actual_{t}_{strategy}.csv", index=False, float_format="%.4f")
            one = tab[tab.apalancamiento == 1.0].iloc[0]
            row[f"CAGR_{strategy}_1x"] = one["CAGR"]
            row[f"caida_{strategy}_1x"] = one["max_caida"]
            row[f"sharpe_{strategy}_1x"] = one["sharpe"]
            lev, cagr = max_leverage_within(tab)
            row[f"apalanc_max_{strategy}_caida≤50%"] = lev
            row[f"CAGR_{strategy}_a_ese_apalanc"] = cagr
            row["desde_evaluacion"] = f"{start:%Y-%m}"
        rows.append(row)
    per_asset = pd.DataFrame(rows)
    per_asset.to_csv(OUT / "actual_por_token.csv", index=False, float_format="%.4f")
    print(per_asset.round(2).to_string(index=False))

    members_now = pd.DataFrame({t: pd.Series(True, index=df.index[MIN_HISTORY:]) for t, df in frames.items()})
    members_now = members_now.reindex(pd.date_range("2017-08-01", "2026-10-21", freq="1D", tz="UTC")).fillna(False)
    for strategy in ["A", "HODL"]:
        for period in PERIODS:
            tab = run_sweep(frames, members_now, strategy, period)
            tab.to_csv(OUT / f"actual_cartera_{strategy}_{period}.csv", index=False, float_format="%.4f")
            print(f"\n== Top 10 ACTUAL · cartera {strategy} · {period}")
            print(tab[tab.apalancamiento.isin([0, 0.5, 1, 1.5, 2, 3, 5, 10])].round(3).to_string(index=False))

    # ------------------- referencia: solo BTC y ETH en el mismo periodo (2019-2026)
    frames_be = {t: frames[t] for t in ["BTC", "ETH"]}
    members_be = members_now[["BTC", "ETH"]]
    for strategy in ["A", "HODL"]:
        for period in PERIODS:
            tab = run_sweep(frames_be, members_be, strategy, period)
            tab.to_csv(OUT / f"btc_eth_cartera_{strategy}_{period}.csv", index=False, float_format="%.4f")
            print(f"\n== Solo BTC y ETH · cartera {strategy} · {period}")
            print(tab[tab.apalancamiento.isin([0, 0.5, 1, 1.5, 2, 3, 5, 10])].round(3).to_string(index=False))

    # -------------------------------------- 2) top 10 en su momento (sin sesgo)
    membership, segs = point_in_time_universe()
    membership.to_csv(OUT / "pit_composicion_mensual.csv")
    used = sorted({s for row in membership.itertuples(index=False) for s in row if isinstance(s, str)})
    print(f"\nTop 10 en su momento: {len(used)} tokens distintos han formado parte:", used)
    frames_pit = {s: segs[s] for s in used}
    mem = pd.DataFrame(False, index=pd.date_range("2018-12-01", "2026-10-21", freq="1D", tz="UTC"), columns=used)
    for m, row in membership.iterrows():
        end = m + pd.offsets.MonthBegin(1)
        sel = [s for s in row if isinstance(s, str)]
        mem.loc[(mem.index >= m) & (mem.index < end), sel] = True
    for strategy in ["A", "HODL"]:
        for period in PERIODS:
            tab = run_sweep(frames_pit, mem, strategy, period)
            tab.to_csv(OUT / f"pit_cartera_{strategy}_{period}.csv", index=False, float_format="%.4f")
            print(f"\n== Top 10 EN SU MOMENTO · cartera {strategy} · {period}")
            print(tab[tab.apalancamiento.isin([0, 0.5, 1, 1.5, 2, 3, 5, 10])].round(3).to_string(index=False))
    curves = pd.DataFrame({
        "A top 10 en su momento": equity_curve(frames_pit, mem, "A"),
        "HODL top 10 en su momento": equity_curve(frames_pit, mem, "HODL"),
        "A top 10 actual": equity_curve(frames, members_now, "A"),
        "HODL top 10 actual": equity_curve(frames, members_now, "HODL"),
        "A solo BTC y ETH": equity_curve(frames_be, members_be, "A"),
        "HODL solo BTC y ETH": equity_curve(frames_be, members_be, "HODL"),
    })
    curves.to_csv(OUT / "curvas_1x.csv", float_format="%.5f")


if __name__ == "__main__":
    main()
