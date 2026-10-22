import numpy as np
import pandas as pd
import pytest

from corrbot.leverage import LevConfig, asset_arrays, month_starts, simulate_portfolio
from corrbot.protect import Controls, prepare_asset, simulate_protected
from corrbot.trend import trend_exposure, vol_scale


def _market(seed=0, n=900, drift=0.0015, sigma=0.035):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, sigma, n))), index=idx)
    low = close * (1 - np.abs(rng.normal(0, sigma / 2, n)))
    return close, low


def _assets(seeds=(0, 1)):
    out_p, out_old, idx = [], [], None
    for s in seeds:
        close, low = _market(seed=s)
        idx = close.index
        f = np.full(len(close), 0.0003)
        out_p.append(prepare_asset(close, low, f))
        e = (trend_exposure(close) * vol_scale(close, 0.40)).fillna(0.0)
        out_old.append(asset_arrays(close, low, e, f))
    return out_p, out_old, idx


@pytest.mark.parametrize("L", [0.5, 1.0, 3.0])
def test_without_controls_matches_previous_simulator(L):
    new, old, idx = _assets()
    reb = month_starts(idx)
    a = simulate_protected(new, L, Controls(), LevConfig(), reb)["equity"]
    b = simulate_portfolio(old, L, LevConfig(), rebalance=reb)["equity"]
    assert np.allclose(a, b, rtol=1e-10)


def _simple(r, r_low, trend=1.0, vol=0.40):
    n = len(r)
    return {"r": np.asarray(r, float), "r_low": np.minimum(np.asarray(r_low, float), r), "f": np.zeros(n),
            "trend": np.full(n, trend), "vol_slow": np.full(n, vol), "vol_fast": np.full(n, vol)}


def test_stop_limits_crash_day_loss():
    a = _simple([0, 0.0, -0.18, 0.0], [0, -0.01, -0.20, 0.0])
    free = LevConfig(spot_cost=0, perp_cost=0, maintenance=0.005, band=0.0)
    no_stop = simulate_protected([a], 2.0, Controls(), free)
    with_stop = simulate_protected([a], 2.0, Controls(stop_k=3.0), free)
    assert with_stop["stops"] == 1
    # Sin stop pierde 2 × 18 %; con stop (3 × 40 %/√365 ≈ 6,3 %) mucho menos.
    assert no_stop["equity"][2] == pytest.approx(1 - 2 * 0.18, rel=1e-6)
    assert with_stop["equity"][2] > 0.80


def test_stop_prevents_liquidation_at_high_leverage():
    a = _simple([0, 0.0, -0.05], [0, 0.0, -0.12])
    free = LevConfig(spot_cost=0, perp_cost=0, maintenance=0.005, band=0.0)
    assert simulate_protected([a], 10.0, Controls(), free)["liquidaciones"] == 1
    res = simulate_protected([a], 10.0, Controls(stop_k=3.0), free)
    assert res["liquidaciones"] == 0 and res["equity"][-1] > 0.4


def test_drawdown_floor_cuts_exposure():
    r = [0] + [-0.05] * 30
    a = _simple(r, r)
    free = LevConfig(spot_cost=0, perp_cost=0, maintenance=0.005, band=0.0)
    res = simulate_protected([a], 3.0, Controls(dd_floor=0.40), free)
    eq = res["equity"]
    assert (eq / np.maximum.accumulate(eq) - 1).min() > -0.40
    assert res["dias_en_suelo"] == 0 or eq[-1] == pytest.approx(eq[-2])


def test_strong_only_caps_leverage_when_trend_is_partial():
    a = _simple([0, 0.10], [0, 0.10], trend=2 / 3)
    free = LevConfig(spot_cost=0, perp_cost=0, maintenance=0.005, band=0.0)
    lev = simulate_protected([a], 3.0, Controls(), free)["equity"][-1]
    capped = simulate_protected([a], 3.0, Controls(strong_only=True), free)["equity"][-1]
    assert lev == pytest.approx(1 + 3 * 2 / 3 * 0.10)
    assert capped == pytest.approx(1 + 1 * 2 / 3 * 0.10)


def test_no_lookahead_future_change_does_not_alter_past():
    new, _, idx = _assets(seeds=(3,))
    ctl = Controls(fast_vol=True, stop_k=3.0, dd_floor=0.4, strong_only=True)
    base = simulate_protected(new, 3.0, ctl)["equity"]
    shocked = [{k: v.copy() for k, v in new[0].items()}]
    shocked[0]["r"][500] = -0.3
    shocked[0]["r_low"][500] = -0.35
    alt = simulate_protected(shocked, 3.0, ctl)["equity"]
    assert np.array_equal(base[:500], alt[:500])
