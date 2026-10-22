# ¿Revisar la estrategia A cada hora o cada minuto en vez de una vez al día?

*22 de octubre de 2026 · Estrategia A (BTC y ETH, 50/50, cada mitad por separado) · Velas de 1 minuto de Binance, marzo 2018 – octubre 2026.*

## Respuesta corta

**No: revisar más a menudo empeora el resultado, y revisar cada minuto lo hunde.** La regla es la misma en todos los casos; solo cambia cada cuánto se mira.

| Cada cuánto se revisa | Rentab. anual 2018–26 | Sin costes | Peor caída | Órdenes al año | Examen 2025–26 |
|---|---|---|---|---|---|
| **Una vez al día (la validada)** | **32 %** | 34 % | **−34 %** | **85** | **+25 %** |
| Cada hora | 29 % | 38 % | −35 % | 356 | +13 % |
| Cada minuto | −15 % | 35 % | −88 % | 2.670 | −51 % |
| Mixta: vende en cualquier minuto, compra solo al cierre del día | 28 % | 32 % | −31 % | 173 | +14 % |

## Por qué

- **El cierre diario filtra el ruido.** Dentro del día, el precio cruza las medias arriba y abajo muchas veces. Mirando cada minuto, cada cruce es una compra o una venta.
- **Las señales no son peores, pero se opera muchísimo más.** Sin costes, revisar cada minuto rinde casi lo mismo que una vez al día (35 % frente a 34 % al año). Pero son 2.670 órdenes al año, unas 7 al día, y los costes (0,15 % por operación) se comen unos 50 puntos de rentabilidad al año.
- **Cada hora:**
  - antes de costes rinde algo más en desarrollo, pero no en el examen;
  - con costes pierde 3 puntos al año frente a la diaria, y en el examen gana la mitad.
- **La mixta, pensada para salir antes en los desplomes:**
  - reduce la peor caída de −34 % a −31 %;
  - a cambio, pierde 4 puntos de rentabilidad al año, y en el examen gana +14 % frente a +25 %.

## Cómo se ha calculado

- **Misma regla que la validada:** medias de 50, 100 y 200 días; volatilidad de 30 días con objetivo del 40 %; banda de 10 puntos; costes del 0,15 % por unidad operada.
- **Precio del momento:** se evalúa en cada hora o minuto. "Por encima de la media de n días" significa superar la media de los n−1 cierres diarios anteriores, que es la media de n días contando el precio actual como cierre de hoy. Así, al cierre del día coincide exactamente con la versión diaria.
- **Volatilidad:** incluye la rentabilidad del día en curso.
- **Comprobación:** la versión diaria hecha con velas de 1 minuto reproduce la validada (31,8 % frente a 31,5 % al año con velas diarias; +25 % en el examen en ambas).

## Consecuencia para el bot

Decidir **una vez al día**, con el cierre de las 00:00 UTC. El bot sí puede **vigilar** cada minuto que todo funciona (conexión, saldos, órdenes pendientes, parada de emergencia), pero sin cambiar la regla de inversión.

## Reproducir

```bash
python scripts/download_data.py --only 1m   # velas de 1 minuto de BTC y ETH
python scripts/check_frequency.py           # ~1,5 minutos → results/frecuencia/
```
