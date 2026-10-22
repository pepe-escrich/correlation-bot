"""Descarga el dataset de investigación desde data.binance.vision.

Uso:
    python scripts/download_data.py            # todo (diario, 1h y 5m)
    python scripts/download_data.py --only 1d  # solo un intervalo
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot.data import download_klines  # noqa: E402

# Tokens líquidos con historia larga en Binance (par USDT activo).
UNIVERSE = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "LINK", "AVAX",
    "DOT", "LTC", "BCH", "XLM", "ATOM", "ETC", "NEAR", "UNI", "FIL", "AAVE",
]
# Pares cruzados directos (un solo trade por cambio de posición).
CROSS_PAIRS = ["ETHBTC", "SOLBTC", "BNBBTC", "LTCBTC", "LINKBTC", "SOLETH", "BNBETH", "LINKETH"]

JOBS = {
    "1d": [f"{t}USDT" for t in UNIVERSE] + CROSS_PAIRS,
    "1h": [f"{t}USDT" for t in UNIVERSE] + CROSS_PAIRS,
    "5m": ["BTCUSDT", "ETHUSDT", "ETHBTC"],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=sorted(JOBS), help="descargar solo este intervalo")
    parser.add_argument("--start", default="2017-08-01")
    args = parser.parse_args()
    for interval, symbols in JOBS.items():
        if args.only and interval != args.only:
            continue
        for symbol in symbols:
            t0 = time.time()
            df = download_klines(symbol, interval, start=args.start)
            print(f"{interval:>3} {symbol:<9} {len(df):>8} velas  "
                  f"{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}  ({time.time() - t0:.1f}s)",
                  flush=True)


if __name__ == "__main__":
    main()
