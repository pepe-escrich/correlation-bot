"""Descarga y caché de velas (klines) históricas de Binance spot.

Fuente: https://data.binance.vision (ficheros públicos oficiales, sin API key).

- Meses completos: ficheros mensuales. Mes en curso: ficheros diarios.
- Desde 2025-01-01 los timestamps vienen en microsegundos (antes en milisegundos).
- Caché local en data/klines/<intervalo>/<SIMBOLO>.parquet (no se sube a git).
"""
from __future__ import annotations

import io
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://data.binance.vision/data/spot"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "klines"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]
FLOAT_COLUMNS = ["open", "high", "low", "close", "volume", "quote_volume"]

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def _fetch_zip_csv(url: str, retries: int = 5) -> pd.DataFrame | None:
    """Descarga un zip de Binance y devuelve el CSV como DataFrame (None si no existe)."""
    for attempt in range(retries):
        try:
            resp = _session().get(url, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                with zf.open(zf.namelist()[0]) as fh:
                    return pd.read_csv(fh, header=None, names=KLINE_COLUMNS, dtype=str)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"No se pudo descargar {url}")


def _to_utc(ts: pd.Series) -> pd.DatetimeIndex:
    """Convierte timestamps de Binance (ms antes de 2025, µs después) a UTC."""
    values = ts.astype("int64").to_numpy()
    values = np.where(values > 10**14, values // 1000, values)
    return pd.to_datetime(values, unit="ms", utc=True)


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    # Algunos ficheros traen fila de cabecera: se descartan filas no numéricas.
    raw = raw[pd.to_numeric(raw["open_time"], errors="coerce").notna()]
    df = pd.DataFrame(index=_to_utc(raw["open_time"]))
    df.index.name = "open_time"
    for col in FLOAT_COLUMNS:
        df[col] = raw[col].astype(float).to_numpy()
    df["trades"] = raw["trades"].astype("int64").to_numpy()
    return df


def _month_starts(start: date, end: date) -> list[date]:
    months, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        months.append(cur)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def _urls(symbol: str, interval: str, start: date, today: date) -> list[str]:
    first_of_month = date(today.year, today.month, 1)
    urls = []
    for m in _month_starts(start, first_of_month - timedelta(days=1)):
        name = f"{symbol}-{interval}-{m:%Y-%m}"
        urls.append(f"{BASE_URL}/monthly/klines/{symbol}/{interval}/{name}.zip")
    day = max(first_of_month, start)
    while day < today:
        name = f"{symbol}-{interval}-{day:%Y-%m-%d}"
        urls.append(f"{BASE_URL}/daily/klines/{symbol}/{interval}/{name}.zip")
        day += timedelta(days=1)
    return urls


def cache_path(symbol: str, interval: str) -> Path:
    return DATA_DIR / interval / f"{symbol}.parquet"


def download_klines(symbol: str, interval: str = "1h", start: str = "2017-08-01",
                    workers: int = 16, refresh: bool = False) -> pd.DataFrame:
    """Descarga (o actualiza de forma incremental) las velas de un símbolo y las cachea."""
    path = cache_path(symbol, interval)
    today = datetime.now(timezone.utc).date()
    cached = None
    start_date = date.fromisoformat(start)
    if path.exists() and not refresh:
        cached = pd.read_parquet(path)
        if len(cached):
            last = cached.index[-1].date()
            start_date = date(last.year, last.month, 1)  # se vuelve a bajar el último mes
    urls = _urls(symbol, interval, start_date, today)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [f for f in pool.map(_fetch_zip_csv, urls) if f is not None and len(f)]
    parts = [_clean(f) for f in frames]
    if cached is not None:
        parts.insert(0, cached)
    if not parts:
        raise ValueError(f"Sin datos para {symbol} {interval}")
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def load_klines(symbol: str, interval: str = "1h") -> pd.DataFrame:
    path = cache_path(symbol, interval)
    if not path.exists():
        raise FileNotFoundError(f"{path} no existe: ejecuta scripts/download_data.py")
    return pd.read_parquet(path)


def load_closes(symbols: list[str], interval: str = "1h", start: str | None = None,
                end: str | None = None) -> pd.DataFrame:
    """Precios de cierre alineados en una rejilla regular (huecos cortos rellenados)."""
    closes = pd.concat({s: load_klines(s, interval)["close"] for s in symbols}, axis=1)
    if start:
        closes = closes[closes.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        closes = closes[closes.index < pd.Timestamp(end, tz="UTC")]
    freq = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}[interval]
    grid = pd.date_range(closes.index[0], closes.index[-1], freq=freq)
    # El índice es la hora de APERTURA de cada vela (el cierre llega un intervalo después).
    # Se rellenan huecos cortos (paradas de mantenimiento del exchange).
    return closes.reindex(grid).ffill(limit=12)


# ------------------------------------------------------------------ funding rates
FUNDING_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


def _fetch_funding(url: str) -> pd.Series | None:
    raw = _fetch_raw_csv(url)
    if raw is None:
        return None
    raw = raw[pd.to_numeric(raw[0], errors="coerce").notna()]
    ts = raw[0].astype("int64").to_numpy()
    ts = np.where(ts > 10**14, ts // 1000, ts)
    return pd.Series(raw[raw.columns[-1]].astype(float).to_numpy(), index=pd.to_datetime(ts, unit="ms", utc=True))


def _fetch_raw_csv(url: str, retries: int = 5) -> pd.DataFrame | None:
    for attempt in range(retries):
        try:
            resp = _session().get(url, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                with zf.open(zf.namelist()[0]) as fh:
                    return pd.read_csv(fh, header=None, dtype=str)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"No se pudo descargar {url}")


def download_funding(symbol: str, start: str = "2019-09-01", workers: int = 16) -> pd.Series:
    """Funding rates de los perpetuos USDT-M de Binance (cada 8 h) → data/funding/<SIMBOLO>.parquet."""
    today = datetime.now(timezone.utc).date()
    months = _month_starts(date.fromisoformat(start), date(today.year, today.month, 1) - timedelta(days=1))
    urls = [f"{FUNDING_URL}/{symbol}/{symbol}-fundingRate-{m:%Y-%m}.zip" for m in months]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = [p for p in pool.map(_fetch_funding, urls) if p is not None]
    series = pd.concat(parts).sort_index()
    series = series[~series.index.duplicated()]
    path = DATA_DIR.parent / "funding" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_frame("rate").to_parquet(path)
    return series
