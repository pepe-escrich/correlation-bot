import numpy as np
import pandas as pd
import pytest

from corrbot.dips import DipCosts, DipParams, dip_trades, filter_on_bars
from corrbot.trend import (
    apply_band, backtest_position, block_bootstrap_max_dd, perf, strategy_a, trend_exposure,
)


def _daily(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="1D", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_trend_exposure_rising_and_falling():
    up = _daily(np.linspace(100, 300, 300))
    down = _daily(np.linspace(300, 100, 300))
    e_up, e_down = trend_exposure(up), trend_exposure(down)
    assert e_up.iloc[:199].isna().all()            # sin la media de 200 no hay señal
    assert e_up.iloc[250] == 1.0 and e_down.iloc[250] == 0.0


def test_backtest_position_buy_and_hold_and_costs():
    close = _daily(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, 400))))
    full = backtest_position(close, pd.Series(1.0, index=close.index), cost=0.0)
    bh = close.iloc[-1] / close.iloc[0]
    assert (1 + full["ret"]).prod() == pytest.approx(bh)
    # Un único cambio de posición paga el coste una sola vez.
    pos = pd.Series(0.0, index=close.index)
    pos.iloc[100:] = 1.0
    with_cost = backtest_position(close, pos, cost=0.01)
    assert with_cost["turnover"].sum() == pytest.approx(1.0)


def test_no_lookahead_daily():
    rng = np.random.default_rng(5)
    close = _daily(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 3000))))
    cheat = (close.pct_change() > 0).astype(float)   # conoce la vela que ACABA de cerrar
    bt = backtest_position(close, cheat, cost=0.0)
    # Aplicada a la vela siguiente, en un paseo aleatorio no aporta nada.
    assert abs(perf(bt["ret"])["sharpe"]) < 1.0


def test_band_ignores_small_changes_but_always_exits():
    target = pd.Series([0.5, 0.55, 0.58, 0.7, 0.05, 0.0])
    assert list(apply_band(target, 0.10)) == [0.5, 0.5, 0.5, 0.7, 0.05, 0.0]


def test_strategy_a_bounds():
    rng = np.random.default_rng(2)
    close = _daily(100 * np.exp(np.cumsum(rng.normal(0.001, 0.04, 800))))
    pos = strategy_a(close)
    assert pos.min() >= 0.0 and pos.max() <= 1.0


def _bars(prices, lows=None):
    idx = pd.date_range("2021-01-01", periods=len(prices), freq="5min", tz="UTC")
    prices = np.asarray(prices, dtype=float)
    return pd.DataFrame({"close": prices, "low": prices if lows is None else lows}, index=idx)


def test_dip_trade_needs_limit_fill_and_respects_filter():
    n = 40 * 288
    rng = np.random.default_rng(3)
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
    p[n - 500:n - 452] *= np.linspace(1.0, 0.90, 48)       # caída brusca de 4 h
    p[n - 452:] *= 0.90
    bars = _bars(p)
    days = pd.date_range("2020-12-01", periods=80, freq="1D", tz="UTC")
    params = DipParams()
    up = pd.Series(1.0, index=days)
    trades = dip_trades(bars, up, params, DipCosts())
    assert len(trades) >= 1
    assert (trades["salida"] - trades["entrada"] >= pd.Timedelta(hours=4)).all()
    # Sin tendencia alcista no se opera.
    assert dip_trades(bars, pd.Series(0.0, index=days), params, DipCosts()).empty
    # Si el precio nunca vuelve a tocar el nivel de la orden límite, no hay operación.
    lows = p.copy()
    lows[1:] = np.maximum(p[1:], p[:-1] * 1.0001)
    assert dip_trades(_bars(p, lows), up, params, DipCosts()).empty


def test_filter_uses_previous_day():
    days = pd.date_range("2021-01-01", periods=3, freq="1D", tz="UTC")
    exp = pd.Series([0.0, 1.0, 0.0], index=days)
    bars_idx = pd.DatetimeIndex([pd.Timestamp("2021-01-02 12:00", tz="UTC"),
                                 pd.Timestamp("2021-01-03 00:00", tz="UTC")])
    # El día 2 a mediodía solo se conoce la señal del día 1 (0); el día 3 la del día 2 (1).
    assert list(filter_on_bars(exp, bars_idx)) == [0.0, 1.0]


def test_block_bootstrap_range():
    r = pd.Series(np.random.default_rng(0).normal(0.001, 0.03, 1000))
    dd = block_bootstrap_max_dd(r, horizon_days=365, n_sims=50)
    assert (dd <= 0).all() and (dd >= -1).all()
