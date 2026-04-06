# Guía de desarrollo local

## Requisitos previos

- Python 3.10+
- pip

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/ortego88/geo-newsletter
cd geo-newsletter

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Copiar el archivo de entorno
cp .env.example .env
# Edita .env y rellena las variables necesarias
```

## Ejecución

```bash
python run_all.py
```

La aplicación estará disponible en **http://localhost:8080**

## Páginas disponibles

| URL | Descripción |
|-----|-------------|
| `/` | Landing pública |
| `/pricing` | Página de precios |
| `/register` | Registro de usuario (prueba 7 días) |
| `/login` | Iniciar sesión |
| `/dashboard` | Área privada (requiere login) |
| `/dashboard/settings` | Configuración de activos y Telegram |
| `/subscribe/<plan>` | Checkout de suscripción |
| `/health` | Health check para Railway |

## Pagos en modo test (Stripe)

Sin `STRIPE_SECRET_KEY` configurada, los pagos se simulan localmente.

Para probar el flujo de pago usa la tarjeta de prueba:

```
Número: 4242 4242 4242 4242
Caducidad: cualquier fecha futura (ej: 12/26)
CVC: cualquier 3 dígitos (ej: 123)
```

## Base de datos

- `data/predictions.db` — predicciones y análisis del pipeline
- `data/app.db` — usuarios, suscripciones y métodos de pago

## Variables de entorno importantes

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Clave secreta para sesiones Flask |
| `STRIPE_PUBLISHABLE_KEY` | Clave pública de Stripe (pk_test_...) |
| `STRIPE_SECRET_KEY` | Clave secreta de Stripe (sk_test_...) |
| `APP_DB_PATH` | Ruta a la base de datos de la app (default: data/app.db) |
| `OPENAI_API_KEY` | API key de OpenAI para el pipeline |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram para alertas |
