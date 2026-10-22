import numpy as np
import pandas as pd
import pytest

from corrbot.intraday import (
    Mgmt, TradeCosts, atr, bootstrap_year, liquidation_move, max_drawdown, month_paths, path_equity,
    resample_ohlc, signals, simulate_trades, simulate_trades_loop, trade_returns,
)

TF = pd.Timedelta(minutes=15)
COSTS = TradeCosts()


def _run(path, d=1, mgmt=Mgmt(k=1.0, be=1.0, exit="tp"), atr_value=2.0, lows=None, highs=None,
         funding=None, sim=simulate_trades, opens=None):
    """Una señal en la vela de 15 min que cierra a las 00:15; la operación entra a 100 en la
    vela de 5 min de las 00:15 y sigue el camino de precios indicado (cierres)."""
    n = len(path)
    t5 = pd.date_range("2024-01-01 00:15", periods=n, freq="5min", tz="UTC")
    close = np.asarray(path, dtype=float)
    opens = np.concatenate([[100.0], close[:-1]]) if opens is None else np.asarray(opens, float)
    lo = np.minimum(opens, close) if lows is None else np.asarray(lows, float)
    hi = np.maximum(opens, close) if highs is None else np.asarray(highs, float)
    bars = pd.DataFrame({"open": opens, "high": hi, "low": lo, "close": close}, index=t5)
    ohlc = pd.DataFrame({"close": [100.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00", tz="UTC")]))
    sig = np.array([d])
    a = pd.Series([atr_value], index=ohlc.index)
    return sim(bars, ohlc, sig, a, TF, mgmt, COSTS, funding)


@pytest.fixture(params=[simulate_trades, simulate_trades_loop], ids=["rapida", "referencia"])
def sim(request):
    return request.param


def test_initial_stop_with_overshoot(sim):
    t = _run([99.5, 99.0, 97.0, 96.0], lows=[99.0, 98.5, 97.0, 95.0], sim=sim).iloc[0]
    assert t["motivo"] == "stop"
    # Stop a 98 (1 × ATR 2); la vela baja a 97: se pierde además un 10 % de 1 → 97,9.
    assert t["precio_salida"] == pytest.approx(97.9)
    assert t["peor_excursion"] == pytest.approx(-0.021)
    assert t["peor_mecha"] == pytest.approx(-0.03)


def test_gap_through_stop_exits_at_open(sim):
    t = _run([99.5, 95.0], opens=[100.0, 96.0], lows=[99.0, 94.0], highs=[100.0, 96.0], sim=sim).iloc[0]
    # Abre a 96 (por debajo del stop de 98): sale a la apertura menos el 10 % de lo que baja después.
    assert t["motivo"] == "stop" and t["precio_salida"] == pytest.approx(96.0 - 0.2)


def test_breakeven_after_one_r(sim):
    t = _run([101.0, 102.5, 101.0, 99.0, 98.0], sim=sim).iloc[0]
    assert t["motivo"] == "breakeven"
    be = 100 * (1 + COSTS.be_offset)
    assert 99.8 < t["precio_salida"] <= be
    assert t["neto"] == pytest.approx(t["bruto"] - t["costes"])


def test_take_profit_at_three_r(sim):
    t = _run([101, 102, 103, 104, 105, 106.5], sim=sim).iloc[0]
    assert t["motivo"] == "objetivo" and t["precio_salida"] == pytest.approx(106.0)
    assert t["costes"] == pytest.approx(COSTS.taker + COSTS.slip + COSTS.maker)


def test_ambiguous_bar_counts_stop_first(sim):
    t = _run([100.0, 100.0], lows=[97.0, 100.0], highs=[107.0, 100.0], sim=sim).iloc[0]
    assert t["motivo"] == "stop"


def test_breakeven_starts_on_next_bar(sim):
    # Vela 1: toca +1R (102) y baja a 99,5, por debajo del breakeven: aún no cuenta.
    # Vela 2: baja a 99,9 → ahora sí sale en breakeven.
    t = _run([100.5, 100.0], lows=[99.5, 99.9], highs=[102.5, 101.0], sim=sim).iloc[0]
    assert t["motivo"] == "breakeven"
    assert t["salida"] == pd.Timestamp("2024-01-01 00:25", tz="UTC")


def test_trailing_stop_locks_profit(sim):
    path = [101, 102, 103, 104, 105, 106, 107, 108, 105.5]
    t = _run(path, mgmt=Mgmt(k=1.0, be=1.0, exit="trail"), sim=sim).iloc[0]
    # Mejor cierre 108, distancia 2 → stop a 106; la última vela baja a 105,5.
    assert t["motivo"] == "stop que persigue"
    assert 105.8 < t["precio_salida"] <= 106.0


def test_short_mirror(sim):
    t = _run([99, 98, 97, 96, 95, 93.5], d=-1, sim=sim).iloc[0]
    assert t["dir"] == -1 and t["motivo"] == "objetivo" and t["precio_salida"] == pytest.approx(94.0)
    assert t["bruto"] == pytest.approx(0.06)


def test_time_exit_after_24h(sim):
    t = _run([100.2] * 300, mgmt=Mgmt(k=1.0, be=None, exit="tp", max_hours=24), sim=sim).iloc[0]
    assert t["motivo"] == "tiempo"
    assert t["salida"] - t["entrada"] == pd.Timedelta(hours=24)


def test_funding_sign(sim):
    fund = pd.Series([0.001], index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:30", tz="UTC")]))
    long_ = _run([100.0] * 12, mgmt=Mgmt(k=1.0, be=None, max_hours=1), funding=fund, sim=sim).iloc[0]
    short = _run([100.0] * 12, d=-1, mgmt=Mgmt(k=1.0, be=None, max_hours=1), funding=fund, sim=sim).iloc[0]
    assert long_["funding"] == pytest.approx(0.001) and short["funding"] == pytest.approx(-0.001)
    assert long_["neto"] == pytest.approx(-long_["costes"] - 0.001)


def _synthetic(n=12_000, seed=1):
    rng = np.random.default_rng(seed)
    t5 = pd.date_range("2023-01-01", periods=n, freq="5min", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    opens = np.concatenate([[100.0], close[:-1]])
    wick = np.abs(rng.normal(0, 0.002, (2, n)))
    bars = pd.DataFrame({"open": opens, "high": np.maximum(opens, close) * (1 + wick[0]),
                         "low": np.minimum(opens, close) * (1 - wick[1]), "close": close}, index=t5)
    bars = bars.drop(bars.index[5000:5030])                 # hueco en los datos
    fund = pd.Series(rng.normal(0.0001, 0.0003, n // 96 + 1),
                     index=pd.date_range("2023-01-01", periods=n // 96 + 1, freq="8h", tz="UTC"))
    return bars, fund


@pytest.mark.parametrize("tf", ["15min", "1h"])
def test_fast_simulator_matches_reference(tf):
    bars, fund = _synthetic()
    ohlc = resample_ohlc(bars, tf)
    a = atr(ohlc)
    allowed = np.where((np.arange(len(ohlc)) // 200) % 2 == 0, 1, -1)
    sig = signals(ohlc, "random", allowed, p=0.15, seed=3)
    tf_ = pd.Timedelta(tf)
    n_total = 0
    for k in (1.0, 2.0, 3.0):
        for be in (0.5, 1.0, 2.0, None):
            for ex in ("tp", "trail"):
                m = Mgmt(k=k, be=be, exit=ex)
                fast = simulate_trades(bars, ohlc, sig, a, tf_, m, COSTS, fund)
                ref = simulate_trades_loop(bars, ohlc, sig, a, tf_, m, COSTS, fund)
                pd.testing.assert_frame_equal(fast, ref)
                n_total += len(fast)
                assert set(fast["dir"]) == {-1, 1}
    assert n_total > 1000


def test_no_trade_entering_in_a_gap():
    bars, _ = _synthetic()
    ohlc = resample_ohlc(bars, "15min")
    sig = np.ones(len(ohlc), dtype=int)
    tr = simulate_trades(bars, ohlc, sig, atr(ohlc), TF, Mgmt(k=1.0, be=None, max_hours=1))
    # Cada entrada coincide con el cierre de una vela de señal (nunca dentro del hueco).
    assert tr["entrada"].isin(ohlc.index + TF).all()
    assert (tr["entrada"].iloc[1:].to_numpy() >= tr["salida"].iloc[:-1].to_numpy()).all()


def test_liquidation_depends_on_leverage_and_fill():
    trades = pd.DataFrame({"neto": [0.01, -0.012], "peor_excursion": [-0.10, -0.012],
                           "peor_mecha": [-0.10, -0.12]})
    r10 = trade_returns(trades, 10.0)
    assert r10[0] == -1.0 and r10[1] == pytest.approx(-0.12)
    # Estrés: si el stop no se ejecutara hasta el extremo de la vela, la segunda también se liquida.
    assert trade_returns(trades, 10.0, col="peor_mecha")[1] == -1.0
    assert trade_returns(trades, 5.0)[0] == pytest.approx(0.05)
    assert liquidation_move(10.0) == pytest.approx((0.1 - 0.005) / 0.995)
    assert np.isinf(liquidation_move(1.0))


def test_fixed_risk_sizing():
    trades = pd.DataFrame({"neto": [-0.0055, 0.01], "peor_excursion": [-0.0055, -0.001],
                           "distancia_stop": [0.005, 0.0005]})
    r = trade_returns(trades, 10.0, risk=0.01)
    # Stop al 0,5 % → 2x (pierde ~1,1 %); stop al 0,05 % → 20x, con tope en 10x.
    assert r[0] == pytest.approx(2 * -0.0055) and r[1] == pytest.approx(10 * 0.01)


def test_breakout_signal_uses_only_past_bars():
    idx = pd.date_range("2024-01-01", periods=25, freq="15min", tz="UTC")
    close = pd.Series(np.linspace(100, 101, 25), index=idx)
    ohlc = pd.DataFrame({"open": close, "high": close + 0.1, "low": close - 0.1, "close": close})
    allowed = np.ones(25, dtype=int)
    # Cierre de la última vela por debajo del máximo previo (máximo = cierre previo + 0,1): sin señal.
    assert signals(ohlc, "breakout", allowed)[-1] == 0
    ohlc.iloc[-1, ohlc.columns.get_loc("close")] = 102
    assert signals(ohlc, "breakout", allowed)[-1] == 1


def test_month_paths_refill_after_liquidation():
    t_btc = pd.DataFrame({"salida": [pd.Timestamp("2024-01-30 12:00", tz="UTC")], "neto": [0.0],
                          "peor_excursion": [-0.2]})
    t_eth = pd.DataFrame({"salida": [pd.Timestamp("2024-02-02 12:00", tz="UTC")], "neto": [0.02],
                          "peor_excursion": [-0.01]})
    months = np.array(["2024-01", "2024-02"], dtype="datetime64[M]")
    paths = month_paths({"BTC": t_btc, "ETH": t_eth}, 10.0, months)
    assert [p["liq"] for p in paths] == [1, 0]
    eq = path_equity(paths)
    # BTC se liquida (0,5 → 0); el 1 de febrero se reparte 0,25 a cada uno; ETH gana 10 × 2 %.
    assert eq[-1] == pytest.approx(0.25 + 0.25 * 1.2)
    assert max_drawdown(eq) == pytest.approx(-0.5)


def test_bootstrap_year_constant_months():
    paths = [{"capital": np.array([1.0, 0.9, 1.1]), "liq": 0}, {"capital": np.array([1.0, 1.0]), "liq": 1}]
    out = bootstrap_year(paths, n_sims=200, seed=0, months=12)
    assert ((out["multiplicador"] > 0.99) & (out["multiplicador"] < 1.1 ** 12 + 1e-9)).all()
    assert (out["caida"] <= 0).all() and (out["caida"] >= -0.1 - 1e-12).all()
    assert out["liquidaciones"].max() <= 12
