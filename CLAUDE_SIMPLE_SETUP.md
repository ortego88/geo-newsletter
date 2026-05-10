# Setup Simple: Claude API Directa (Recomendado)

## ⚠️ Problema encontrado con Bedrock

Tu cuenta de AWS Bedrock tiene limitaciones:
- ❌ Claude 3.X marcados como "Legacy" (requiere uso activo en últimos 30 días)
- ❌ Claude 4.X requieren "inference profiles" (configuración adicional compleja)

## ✅ Solución Recomendada: API Directa de Anthropic

**Más simple, mismo resultado, mismo coste (~$0.01 por predicción)**

### Paso 1: Obtener API Key de Anthropic

1. Ve a: https://console.anthropic.com/
2. Crea cuenta / inicia sesión
3. **API Keys** → **Create Key**
4. Nombre: "geo-newsletter-production"
5. Copia la key: `sk-ant-api03-xxxxx...`

### Paso 2: Configurar en Railway

En Railway → Tu servicio → **Variables**:

```bash
# DESACTIVAR Bedrock
USE_BEDROCK=false

# API DIRECTA DE ANTHROPIC
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx

# MANTENER OpenAI como fallback
OPENAI_API_KEY=sk-proj-xxxxx...
```

### Paso 3: Railway redesplegará automáticamente

Espera 1-2 minutos y verás en los logs:

```
✅ Analizando evento con Claude (Anthropic) + RAG...
✅ Claude (Direct API) response: ...
```

---

## 💰 Coste

**Idéntico a Bedrock**: ~$0.01 por predicción

- Claude 3.5 Sonnet via API directa
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens
- 100 predicciones/día = ~$30/mes

---

## 🎯 Ventajas de API Directa vs Bedrock

| Aspecto | API Directa | Bedrock |
|---------|-------------|---------|
| **Setup** | 2 minutos | 30+ minutos (IAM, profiles, etc) |
| **Modelos** | Todos disponibles | Requiere inference profiles |
| **Coste** | $0.01/pred | $0.01/pred (mismo) |
| **Latencia** | Baja | Baja |
| **Mantenimiento** | Cero | Gestión de IAM, profiles, etc |

---

## ✅ Variables finales en Railway

```bash
# OBLIGATORIO
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx

# DESACTIVAR BEDROCK
USE_BEDROCK=false

# MANTENER COMO FALLBACK
OPENAI_API_KEY=sk-proj-xxxxx

# RESTO DE TU CONFIG (mantener tal cual)
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
etc.
```

---

## 🔄 Si quieres volver a intentar Bedrock en el futuro

Necesitarías configurar "Cross-Region Inference Profiles" en AWS Bedrock:

1. AWS Bedrock Console → **Cross-region inference**
2. Create inference profile para Claude Sonnet 4.6
3. Usar el ARN del profile en `BEDROCK_MODEL_ID`

Pero honestamente, **la API directa es mucho más simple** y funciona igual de bien.

---

## 🚀 Test Local (después de configurar)

```bash
source .venv/bin/activate
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx \
USE_BEDROCK=false \
python test_bedrock.py
```

Deberías ver:
```
✅ Analizando evento con Claude
✅ PREDICCIÓN EXITOSA
```

---

¿Prefieres ir con la API directa? Es lo que recomiendo.
