"""Descarga velas diarias de TODOS los pares contra USDT que han existido en Binance spot
(incluidos los deslistados) para construir un top 10 "en su momento", sin sesgo de
supervivencia.

Uso: python scripts/download_universe.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrbot.data import cache_path, download_klines_listed, list_s3  # noqa: E402


def main() -> None:
    folders = list_s3("data/spot/monthly/klines/", folders=True)
    symbols = sorted({f.rstrip("/").split("/")[-1] for f in folders if f.rstrip("/").endswith("USDT")})
    todo = [s for s in symbols if not cache_path(s, "1d").exists()]
    print(f"{len(symbols)} pares USDT; faltan {len(todo)}", flush=True)

    def job(sym: str) -> str:
        try:
            df = download_klines_listed(sym, "1d", workers=4)
            return f"{sym}: {0 if df is None else len(df)} velas"
        except Exception as exc:  # noqa: BLE001 - se informa y se sigue
            return f"{sym}: ERROR {exc}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, msg in enumerate(pool.map(job, todo), 1):
            if i % 50 == 0 or "ERROR" in msg:
                print(f"[{i}/{len(todo)}] {msg}", flush=True)
    print("FIN", flush=True)


if __name__ == "__main__":
    main()
