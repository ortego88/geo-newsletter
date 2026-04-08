# Almacenamiento persistente en Railway

## Solución adoptada: PostgreSQL

La app usa **PostgreSQL** (servicio de Railway) para almacenar todos los datos críticos.
PostgreSQL es un servicio externo administrado por Railway y **persiste entre deploys** automáticamente.

## Por qué no SQLite

Railway destruye el filesystem del contenedor en cada redeploy. Si la app usara SQLite
(un fichero `.db` local), todos los datos se perderían en cada deploy.

## Configuración en Railway

1. En tu proyecto Railway: *New* → *Database* → **PostgreSQL**
2. Railway creará automáticamente la variable `DATABASE_URL` en tu servicio web
3. Si no aparece automáticamente:
   - Ve a tu servicio web → *Variables*
   - Añade `DATABASE_URL` con el valor de conexión del servicio PostgreSQL
4. En el próximo deploy, la app usará PostgreSQL y el histórico se conservará entre deploys ✅

## Datos que se conservan entre deploys

Con PostgreSQL configurado, los siguientes datos son persistentes:
- `users` — usuarios registrados y autenticación
- `subscriptions` — planes y suscripciones
- `payment_methods` — métodos de pago
- `alert_log` — historial de alertas enviadas
- `predictions` — histórico de predicciones y análisis

## Datos efímeros (no críticos)

El directorio `data/` contiene archivos auxiliares que son efímeros (se pierden en cada deploy),
pero no son críticos porque se regeneran automáticamente:
- `data/scheduler.log` — logs del scheduler
- `data/recent_articles.db` — caché de deduplicación de noticias (ventana de 48h)
- `data/seen_articles.txt` — hashes de noticias ya procesadas

## Borrar histórico de predicciones

El único modo de borrar datos es a través del endpoint de administración:

```
/admin/reset-predictions
```

Accede con la contraseña de administrador (`ADMIN_PASSWORD`).
Este endpoint borra las predicciones en PostgreSQL y limpia la caché de deduplicación.
**Los deploys NUNCA borran datos automáticamente.**
