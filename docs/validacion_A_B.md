# Validación de la estrategia A + B

*Estado: **protocolo pre-registrado** (escrito y subido al repositorio antes de ejecutar ningún test). Los resultados se añadirán debajo sin modificar esta sección.*

## Objetivo del usuario (restricciones)

- Ganar en **euros/dólares** (no en BTC).
- Capital inicial ~5.000 €; **caída máxima tolerable: 50 %**.
- Exchange: OKX Europa (regulado en España bajo MiCA). Datos de Binance como referencia.
- Se permiten futuros.

## Hipótesis

- **A (núcleo):** estar comprado en BTC/ETH solo cuando hay tendencia alcista, y en USDT cuando no, mejora la rentabilidad ajustada por riesgo y reduce las caídas frente a mantener (HODL).
- **B (satélite):** dentro de una tendencia alcista, comprar tras una caída brusca de pocas horas y vender poco después da beneficio neto, porque tras caídas extremas hay un pequeño rebote.

## Configuración a priori (congelada, sin optimizar)

**A — Seguimiento de tendencia**
- Activos: BTC y ETH, 50 % del capital del núcleo en cada uno, sin reequilibrar entre ellos.
- Señal diaria (cierre UTC): conjunto de tres medias simples de **50, 100 y 200 días**. Exposición de tendencia = número de medias por debajo del precio ÷ 3 (0, ⅓, ⅔ o 1). Usar varias medias en vez de "la mejor" es la práctica habitual para no sobreajustar.
- Tamaño por volatilidad: escala = mín(1; **40 %** ÷ volatilidad anualizada de los últimos 30 días). Exposición = tendencia × escala (entre 0 y 1, sin apalancamiento).
- Solo se opera si la exposición objetivo cambia **≥ 10 puntos** (evita micro-operaciones).
- Instrumento: **spot** (los largos en futuros pagan funding). Efectivo en USDT al 0 % (conservador).
- Costes: 0,10 % de comisión (taker spot de OKX) + 0,05 % de deslizamiento = **0,15 % por unidad operada**.

**B — Comprar caídas bruscas con tendencia alcista**
- Activos: BTC y ETH, velas de 5 minutos.
- Filtro: solo si la exposición de tendencia de A al cierre diario anterior es **≥ ⅔**.
- Disparador: rentabilidad de las últimas **4 h** inferior a **−3 desviaciones típicas** (estimadas con los 30 días anteriores, sin mirar al futuro).
- Entrada al cierre de la vela del disparador; **salida a las 4 h**. Una operación abierta por activo como máximo.
- Instrumento: futuros perpetuos 1x. Costes: 0,02 % de entrada (orden límite) + 0,05 % de salida (a mercado) + 0,02 % de deslizamiento, más el **funding real** de las horas mantenidas.

## Periodos

- **Desarrollo:** desde que hay 200 días de historia (marzo de 2018) hasta el 31-12-2024.
- **Examen final:** 01-01-2025 a 21-10-2026. Se ejecuta **una sola vez**, al final, con todo congelado.
- **Transparencia:** la criba rápida previa ya miró 2018–2026 completo en BTC y ETH, así que el examen final no es 100 % virgen. Para compensarlo: (1) la configuración de A no se optimiza; (2) se prueba en **18 tokens que no se han mirado**; (3) B se valida también en otros 6 tokens.

## Criterios de aprobado (fijados antes de ver resultados)

Métricas en dólares con rentabilidades diarias: Sharpe anualizado (√365, tipo libre de riesgo 0), caída máxima y rentabilidad anual compuesta. Referencia: **HODL 50/50 BTC/ETH** (y HODL de cada activo).

**A aprueba si cumple todo:**
1. **Desarrollo:** en BTC, en ETH y en la cartera 50/50, Sharpe mayor que HODL y caída máxima ≤ 50 %.
2. **Robustez de parámetros:** en la rejilla (una sola media de 20 a 200 días × objetivo de volatilidad 30/40/60 %/sin), al menos el **70 %** de las combinaciones supera el Sharpe de HODL en desarrollo, en cada activo.
3. **Azar:** el *timing* de la tendencia supera al 95 % de las simulaciones con los mismos periodos dentro/fuera en orden aleatorio (BTC y ETH, desarrollo).
4. **Otros tokens:** con la misma configuración, mejora el Sharpe de HODL en **≥ ⅔** de los 18 tokens y reduce la caída máxima en **≥ 80 %**.
5. **Estrés:** con costes ×2 **y** un día de retraso en la ejecución, sigue cumpliendo el criterio 1 en la cartera 50/50.
6. **Examen final (cartera 50/50):** caída máxima ≤ 50 % y ≤ la de HODL; Sharpe ≥ el de HODL − 0,3 (margen por lo corto del periodo).

**B aprueba si cumple todo:**
1. **Desarrollo (BTC+ETH):** rentabilidad neta media por operación > 0 con t ≥ 2.
2. **Walk-forward 2020–2024** (parámetros elegidos cada año con los 2 anteriores): resultado neto positivo.
3. **El filtro de tendencia ayuda:** la rentabilidad neta por operación con filtro es mayor que sin filtro.
4. **Otros tokens:** neto positivo en al menos 4 de 6 (SOL, BNB, XRP, DOGE, ADA, LINK).
5. **Examen final:** neto positivo en 2025–2026.

**Decisión:** si A aprueba, se pasa a construir el bot (motor realista + paper trading en OKX). B solo se incluye si aprueba. Si no, el bot será solo A.

**Informativo (no decide):** walk-forward eligiendo la mejor media cada año; probabilidad de una caída > 50 % en 3 años por simulación (*bootstrap* por bloques); cartera combinada A+B.

---

## Resultados

*(Pendiente: se añadirán tras ejecutar los tests.)*
