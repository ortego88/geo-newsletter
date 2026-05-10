# Setup CoinMarketCap API (Fallback para precios crypto)

## ¿Por qué?

CoinGecko free tier tiene rate limits que causan errores 429. CoinMarketCap ofrece:
- **10,000 llamadas/mes gratis** (suficiente para tu caso de uso)
- Más fiable que CoinGecko para activos pequeños
- Fallback automático si CoinGecko falla

## Paso 1: Obtener API Key (5 minutos)

1. Ve a: https://pro.coinmarketcap.com/signup
2. Crea cuenta con tu email
3. Verifica el email
4. Ve a: https://pro.coinmarketcap.com/account
5. Copia tu **API Key** (empieza con algo como `b54bcf4d-1bcc-4e5f-...`)

## Paso 2: Configurar en Railway

En Railway → Tu servicio → **Variables**:

```bash
COINMARKETCAP_API_KEY=tu-api-key-aqui
```

## Paso 3: Test Local (opcional)

```bash
cd /Users/dani/Desktop/geo-newsletter
source .venv/bin/activate

COINMARKETCAP_API_KEY=tu-api-key-aqui python3 -c "
from src.services.real_price_fetcher import get_price

# Test con BTC
price = get_price('BTC')
print(f'BTC price: \${price}')

# Test con activo problemático
price = get_price('XRP')
print(f'XRP price: \${price}')
"
```

Deberías ver:
```
✅ BTC price: $81234.56
✅ XRP price: $1.47
```

## Paso 4: Verificar en Logs

Después de configurar en Railway, busca en los logs:

```
Usando precio de CoinMarketCap para XRP
```

Si ves eso, significa que CoinGecko falló y el fallback funcionó ✅

---

## Activos soportados

Con CoinMarketCap añadido, ahora soportamos **todos** los tickers que Claude puede recomendar:

- **IBEX35**: Todos via yfinance
- **ETFs**: Todos via yfinance  
- **Crypto principales**: BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI, LTC, ATOM, XLM, ALGO, FIL, NEAR, ARB, OP

Los activos problemáticos en los logs (USDT, HYPE, TON, etc.) son stablecoins o tokens muy pequeños que Claude **no debería recomendar** según su system prompt.

Si siguen apareciendo, significa que Claude está ignorando las reglas de activos permitidos → ajustar system prompt.
