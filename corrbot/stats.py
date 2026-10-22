"""Estadísticos para evaluar pares de tokens.

Lo que importa para la estrategia de rotación NO es solo la correlación, sino si el
ratio entre los dos tokens (p. ej. ETH/BTC) es predecible: si tiende a volver a la
media (reversión) o a seguir en la misma dirección (tendencia/momentum).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def log_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return np.log(prices).diff()


# --------------------------------------------------------------------------- beta
def ols_beta(y: np.ndarray, x: np.ndarray) -> dict:
    """Regresión y = alpha + beta·x (por MCO)."""
    mask = np.isfinite(y) & np.isfinite(x)
    y, x = y[mask], x[mask]
    beta = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
    alpha = y.mean() - beta * x.mean()
    resid = y - alpha - beta * x
    r2 = 1 - resid.var() / y.var()
    return {"alpha": alpha, "beta": beta, "r2": r2, "corr": np.corrcoef(x, y)[0, 1], "n": len(y)}


def dual_beta(y: np.ndarray, x: np.ndarray) -> dict:
    """Beta separada para subidas y bajadas del activo de referencia.

    y = a + b_up·x·1[x>0] + b_down·x·1[x<=0] + e, con errores estándar robustos (HC1).
    """
    mask = np.isfinite(y) & np.isfinite(x)
    y, x = y[mask], x[mask]
    X = np.column_stack([np.ones_like(x), x * (x > 0), x * (x <= 0)])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    meat = X.T @ (X * resid[:, None] ** 2)
    cov = xtx_inv @ meat @ xtx_inv * n / (n - k)
    se = np.sqrt(np.diag(cov))
    diff_se = np.sqrt(cov[1, 1] + cov[2, 2] - 2 * cov[1, 2])
    return {
        "beta_up": coef[1], "beta_down": coef[2],
        "se_up": se[1], "se_down": se[2],
        "t_diff": (coef[1] - coef[2]) / diff_se, "n": n,
    }


# ------------------------------------------------------------ variance ratio test
def _lagged_products(x: np.ndarray, maxlag: int) -> np.ndarray:
    """s[j] = sum_t x[t]·x[t+j] para j = 0..maxlag (vía FFT)."""
    n = len(x)
    nfft = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(x, nfft)
    return np.fft.irfft(f * np.conj(f), nfft)[: maxlag + 1]


def variance_ratio(log_prices: np.ndarray, q: int) -> tuple[float, float]:
    """Test de ratio de varianzas de Lo-MacKinlay (1988), robusto a heterocedasticidad.

    VR(q) = Var(retorno a q periodos) / (q · Var(retorno a 1 periodo)).
      VR < 1 -> reversión a la media a ese horizonte (lo que necesita la idea).
      VR > 1 -> tendencia/momentum.
      VR = 1 -> paseo aleatorio (no predecible).
    Devuelve (VR, z*); |z*| > 1.96 es significativo al 5 %.
    """
    lp = np.asarray(log_prices, dtype=float)
    lp = lp[np.isfinite(lp)]
    r = np.diff(lp)
    T = len(r)
    mu = r.mean()
    e = r - mu
    var1 = (e @ e) / (T - 1)
    rq = lp[q:] - lp[:-q]
    m = q * (T - q + 1) * (1 - q / T)
    varq = ((rq - q * mu) ** 2).sum() / m
    vr = varq / var1
    e2 = e ** 2
    s = _lagged_products(e2, q - 1)
    j = np.arange(1, q)
    delta = T * s[1:q] / (e2.sum() ** 2)
    theta = np.sum((2 * (q - j) / q) ** 2 * delta)
    z = np.sqrt(T) * (vr - 1) / np.sqrt(theta) if q > 1 else 0.0
    return float(vr), float(z)


def lag1_autocorr(returns: pd.Series) -> tuple[float, float]:
    """Autocorrelación de orden 1 y su estadístico t aproximado (sqrt(n)·rho)."""
    r = returns.dropna().to_numpy()
    rho = np.corrcoef(r[:-1], r[1:])[0, 1]
    return float(rho), float(rho * np.sqrt(len(r) - 1))


# ------------------------------------------------------------------------ zigzag
def zigzag(prices: np.ndarray, threshold: float) -> pd.DataFrame:
    """Detecta tramos alcistas/bajistas: un giro se confirma cuando el precio se aleja
    `threshold` (p. ej. 0.03 = 3 %) del último extremo.

    Devuelve una fila por pivote con:
      idx      -> barra donde estuvo el extremo (solo se sabe a posteriori)
      kind     -> +1 máximo, -1 mínimo
      confirm  -> barra en la que el giro queda confirmado (lo que un bot vería en vivo)
    """
    p = np.asarray(prices, dtype=float)
    idx, kind, confirm = [], [], []
    trend, hi, lo = 0, 0, 0
    for i in range(1, len(p)):
        x = p[i]
        if trend == 0:
            if x > p[hi]:
                hi = i
            if x < p[lo]:
                lo = i
            if x >= p[lo] * (1 + threshold):
                idx.append(lo), kind.append(-1), confirm.append(i)
                trend, hi = 1, i
            elif x <= p[hi] * (1 - threshold):
                idx.append(hi), kind.append(1), confirm.append(i)
                trend, lo = -1, i
        elif trend == 1:
            if x > p[hi]:
                hi = i
            elif x <= p[hi] * (1 - threshold):
                idx.append(hi), kind.append(1), confirm.append(i)
                trend, lo = -1, i
        else:
            if x < p[lo]:
                lo = i
            elif x >= p[lo] * (1 + threshold):
                idx.append(lo), kind.append(-1), confirm.append(i)
                trend, hi = 1, i
    return pd.DataFrame({"idx": idx, "kind": kind, "confirm": confirm})


def legs_table(pivots: pd.DataFrame, price_a: np.ndarray, price_b: np.ndarray,
               index: pd.DatetimeIndex) -> pd.DataFrame:
    """Para cada tramo entre pivotes (definidos sobre A): variación % de A y de B."""
    start = pivots["idx"].to_numpy()[:-1]
    end = pivots["idx"].to_numpy()[1:]
    direction = np.where(pivots["kind"].to_numpy()[:-1] == -1, "subida", "bajada")
    pct_a = price_a[end] / price_a[start] - 1
    pct_b = price_b[end] / price_b[start] - 1
    return pd.DataFrame({
        "start": index[start], "end": index[end], "direction": direction,
        "bars": end - start, "pct_a": pct_a, "pct_b": pct_b, "amplification": pct_b / pct_a,
    })


# ------------------------------------------------------------- cointegración/OU
def half_life(spread: pd.Series) -> float:
    """Vida media de reversión (en barras) de un proceso AR(1)/Ornstein-Uhlenbeck."""
    s = spread.dropna().to_numpy()
    ds, lag = np.diff(s), s[:-1]
    b = np.cov(lag, ds, ddof=1)[0, 1] / np.var(lag, ddof=1)
    return float(-np.log(2) / np.log(1 + b)) if -1 < b < 0 else float("inf")


def adf_pvalue(series: pd.Series) -> float:
    from statsmodels.tsa.stattools import adfuller

    return float(adfuller(series.dropna().to_numpy(), regression="c", autolag="AIC")[1])


def engle_granger_pvalue(y: pd.Series, x: pd.Series) -> float:
    from statsmodels.tsa.stattools import coint

    df = pd.concat([y, x], axis=1).dropna()
    return float(coint(df.iloc[:, 0], df.iloc[:, 1])[1])
