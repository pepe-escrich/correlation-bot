# Ampliación: la estrategia intradía con velas de 1 minuto

*Estado: **pre-registrado** el 22 de octubre de 2026, antes de simular ninguna operación con velas de 1 minuto. Los resultados se añadirán debajo sin modificar esta sección.*

Continúa [`intradia_10x.md`](intradia_10x.md): misma estrategia (stop según volatilidad → breakeven → objetivo o stop que persigue), mismos costes y mismos criterios.

## Pregunta

¿Cambia la conclusión al usar velas de 1 minuto? Hay dos lecturas posibles y se prueban las dos:

- **A) Precisión.** Se repiten las 96 configuraciones ya probadas (señales en velas de 15 minutos y de 1 hora), pero siguiendo cada operación minuto a minuto en lugar de cada 5 minutos.
- **B) Operar en 1 minuto.** Se generan señales en velas de 1 y de 5 minutos y cada operación se sigue minuto a minuto.

## Dato previo (descriptivo, sin simular operaciones)

Distancia mediana del stop en desarrollo (BTC y ETH, junio 2018 – diciembre 2023), frente a unos costes de ida y vuelta del 0,14 %:

| Velas | Stop a 1 ATR | Stop a 3 ATR | Costes en % del riesgo (1 ATR) | Costes en % del riesgo (3 ATR) |
|---|---|---|---|---|
| 1 min | 0,10 % | 0,29 % | 147 % | 49 % |
| 5 min | 0,24 % | 0,72 % | 60 % | 20 % |
| 15 min | 0,44 % | 1,32 % | 32 % | 11 % |
| 1 hora | 0,93 % | 2,80 % | 15 % | 5 % |

**El breakeven "entrada + costes" a menudo no se puede colocar.** Si el precio de activación (0,5R, 1R o 2R) está más cerca de la entrada que los costes (0,14 %), un stop en "entrada + costes" quedaría por encima del precio. Pasa en estos casos (% de las velas):

| Velas | 1 ATR · 0,5R | 1 ATR · 1R | 1 ATR · 2R | 3 ATR · 0,5R |
|---|---|---|---|---|
| 1 min | 94 % | 71 % | 32 % | 48 % |
| 5 min | 61 % | 21 % | 4 % | 9 % |
| 15 min | 24 % | 4 % | 0,6 % | 1 % |
| 1 hora | 3 % | 0,3 % | 0 % | 0 % |

Con la regla tal como está escrita en el protocolo original, en esos casos la operación se cierra en la apertura de la vela siguiente: el stop ya está "pasado". Se mantiene la regla sin cambios y se informará de cuántas operaciones terminan así.

## Diseño (congelado)

Todo igual que en el protocolo original, salvo lo que se indica:

- **Velas de gestión:** 1 minuto, spot de Binance (BTCUSDT y ETHUSDT), del 1 de marzo de 2018 al 21 de octubre de 2026.
- **Parte A:** las mismas 96 configuraciones (señales en 15 minutos y 1 hora) y las mismas reglas de selección y criterios. No se repiten las entradas al azar, porque el objetivo es comparar con la simulación cada 5 minutos; el criterio 2 queda sin evaluar.
  - **Lectura:** si con velas de 1 minuto ninguna configuración pasa a cumplir los criterios 1, 3 y 4, la conclusión original no depende de la resolución de la simulación.
- **Parte B:** señales en velas de **1 y 5 minutos**, con todo lo demás como en el protocolo original:
  - mismas entradas (ruptura de 20 velas y retroceso a la media de 20 ± 1 ATR de 14 velas);
  - mismo filtro de tendencia diario;
  - misma gestión: stop a 1, 2 o 3 ATR; breakeven a 0,5R, 1R, 2R o sin breakeven; objetivo 3R o stop que persigue; cierre a las 24 horas;
  - mismos costes, las mismas entradas al azar como control (20 semillas, con la frecuencia de la ruptura), la misma regla de selección (≥ 150 operaciones) y los mismos 5 criterios.
- **Periodos:** desarrollo del 1-6-2018 al 31-12-2023 y examen del 1-1-2024 al 21-10-2026, que se ejecuta una sola vez.

**Lo que se espera (escrito antes de ejecutar).**
- **Parte A:** resultados prácticamente iguales a los de la simulación cada 5 minutos. Las velas ambiguas eran muy raras.
- **Parte B:** pérdidas mayores. En velas de 1 minuto los costes superan al riesgo de cada operación. Para salir positiva, una entrada necesitaría ganar antes de costes del orden del 0,15–0,3 % por operación, unas 10–20 veces más que la mejor configuración de 15 minutos y 1 hora.

**Transparencia.**
- El periodo de examen ya se usó en el análisis original (con 15 minutos y 1 hora); las señales de 1 y 5 minutos no se han simulado nunca.
- Un operador de 1 minuto podría entrar con órdenes límite para pagar menos comisión. Simularlo bien exige modelar qué órdenes se llenan y cuáles no, y no se hace aquí. Como referencia, se informará de la rentabilidad **antes de costes**: si no es claramente positiva, ninguna estructura de comisiones puede salvar la estrategia.

---

## Resultados

*(Pendiente: se añadirán tras ejecutar.)*
