# correlation-bot

Investigación y desarrollo de un bot de trading que rota el capital entre dos criptomonedas correlacionadas (p. ej. BTC ↔ ETH) para aprovechar sus diferencias de movimiento.

## Estado

1. **Idea original (rotación BTC↔ETH): descartada.** No tiene ventaja estadística y pierde frente a mantener BTC en 34 de las 35 variantes probadas. Informe: [`docs/analisis_inicial.md`](docs/analisis_inicial.md).
2. **Nueva base A + B: validación completa hecha** con protocolo pre-registrado. Informe: [`docs/validacion_A_B.md`](docs/validacion_A_B.md).
   - **A (seguir la tendencia en BTC/ETH con salida a USDT):** aprueba 5 de 6 criterios, incluido el examen final 2025–2026 (+25,5 % frente a −18 % de mantener; caída máxima −21 % frente a −60 %). Suspende la generalización del Sharpe a altcoins.
   - **B (comprar caídas bruscas):** descartada.
3. **Ampliación al top 10 y apalancamiento 0x–10x:** informe [`docs/top10_apalancamiento.md`](docs/top10_apalancamiento.md).
   - Sin el sesgo de elegir los ganadores de hoy, añadir altcoins a BTC y ETH empeora el resultado (×4,6 frente a ×14,7 en 2019–2026).
   - Con el límite de caída del 50 %, el apalancamiento máximo razonable es 1x (1,5x ya lo roza); a 10x todo se liquida.
4. **Controles de protección para apalancar más (BTC y ETH):** informe [`docs/proteccion_apalancamiento.md`](docs/proteccion_apalancamiento.md).
   - Stop intradía, volatilidad rápida y freno por caída reducen caídas pero no permiten ganar más apalancando; 1x sigue siendo lo mejor entre lo fijado de antemano.
   - Única candidata: "tendencia fuerte + freno con reinicio anual" a 2x (40 % anual frente a 34 %, caída similar), elegida a posteriori y justo en el límite de riesgo.
5. **Siguiente fase propuesta:** motor del bot (estrategia A, solo BTC y ETH, 1x) y paper trading en OKX Europa, con la candidata a 2x en paralelo solo en demo.

## Estructura

```
corrbot/            librería
  data.py           descarga y caché de velas de Binance (data.binance.vision, sin API key)
  stats.py          beta, beta asimétrica, ratio de varianzas, zigzag (tramos), cointegración
  backtest.py       backtester de rotación 0/1 y de rebalanceo, métricas, test de azar, walk-forward
  trend.py          estrategia A: tendencia con tamaño por volatilidad, backtest, test de azar, simulación de caídas
  dips.py           estrategia B: compras tras caídas extremas (órdenes límite, funding)
  leverage.py       simulador con apalancamiento: funding, liquidación y rebalanceo
  protect.py        controles de protección: volatilidad rápida, stop intradía, freno por caída, tendencia fuerte
  plots.py          estilo de gráficos
scripts/
  download_data.py  descarga el dataset (~200 MB en data/, ignorado por git)
  explore.py        fase 1: ¿se cumplen las premisas? → results/*.csv, docs/img/01-04
  backtest_rotation.py  backtests con costes → results/bt_*.csv, docs/img/05-06
  validate_a.py     validación de A (tendencia) en desarrollo → results/validacion/A_*.csv
  validate_b.py     validación de B (caídas) en desarrollo → results/validacion/B_*.csv
  final_exam.py     examen final 2025-2026 → results/validacion/examen_*.csv, docs/img/07-08
  download_universe.py  velas diarias de todos los pares USDT de Binance (incluidos deslistados)
  leverage_analysis.py  apalancamiento 0x-10x en BTC/ETH, rotación y B → results/apalancamiento/
  top10_analysis.py     top 10 de hoy y de cada momento, con apalancamiento → results/top10/
  charts_top10_leverage.py  gráficos 09-11
  protection_analysis.py    controles de protección y apalancamiento máximo aceptable → results/proteccion/
  charts_protection.py      gráficos 12-13
tests/              tests del backtester (incluye comprobación de "no mirar al futuro")
results/            resultados en CSV (los números del informe)
docs/               informe y gráficos
```

## Uso

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_data.py
python scripts/explore.py
python scripts/backtest_rotation.py
python -m pytest -q
```
