import numpy as np
import pandas as pd
import pytest

from corrbot.leverage import LevConfig, daily_funding, month_starts, simulate_portfolio

FREE = LevConfig(spot_cost=0.0, perp_cost=0.0, maintenance=0.0)


def _asset(r, r_low=None, e=None, f=None):
    r = np.asarray(r, dtype=float)
    return {"r": r, "r_low": np.minimum(r if r_low is None else np.asarray(r_low, float), r),
            "e": np.ones(len(r)) if e is None else np.asarray(e, float),
            "f": np.zeros(len(r)) if f is None else np.asarray(f, float)}


def test_zero_leverage_is_cash():
    a = _asset([0, 0.1, -0.2, 0.05])
    assert np.allclose(simulate_portfolio([a], 0.0, FREE)["equity"], 1.0)


def test_one_x_is_buy_and_hold():
    r = [0, 0.1, -0.2, 0.05]
    out = simulate_portfolio([_asset(r)], 1.0, FREE)["equity"]
    assert out[-1] == pytest.approx(1.1 * 0.8 * 1.05)


def test_two_x_daily_rebalanced_and_funding():
    r = [0, 0.1, -0.05]
    # Sin banda: rebalanceo diario exacto a 2x.
    cfg = LevConfig(spot_cost=0, perp_cost=0, maintenance=0, band=0.0)
    out = simulate_portfolio([_asset(r)], 2.0, cfg)["equity"]
    assert out[-1] == pytest.approx(1.2 * 0.9)
    f = [0, 0.001, 0.001]
    out_f = simulate_portfolio([_asset(r, f=f)], 2.0, cfg)["equity"]
    assert out_f[-1] < out[-1]          # el funding de los largos resta


def test_liquidation_wipes_subaccount():
    # 10x: una caída intradía del 10 % liquida aunque el cierre se recupere.
    r = [0, 0.0, 0.02, 0.05]
    r_low = [0, -0.11, 0.0, 0.0]
    res = simulate_portfolio([_asset(r, r_low)], 10.0, LevConfig(perp_cost=0, maintenance=0.005))
    assert res["liquidations"] == 1 and res["equity"][-1] == 0.0
    # Con 2x la misma mecha no liquida.
    res2 = simulate_portfolio([_asset(r, r_low)], 2.0, LevConfig(perp_cost=0, maintenance=0.005))
    assert res2["liquidations"] == 0 and res2["equity"][-1] > 1.0


def test_monthly_rebalance_refills_liquidated_subaccount():
    idx = pd.date_range("2021-01-30", periods=4, freq="1D", tz="UTC")
    reb = month_starts(idx)                       # 1 de febrero
    a = _asset([0, 0.0, 0.0, 0.0], [0, -0.5, 0, 0])   # se liquida el 31 de enero
    b = _asset([0, 0.0, 0.0, 0.10])
    res = simulate_portfolio([a, b], 3.0, LevConfig(perp_cost=0, maintenance=0.005), rebalance=reb)
    assert res["liquidations"] == 1
    # Tras la liquidación queda 0,5 de capital; el día 1 se reparte 0,25 a cada sub-cuenta
    # y B sube un 10 % con 3x: 0,25 + 0,25 × 1,3.
    assert res["equity"][-1] == pytest.approx(0.25 + 0.25 * 1.3, rel=1e-6)


def test_daily_funding_default_and_sum():
    idx = pd.date_range("2021-01-01", periods=2, freq="1D", tz="UTC")
    s = pd.Series([0.0001, 0.0002, 0.0003], index=pd.DatetimeIndex(
        ["2021-01-01 00:00", "2021-01-01 08:00", "2021-01-01 16:00"], tz="UTC"))
    out = daily_funding(s, idx, 0.0001)
    assert out[0] == pytest.approx(0.0006) and out[1] == pytest.approx(0.0003)
