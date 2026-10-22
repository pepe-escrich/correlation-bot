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
5. **Estrategia intradía a 10x con stop escalonado (stop según volatilidad → breakeven → objetivo): descartada.** Informe: [`docs/intradia_10x.md`](docs/intradia_10x.md).
   - Protocolo pre-registrado con 96 configuraciones (15 min y 1 h) y entradas al azar como control: suspende los 5 criterios.
   - Sin ventaja antes de costes; los costes se comen hasta el 39 % del riesgo de cada operación en velas de 15 min. El breakeven no mejora la rentabilidad.
   - A 10x la cuenta pierde el 90 % en 11 meses; en el examen 2024–2026 pierden las 96 configuraciones.
6. **Ampliación con velas de 1 minuto: confirma el descarte.** Informe: [`docs/intradia_1min.md`](docs/intradia_1min.md).
   - Seguir cada operación minuto a minuto en lugar de cada 5 minutos no cambia el resultado (diferencia mediana del 0,01 % por operación).
   - Con señales de 1 y 5 minutos pierden las 96 configuraciones: los costes llegan a ser 2,5 veces lo que arriesga el stop y el breakeven ni siquiera se puede colocar en la mayoría de operaciones.
7. **¿Revisar la estrategia A cada hora o cada minuto?** No: empeora. Una vez al día da 32 % al año; cada hora, 29 %; cada minuto, −15 % (2.670 órdenes al año). Informe: [`docs/frecuencia_chequeo.md`](docs/frecuencia_chequeo.md).
8. **Estrategia A con HYPE en 2026 (ilustración):** 1.000 $ → 1.424 $ (+42 %, caída −13 %) frente a 3.166 $ manteniendo (+217 %, caída −30 %). Por su volatilidad, la regla invierte como mucho la mitad. Antes, del máximo de septiembre de 2025 a enero de 2026, HYPE cayó un 64 %. Informe: [`docs/hype_2026.md`](docs/hype_2026.md).
9. **Siguiente fase propuesta:** motor del bot (estrategia A, solo BTC y ETH, 1x) y paper trading en OKX Europa, con la candidata a 2x en paralelo solo en demo.

## Estructura

```
corrbot/            librería
  data.py           descarga y caché de velas de Binance (data.binance.vision) y de Hyperliquid, sin API key
  stats.py          beta, beta asimétrica, ratio de varianzas, zigzag (tramos), cointegración
  backtest.py       backtester de rotación 0/1 y de rebalanceo, métricas, test de azar, walk-forward
  trend.py          estrategia A: tendencia con tamaño por volatilidad, backtest, test de azar, simulación de caídas
  dips.py           estrategia B: compras tras caídas extremas (órdenes límite, funding)
  leverage.py       simulador con apalancamiento: funding, liquidación y rebalanceo
  protect.py        controles de protección: volatilidad rápida, stop intradía, freno por caída, tendencia fuerte
  intraday.py       operaciones intradía con stop escalonado sobre velas de 5 min, cuenta apalancada
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
  intraday_analysis.py      estrategia intradía 10x con stop escalonado (protocolo pre-registrado) → results/intradia/
                            con --velas 1m y --temporalidades, la ampliación a 1 minuto → results/intradia_1min/
  breakeven_check.py        cuántas operaciones tienen un breakeven que no se puede colocar
  check_frequency.py        estrategia A revisada cada día, hora o minuto → results/frecuencia/
  hype_2026.py              estrategia A con HYPE en 2026 (datos de Hyperliquid) → results/hype_2026/, gráfico 21
  charts_intraday.py        gráficos 14-17
  charts_intraday_1min.py   gráficos 18-20
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
