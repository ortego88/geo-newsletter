# Configuración de almacenamiento persistente en Railway

## Problema

Railway destruye el filesystem del contenedor en cada redeploy. Esto significa que los archivos generados en tiempo de ejecución — como las bases de datos SQLite — se **pierden en cada deploy**.

Archivos afectados:
- `data/app.db` — Base de datos de usuarios, suscripciones y métodos de pago.
- `data/predictions.db` — Base de datos de predicciones y alertas geopolíticas.

Si no se configura almacenamiento persistente, **todos los usuarios registrados y sus datos se borrarán** en cada redeploy.

## Solución: Configurar un Persistent Volume en Railway

### Pasos

1. Entra en el panel de Railway: [railway.app](https://railway.app)
2. Selecciona tu proyecto y servicio **geo-newsletter**
3. Ve a la pestaña **"Volumes"** (o "Storage")
4. Haz clic en **"+ New Volume"**
5. Configura:
   - **Mount Path:** `/app/data`
   - **Size:** 1 GB (suficiente para SQLite)
6. Haz clic en **"Create"**
7. Railway reiniciará el servicio automáticamente

A partir de ese momento, el directorio `/app/data` (y por tanto `data/app.db` y `data/predictions.db`) **sobrevivirá entre deploys**.

### Verificación

Una vez configurado el volumen, al hacer deploy el log de arranque **no debería mostrar** el aviso:

```
⚠️  AVISO: data/app.db no existe. Si estás en Railway, configura un Persistent Volume...
```

Si el aviso sigue apareciendo, comprueba que el Mount Path del volumen es exactamente `/app/data`.

## Variable de entorno alternativa

Si prefieres usar una ruta diferente para la base de datos, puedes configurar la variable de entorno `APP_DB_PATH` en Railway:

```
APP_DB_PATH=/app/data/app.db
```

Esto permite mover la base de datos a cualquier ruta montada en un volumen persistente.

## Nota sobre backups

Railway Volumes no incluye backups automáticos en todos los planes. Se recomienda:
- Hacer exportaciones periódicas de los datos.
- Considerar migrar a PostgreSQL (Railway ofrece un addon de PostgreSQL con backups automáticos) para proyectos en producción con datos críticos.
