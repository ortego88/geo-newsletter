# Guía de desarrollo local

## Requisitos previos

- Python 3.10+
- pip
- PostgreSQL 14+ (obligatorio en todos los entornos)

## Setup local con PostgreSQL

1. **Instalar PostgreSQL** en tu máquina (https://www.postgresql.org/download/)

2. **Crear base de datos:**
   ```bash
   createdb geo_newsletter
   ```

3. **Copiar `.env.example` a `.env` y configurar `DATABASE_URL`:**
   ```bash
   cp .env.example .env
   # Editar .env con tus credenciales de PostgreSQL
   # DATABASE_URL=postgresql://postgres:tupassword@localhost:5432/geo_newsletter
   ```

4. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Inicializar la base de datos** (se crea automáticamente al arrancar la app):
   ```bash
   python run_all.py
   ```

## Instalación rápida (resumen)

```bash
# 1. Clonar el repositorio
git clone https://github.com/ortego88/geo-newsletter
cd geo-newsletter

# 2. Crear base de datos PostgreSQL
createdb geo_newsletter

# 3. Copiar el archivo de entorno
cp .env.example .env
# Edita .env y rellena DATABASE_URL y demás variables necesarias

# 4. Instalar dependencias
pip install -r requirements.txt
```

## Ejecución

### Modo desarrollo (hot-reload recomendado)

Con `FLASK_ENV=development` el servidor Flask recargará automáticamente cuando detecte cambios en el código o en los templates, sin necesidad de reiniciarlo manualmente.

```bash
FLASK_ENV=development python run_all.py
```

O bien, añade `FLASK_ENV=development` a tu `.env` para que se active siempre.

### Modo producción (por defecto)

```bash
python run_all.py
```

La aplicación estará disponible en **http://localhost:8080**

## Deploy en Railway

1. En tu proyecto Railway: *New* → *Database* → **PostgreSQL**
2. Railway creará automáticamente la variable `DATABASE_URL` en tu servicio web
3. Si no aparece automáticamente:
   - Ve a tu servicio web → *Variables*
   - Añade `DATABASE_URL` con el valor de conexión del servicio PostgreSQL
4. En el próximo deploy, la app usará PostgreSQL y el histórico se conservará entre deploys ✅

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
| `/admin` | Panel de administración |
| `/admin/reset-predictions` | Borrar histórico de predicciones (única forma permitida) |

## Pagos en modo test (Stripe)

Sin `STRIPE_SECRET_KEY` configurada, los pagos se simulan localmente.

Para probar el flujo de pago usa la tarjeta de prueba:

```
Número: 4242 4242 4242 4242
Caducidad: cualquier fecha futura (ej: 12/26)
CVC: cualquier 3 dígitos (ej: 123)
```

## Base de datos

La app usa **PostgreSQL** para todas las tablas:
- `users` — usuarios y autenticación
- `subscriptions` — suscripciones y planes
- `payment_methods` — métodos de pago (Stripe)
- `alert_log` — log de alertas enviadas
- `predictions` — predicciones y análisis del pipeline

> **Nota:** El directorio `data/` se mantiene para logs (`data/scheduler.log`) y la caché
> de deduplicación de noticias (`data/recent_articles.db`). Estos archivos son efímeros
> y se regeneran en cada deploy; no contienen datos críticos.

## Variables de entorno importantes

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | **Obligatorio.** URL de conexión a PostgreSQL |
| `SECRET_KEY` | Clave secreta para sesiones Flask |
| `STRIPE_PUBLISHABLE_KEY` | Clave pública de Stripe (pk_test_...) |
| `STRIPE_SECRET_KEY` | Clave secreta de Stripe (sk_test_...) |
| `OPENAI_API_KEY` | API key de OpenAI para el pipeline |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram para alertas |
| `ADMIN_PASSWORD` | Contraseña para acceder al panel de admin |
