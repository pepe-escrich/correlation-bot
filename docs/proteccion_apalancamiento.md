# Controles de protección y apalancamiento (solo BTC y ETH)

*22 de octubre de 2026 · Estrategia A sobre BTC y ETH (50/50, reparto mensual) · Datos de Binance de marzo 2018 a octubre 2026.*

## Pregunta

¿Podemos añadir controles que protejan ante caídas y, gracias a ellos, usar más apalancamiento sin romper tu límite de −50 %?

<!-- RESUMEN -->

## Los controles probados

Todos se calculan con información hasta el cierre anterior, sin mirar al futuro. Los parámetros se han fijado por criterio y **no** optimizando sobre los datos.

| Control | Qué hace | Parámetro elegido | Por qué ese valor |
|---|---|---|---|
| **Volatilidad rápida** | Reduce la posición en cuanto el mercado se pone nervioso. Usa la mayor entre la volatilidad de 30 días y una rápida de ~10 días | media exponencial con vida media de 5 días | estándar en control de riesgo |
| **Stop intradía** | Si el precio cae más de 3 movimientos diarios normales desde el cierre anterior, cierra la posición. Vuelve a entrar al día siguiente si la señal sigue | 3 desviaciones típicas; nunca más lejos de la mitad de la distancia a la liquidación | 3σ solo salta en días anómalos; la mitad de la distancia evita liquidaciones |
| **Freno por caída** (CPPI/TIPP) | Cuanto más cae la cuenta desde su máximo, menos apalanca: todo el apalancamiento en máximos, cero al llegar al suelo | suelo a −40 % del máximo | 10 puntos de margen sobre tu −50 % para absorber huecos |
| **Freno con reinicio anual** | Igual, pero el máximo de referencia es el de los últimos 365 días. Tras tocar el suelo puede volver a operar | 365 días | evita quedarse en USDT para siempre |
| **Solo con tendencia fuerte** | Apalanca por encima de 1x solo si las tres medias (50, 100 y 200 días) están a favor | — | apalancar solo cuando la señal es más fiable |
| **Todo junto** | Los cuatro anteriores a la vez | — | — |

**Regla de aceptación (fijada antes de ver resultados).** Un apalancamiento es aceptable si cumple las tres condiciones:
1. La peor caída histórica (2018–2026) no supera el −50 %.
2. En la simulación de 3 años (400 escenarios), la probabilidad de caer más de un 50 % es ≤ 5 %.
3. La probabilidad de alguna liquidación es ≤ 1 %.

<!-- RESULTADOS -->

## Cómo se aplicarían en el bot

- **Stop:** como orden condicional en el propio exchange (OKX), no ejecutado por el bot. Así protege aunque el servidor del bot se caiga. En el backtest se asume un deslizamiento extra en días de desplome: como mínimo 0,5 %, más un 10 % de lo que el precio atraviese el stop.
- **Freno por caída:** se calcula una vez al día con el saldo total de la cuenta. Si se toca el suelo, el bot pasa todo a USDT y avisa.
- **Parada de emergencia manual:** independiente de todo lo anterior, siempre disponible.
