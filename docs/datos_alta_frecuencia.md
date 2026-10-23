# Datos para un bot de alta o semi-alta frecuencia, y qué consultan los agentes de IA

*23 de octubre de 2026 · Cada fuente gratuita se ha comprobado descargando una muestra o llamando a su API.*

## Resumen

- **Hay mucho dato público y gratuito.** Binance publica años de historia de microestructura (operaciones una a una, profundidad del libro, interés abierto y ratios). OKX, Hyperliquid y Deribit dan el resto en directo sin clave.
- **Lo que no tiene historia gratuita hay que grabarlo uno mismo** desde hoy: el libro de órdenes completo y las liquidaciones. También se puede comprar (Tardis.dev).
- **Los agentes de IA consultan estos mismos datos públicos** a través de conectores (MCP) de los exchanges y de agregadores. No tienen datos privilegiados y deciden cada pocos minutos, así que no son de alta frecuencia.
- **El obstáculo no son los datos, son los costes.** La semi-alta frecuencia solo puede funcionar con órdenes límite (que no pagan el diferencial) y comisiones bajas. La alta frecuencia real, de milisegundos, no está al alcance de una cuenta particular.

## 1. Datos de mercado de los exchanges (microestructura)

| Dato | Para qué sirve | Histórico gratis | En directo |
|---|---|---|---|
| **Operaciones una a una** (precio, cantidad, lado que agrede, milisegundo) | Flujo de órdenes: quién compra o vende a mercado y con qué fuerza | Binance: futuros desde 2019 (BTC: 3,1 millones al día, 23 MB comprimidos) y spot desde 2017 | WebSocket de cualquier exchange |
| **Profundidad del libro** (liquidez a ±0,2 %, ±1 %… ±5 % del precio) | Desequilibrio entre compradores y vendedores; coste de ejecutar | Binance `bookDepth`: una foto cada 30 s desde 2023 (0,6 MB al día) | OKX y Binance, 100 ms; OKX incluye el nº de órdenes por nivel |
| **Libro completo tick a tick** | Reconstruir la cola de órdenes; simular órdenes límite | No gratis. Tardis.dev: gratis solo el día 1 de cada mes; el resto, de pago | Grabarlo uno mismo |
| **Mejor compra/venta y diferencial** | Coste real de entrar y salir | Binance `bookTicker`: solo de mayo 2023 a marzo 2024 | Todos |
| **Velas de 1 segundo** | Precio y volumen a alta resolución | Binance spot desde 2017 (2,3 MB al día) | Todos |
| **Funding** | Coste de mantener la posición; sentimiento | Binance (desde 2019) | OKX, Binance, Hyperliquid |
| **Interés abierto, ratios largos/cortos, volumen comprador/vendedor** | Posicionamiento y apalancamiento del mercado | Binance `metrics` cada 5 min desde 2020 | OKX `rubik` (5 min), Hyperliquid |
| **Liquidaciones** | Cascadas de ventas o compras forzadas | No gratis (agregadores de pago como Coinglass) | OKX (endpoint público), Binance (stream; envía solo la última de cada segundo por contrato), Hyperliquid |
| **Precio de marca, índice y prima** (perpetuo frente a spot) | Tensión entre futuros y contado | Binance desde 2019-2020 | Todos |
| **Volatilidad implícita** (opciones) | Lo que el mercado espera que se mueva | Binance BVOL (cada segundo) | Deribit DVOL (API gratis) |

## 2. Lo que solo ofrece Hyperliquid

Al ser un exchange en cadena, todo es público:
- **Cada operación lleva las direcciones del comprador y del vendedor** (comprobado en su API).
- **Se ven la posición, el apalancamiento y el precio de liquidación de cualquier cuenta.** Permite seguir a las cuentas grandes y estimar dónde están las liquidaciones.
- **Archivo histórico en S3:**
  - el bucket `hyperliquid-archive` tiene fotos del libro y el contexto de cada activo;
  - el bucket `hl-mainnet-node-data` tiene las operaciones por bloque;
  - se actualiza de forma irregular y paga la descarga quien la hace.

## 3. Fuera de los exchanges

- **Entre exchanges:**
  - **la prima de Coinbase** (precio en Coinbase frente a Binance) se usa como señal de demanda en EE. UU.;
  - **qué exchange se adelanta** a los demás en los movimientos de precio.
- **En cadena:** entradas y salidas de los exchanges, emisión de stablecoins y grandes transferencias. Proveedores: Glassnode, CryptoQuant, Arkham, Nansen y Dune, casi todos de pago o con una capa gratuita limitada.
- **Sentimiento y noticias:**
  - el índice de miedo y codicia es gratis y diario;
  - noticias: CryptoPanic;
  - redes sociales: X, Kaito, LunarCrush, Santiment, todos de pago.
- **Macro:** calendario económico (IPC, Reserva Federal), flujos de los ETF de bitcoin, bolsa y dólar.

Para la semi-alta frecuencia estos datos cuentan poco, porque son lentos, salvo las noticias que mueven el precio de golpe.

## 4. Qué consultan los agentes de IA de trading

- **Conectores (MCP) de los exchanges.** Dan a un modelo de lenguaje acceso a los datos y, si se le permite, a operar:
  - **OKX Agent Trade Kit** (`github.com/okx/agent-trade-kit`). Sin claves para datos de mercado: precios, velas, libro de órdenes, funding, precio de marca, interés abierto y su historia, y más de 70 indicadores técnicos. Tiene un módulo de "smart money" (clasificaciones y posiciones de traders) y un modo de solo lectura.
  - **Otros exchanges:** Bybit (abril 2026), Binance Agent OS (agosto 2026), Bitget y Robinhood (julio 2026).
- **Agregadores:** CoinGecko y CoinMarketCap para precios y capitalización; CCXT y Hummingbot para operar en muchos exchanges con el mismo código.
- **Un ejemplo público: Alpha Arena (Nof1, octubre–noviembre 2025).**
  - **Qué hicieron:** seis modelos de lenguaje operaron futuros en Hyperliquid con 10.000 $ cada uno durante 17 días.
  - **Qué datos tenían:** el texto oficial de las instrucciones no se publicó. Según una reconstrucción no oficial, cada 2–3 minutos recibían precio, medias, MACD y RSI (en velas de 3 minutos y de 4 horas), interés abierto, funding y el estado de su cuenta, sin noticias.
  - **Resultado:** ganó Qwen3-Max (+22 %), y GPT-5 y Gemini 2.5 Pro acabaron con pérdidas fuertes. Con 17 días y una sola tirada, es sobre todo ruido.
- **Conclusión:** los agentes usan los mismos datos públicos que cualquiera. Lo que aporta el modelo es interpretar y automatizar, no velocidad ni información exclusiva.

## 5. Qué haría falta para la semi-alta frecuencia

- **Los costes mandan.** En el análisis de velas de 1 minuto (`intradia_1min.md`), los costes de ida y vuelta (~0,14 % con órdenes a mercado) eran 2,5 veces lo que arriesgaba el stop. Las señales de microestructura suelen anticipar movimientos de pocos puntos básicos en segundos o minutos.
- **Solo tiene opciones con órdenes límite** (comisión maker del 0,02 % o menos, sin pagar el diferencial). Pero entonces hay que medir dos cosas que las velas no dan: con qué probabilidad se llena la orden y si se llena justo cuando el precio va en contra. Para eso hacen falta el libro y las operaciones.
- **La alta frecuencia real** (milisegundos) exige servidores junto al motor del exchange, niveles de comisión VIP y competir con creadores de mercado profesionales. No es viable con 5.000 €.

## 6. Plan propuesto

1. **Descargar ya el histórico gratuito de Binance** (BTC y ETH, 2023–2026): operaciones una a una, profundidad del libro, `metrics`, precio de marca y prima. Las operaciones pueden resumirse al segundo (volumen comprador y vendedor, nº de operaciones), lo que ocupa unas 100 veces menos.
2. **Grabar en directo 24/7** en un servidor pequeño, porque este entorno es temporal y no se debe usar el PC de la empresa:
   - libro de órdenes (20 niveles cada 100 ms) y operaciones de BTC y ETH en OKX, Binance y Hyperliquid;
   - funding, interés abierto y liquidaciones cada minuto;
   - del orden de cientos de MB al día comprimidos.
3. **Con 1–3 meses grabados, probar hipótesis concretas** con protocolo pre-registrado, como hasta ahora, y siempre con costes de órdenes límite y probabilidad de llenado:
   - desequilibrio del libro o del flujo → movimiento en 1–60 s;
   - cascadas de liquidaciones → rebote o continuación;
   - funding o interés abierto extremos;
   - prima de Coinbase y adelanto entre exchanges.

## Fuentes consultadas

- Binance Data: https://data.binance.vision (listado del bucket y muestras del 21-10-2026)
- Tardis.dev: https://tardis.dev/ · https://docs.tardis.dev/historical-data-details
- Hyperliquid, datos históricos: https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data
- OKX Agent Trade Kit: https://github.com/okx/agent-trade-kit
- Conectores MCP de exchanges: https://www.tradingview.com/news/chainwire:3c517c0ef094b:0-bybit-ai-expands-to-infrastructure-layer-with-official-mcp-release-for-multi-agent-trading/ · https://www.bitget.com/academy/best-official-crypto-exchange-mcp-servers-ai-agents-2026-introduction-to-bitget-mcp · https://genfinity.io/2026/07/21/robinhood-agentic-trading-crypto-ai-agents/ · https://icrrd.com/blog-article/5400/7-best-ai-agents-for-crypto-trading-in-2026
- Alpha Arena: https://gist.github.com/wquguru/7d268099b8c04b7e5b6ad6fae922ae83 (reconstrucción no oficial del prompt) · https://decrypt.co/345006/ai-crypto-trading-showdown-deepseek-grok-winning-gemini-implodes · https://iweaver.ai/blog/alpha-arena-ai-trader-showdown
