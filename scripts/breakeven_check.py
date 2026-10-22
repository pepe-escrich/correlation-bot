"""¿Cuántas operaciones tienen un breakeven que no se puede colocar? (docs/intradia_1min.md)

El breakeven pone el stop en "entrada + costes" (0,14 %). Si el precio de activación
(m × distancia del stop) está más cerca de la entrada que eso, el stop quedaría por encima del
precio y, con la regla escrita, la operación se cierra en la apertura de la vela siguiente.
Para cada configuración con breakeven, en desarrollo:
  - % de operaciones cuyo breakeven no se puede colocar,
  - % de operaciones que terminan cerradas por ese motivo.

Uso: python scripts/breakeven_check.py --velas 1m --temporalidades 1m,5m --salida results/intradia_1min
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import intraday_analysis as ia  # noqa: E402
from corrbot.intraday import Mgmt  # noqa: E402


def _task(cfg) -> dict:
    tf, kind, m = cfg
    tr = ia.pooled(ia.run(ia._DATA, tf, kind, m, ia.START, ia.EXAM))
    blocked = m.be * tr["distancia_stop"] < ia.COSTS.be_offset
    return {"config": ia.config_name(tf, kind, m), "temporalidad": tf, "entrada": ia.ENTRIES[kind], "k": m.k,
            "breakeven": ia.be_label(m.be), "salida": ia.EXITS[m.exit], "operaciones": len(tr),
            "% breakeven no colocable": float(blocked.mean()),
            "% cerradas por breakeven no colocable": float((blocked & (tr["motivo"] == "breakeven")).mean()),
            "% salidas en breakeven": float((tr["motivo"] == "breakeven").mean())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--velas", choices=["5m", "1m"], default="5m")
    ap.add_argument("--temporalidades", default="15m,1h")
    ap.add_argument("--salida", default="results/intradia")
    ap.add_argument("--procesos", type=int, default=4)
    args = ap.parse_args()
    ia.TFS = {tf: ia.RULES[tf] for tf in args.temporalidades.split(",")}
    ia.BAR_INTERVAL, ia.BAR = args.velas, pd.Timedelta(ia.RULES[args.velas])
    ia.PROCS = args.procesos
    ia._DATA = ia.prepare()
    cfgs = [(tf, kind, m) for tf, kind, m in ia.all_configs() if m.be is not None]
    out = pd.DataFrame(ia.pmap(_task, cfgs))
    path = ia.ROOT / args.salida / "breakeven_no_colocable.csv"
    out.to_csv(path, index=False)
    print(out.groupby(["temporalidad", "k", "breakeven"])[["% breakeven no colocable",
                                                           "% cerradas por breakeven no colocable"]].mean().round(3))
    print("guardado en", path.relative_to(ia.ROOT))


if __name__ == "__main__":
    main()
