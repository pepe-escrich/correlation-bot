# correlation-bot

Investigación y desarrollo de un bot de trading que rota el capital entre dos criptomonedas correlacionadas (p. ej. BTC ↔ ETH) para aprovechar sus diferencias de movimiento.

## Estado

**Fase 0 (validación inicial con datos): completada.** Informe completo: [`docs/analisis_inicial.md`](docs/analisis_inicial.md).

Conclusión resumida: la regla original ("tras una subida → BTC, tras una bajada → ETH") **no tiene ventaja estadística y pierde frente a mantener BTC** en 34 de las 35 variantes probadas (2018–2026, con comisiones). El informe explica por qué, qué variantes sí tienen recorrido y propone una hoja de ruta por fases.

## Estructura

```
corrbot/            librería
  data.py           descarga y caché de velas de Binance (data.binance.vision, sin API key)
  stats.py          beta, beta asimétrica, ratio de varianzas, zigzag (tramos), cointegración
  backtest.py       backtester de rotación 0/1 y de rebalanceo, métricas, test de azar, walk-forward
  plots.py          estilo de gráficos
scripts/
  download_data.py  descarga el dataset (~200 MB en data/, ignorado por git)
  explore.py        fase 1: ¿se cumplen las premisas? → results/*.csv, docs/img/01-04
  backtest_rotation.py  backtests con costes → results/bt_*.csv, docs/img/05-06
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
