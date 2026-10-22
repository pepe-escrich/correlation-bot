# Estrategia intradía con apalancamiento 10x y stop-loss escalonado

*Estado: **protocolo pre-registrado** (escrito y subido al repositorio antes de ejecutar ningún test de esta estrategia). Los resultados se añadirán debajo sin modificar esta sección.*

## Idea a evaluar (propuesta del usuario)

Operar BTC y ETH en temporalidades pequeñas con apalancamiento 10x, con una protección en varios pasos:
1. Stop-loss inicial a una distancia calculada con estadísticas del mercado.
2. Cuando la operación gana un cierto porcentaje, mover el stop a *breakeven* (precio de entrada), de forma que ya no pueda perder.
3. Dejar correr la ganancia hasta un objetivo o con un stop que la persiga.

**Aviso de partida.** Un esquema de stops y objetivos no crea ventaja por sí solo: si el precio se moviera al azar, cualquier combinación tendría valor esperado cero antes de costes. La ventaja tiene que venir de **cuándo se entra**, y la gestión sirve para aprovecharla mejor. Por eso se prueban entradas reales y entradas aleatorias con la misma gestión.

## Diseño (congelado)

**Activos y datos:** BTC y ETH. Velas de 5 minutos de Binance (spot, como aproximación al precio de los perpetuos) y funding real de los perpetuos de Binance.

**Filtro de tendencia diaria** (el de la estrategia A, conocido el cierre del día anterior). Solo largos si al menos 2 de las 3 medias de 50, 100 y 200 días están por debajo del precio. Solo cortos si ninguna lo está. En otro caso no se opera.

**Entradas** (señal al cierre de una vela de 15 minutos o de 1 hora; ejecución en la siguiente vela de 5 minutos):
- **Ruptura:**
  - Largo: el cierre supera el máximo de las 20 velas anteriores.
  - Corto: el cierre baja del mínimo de las 20 velas anteriores.
- **Retroceso:**
  - Largo: el cierre queda por debajo de la media exponencial de 20 velas menos 1 ATR (rango medio de 14 velas).
  - Corto: el cierre queda por encima de esa media más 1 ATR.
- **Aleatoria (control):** mismo filtro de tendencia. En cada vela se entra con la misma probabilidad media que la ruptura (20 semillas distintas).
- Una sola operación abierta por activo; las señales que llegan con una operación abierta se ignoran.

**Gestión en pasos:**
1. **Stop inicial** a k × ATR de la temporalidad de la señal, con k ∈ {1, 2, 3}.
2. **Breakeven:** cuando el precio avanza m × la distancia del stop, el stop pasa al precio de entrada más los costes, de modo que salir ahí deja ~0. m ∈ {0,5; 1; 2}, más una versión **sin breakeven** como control.
3. **Salida final**, dos variantes:
   - **(a) Objetivo** a 3 × la distancia del stop.
   - **(b) Stop que persigue:** una vez activado el breakeven (o a +1 distancia en la versión sin breakeven), sigue al mejor cierre a 1 × la distancia del stop, sin bajar nunca del breakeven.
4. **Cierre por tiempo** a las 24 horas.

Rejilla: 2 temporalidades × 2 entradas × 3 stops × 4 opciones de breakeven × 2 salidas = **96 configuraciones**.

**Ejecución y costes (futuros):**
- **Entrada:** a mercado, 0,05 % de comisión + 0,02 % de deslizamiento.
- **Stop y cierre por tiempo:** a mercado, 0,05 % + 0,02 %. En el stop se suma además un 10 % de lo que la vela haya atravesado el nivel.
- **Objetivo:** orden límite, 0,02 %.
- **Funding:** el real, cobrado cada 8 h sobre el nocional.
- **Ambigüedad dentro de una vela de 5 min:** si se tocan a la vez el stop y el objetivo (o el nivel del breakeven), se supone **el stop primero**. El breakeven y el stop que persigue se aplican desde la vela siguiente.

**Apalancamiento:** 10x sobre el capital de cada activo (50 % cada uno), con interés compuesto y margen aislado. **Liquidación** si el mínimo (o máximo, en cortos) de una vela alcanza el precio de liquidación antes de que se ejecute el stop (margen de mantenimiento 0,5 %). Una sub-cuenta liquidada recibe capital en el siguiente reparto mensual.

## Periodos

- **Desarrollo:** 1-6-2018 a 31-12-2023.
- **Examen final:** 1-1-2024 a 21-10-2026. Se ejecuta **una sola vez** con la configuración congelada.
- **Transparencia:** ya se han visto datos de todo el periodo para otras estrategias. En concreto, la estrategia B (comprar caídas en tendencia alcista) funcionó hasta 2024 y falló en 2025–2026. Para no sesgar la selección, la entrada de retroceso se incluye igualmente y la elección sigue la regla fijada aquí.

## Selección (fijada antes de ver resultados)

En desarrollo, entre las 96 configuraciones con al menos 150 operaciones (BTC+ETH), se elige la de **mayor rentabilidad neta media por operación** (medida sin apalancar).

## Criterios de aprobado (todos)

1. **Desarrollo:** rentabilidad neta media por operación > 0 con t ≥ 2.
2. **Mejor que el azar:** supera al percentil 95 de las entradas aleatorias con la misma gestión.
3. **Robustez:** al menos la mitad de sus vecinas tiene rentabilidad neta media positiva en desarrollo. Vecinas = misma entrada y temporalidad, stop y breakeven a un paso, ambas salidas.
4. **Examen final:** rentabilidad neta media por operación > 0.
5. **Riesgo a 10x:**
   - en el examen, peor caída ≤ 50 % y ninguna liquidación;
   - en una simulación de 1 año remuestreando las operaciones de desarrollo, probabilidad de caer más de un 50 % ≤ 5 %.
   - Si solo falla este punto, se informa del mayor apalancamiento que sí lo cumple.

**Informativo:** efecto del breakeven (misma configuración con y sin él), largos frente a cortos, BTC frente a ETH, resultados por año y barrido de apalancamiento (1x, 2x, 3x, 5x, 10x).

---

## Resultados

*(Pendiente: se añadirán tras ejecutar los tests.)*
