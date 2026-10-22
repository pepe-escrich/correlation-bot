import numpy as np
import pandas as pd
import pytest

from corrbot.backtest import (
    Costs, NO_COSTS, random_timing_null, run_rebalance, run_switch, target_anchored_grid,
    target_time_rule, target_zigzag,
)
from corrbot.stats import variance_ratio, zigzag


def _prices(n=2000, seed=1, beta=1.5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    ra = rng.normal(0, 0.01, n)
    rb = beta * ra + rng.normal(0, 0.005, n)
    pa = pd.Series(100 * np.exp(np.cumsum(ra)), index=idx)
    pb = pd.Series(10 * np.exp(np.cumsum(rb)), index=idx)
    return pa, pb


def test_identity_vs_hodl_a():
    """Frente a HODL A solo cuenta el ratio B/A mientras se está en B, menos costes."""
    pa, pb = _prices()
    tgt = target_time_rule(pa.pct_change().fillna(0).to_numpy(), contrarian=True)
    costs = Costs(fee=0.001, slippage=0.0002)
    res = run_switch(pa, pb, tgt, costs)
    dlr = np.diff(np.log((pb / pa).to_numpy()), prepend=np.log(pb.iloc[0] / pa.iloc[0]))
    expected = np.exp(np.sum(res["held"].to_numpy() * dlr)) * (1 - costs.per_switch) ** res["switch"].sum()
    assert res["equity_in_a"].iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_no_lookahead():
    """Una señal que "conoce" el retorno de la barra actual no debe poder aprovecharlo."""
    pa, pb = _prices(seed=3)
    dlr = np.log(pb / pa).diff().fillna(0).to_numpy()
    cheat = (dlr > 0).astype(float)  # B si el ratio sube EN la barra t (ya ocurrido)
    res = run_switch(pa, pb, cheat, NO_COSTS)
    # Como la posición se aplica en t+1 y el ratio es un paseo aleatorio, no hay ventaja:
    # el resultado queda dentro del ruido esperable (4 desviaciones típicas).
    sigma = dlr.std() * np.sqrt(res["held"].sum())
    assert abs(np.log(res["equity_in_a"].iloc[-1])) < 4 * sigma
    # Si se aplicase en la misma barra (trampa), la ganancia sería enorme:
    assert np.exp(np.sum(cheat * dlr)) > 100


def test_rebalance_without_trades_equals_buy_and_hold():
    pa, pb = _prices()
    res = run_rebalance(pa, pb, 0.5, NO_COSTS)
    bh = 0.5 * pa / pa.iloc[0] + 0.5 * pb / pb.iloc[0]
    assert np.allclose(res["equity"].to_numpy(), bh.to_numpy())


def test_always_b_equals_hodl_b_minus_nothing():
    pa, pb = _prices()
    res = run_switch(pa, pb, np.ones(len(pa)), Costs())
    assert res["equity"].iloc[-1] == pytest.approx(pb.iloc[-1] / pb.iloc[0])
    assert res["switch"].sum() == 0


def test_zigzag_confirmation():
    p = np.array([100, 103, 106, 104, 100, 99, 101, 104, 108, 104])
    piv = zigzag(p, 0.05)
    # Máximo en 106 (idx 2) confirmado al caer a 100 (idx 4); mínimo 99 (idx 5)
    # confirmado al llegar a 104 (idx 7).
    first_peak = piv[piv["kind"] == 1].iloc[0]
    assert (first_peak["idx"], first_peak["confirm"]) == (2, 4)
    trough = piv[piv["kind"] == -1].iloc[-1]
    assert (trough["idx"], trough["confirm"]) == (5, 7)
    tgt = target_zigzag(p, 0.05, contrarian=True)
    assert tgt[4] == 1.0 and tgt[6] == 1.0  # tras bajada confirmada -> B
    assert tgt[7] == 0.0                     # tras subida confirmada -> A


def test_anchored_grid():
    r = np.array([1.0, 0.97, 0.95, 0.96, 1.0, 1.05, 1.0])
    tgt = target_anchored_grid(r, 0.05, contrarian=True)
    # Compra B al caer un 5 % (0.95) y vuelve a A al subir un 5 % desde la compra (>= 0.9975).
    assert list(tgt) == [0, 0, 1, 1, 0, 0, 0]


def test_variance_ratio_random_walk_and_mean_reversion():
    rng = np.random.default_rng(7)
    rw = np.cumsum(rng.normal(0, 1, 50_000))
    vr, z = variance_ratio(rw, 10)
    assert abs(vr - 1) < 0.05 and abs(z) < 3
    # Retornos con autocorrelación negativa -> VR < 1
    e = rng.normal(0, 1, 50_000)
    r = e[1:] - 0.5 * e[:-1]
    vr_mr, z_mr = variance_ratio(np.cumsum(r), 10)
    assert vr_mr < 0.7 and z_mr < -10


def test_random_null_preserves_switch_count():
    pa, pb = _prices()
    tgt = target_time_rule(pa.pct_change().fillna(0).to_numpy(), contrarian=True, deadband=0.01)
    sims = random_timing_null(pa, pb, tgt, n_sims=50)
    assert sims.shape == (50,) and np.all(sims > 0)
