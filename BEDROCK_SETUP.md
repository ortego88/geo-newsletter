# Configurar Claude via AWS Bedrock en Railway

## 🎯 Ventajas de usar Bedrock

- ✅ **Más económico** que API directa de Anthropic
- ✅ **Integración con AWS** (si ya tienes infraestructura allí)
- ✅ **Créditos de AWS** pueden aplicarse
- ✅ **Mismo modelo**: Claude 3.5 Sonnet

---

## 📋 Pre-requisitos en AWS

### 1. Habilitar Claude en Bedrock

1. Ve a la consola de AWS Bedrock: https://console.aws.amazon.com/bedrock/
2. Selecciona tu región (recomendado: `us-east-1` o `eu-west-1`)
3. Ve a **"Model access"** en el menú lateral
4. Click en **"Manage model access"**
5. Busca **"Anthropic"** y marca:
   - ✅ Claude 3.5 Sonnet v2
6. Click en **"Request model access"**
7. Espera aprobación (usualmente instantáneo)

### 2. Crear IAM User con permisos

1. Ve a IAM: https://console.aws.amazon.com/iam/
2. **Users** → **Create user**
3. Nombre: `geo-newsletter-bedrock`
4. **Next** → **Attach policies directly**
5. Busca y adjunta: `AmazonBedrockFullAccess`
   - O crea una política custom más restrictiva:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-*"
       }
     ]
   }
   ```
6. **Create user**
7. Selecciona el usuario → **Security credentials**
8. **Create access key**
9. Selecciona: **"Application running outside AWS"**
10. **Guarda** el `Access Key ID` y `Secret Access Key` ⚠️ (solo se muestra una vez)

---

## 🚂 Configurar en Railway

### Variables de entorno requeridas:

Ve a tu proyecto en Railway → **Variables** → Añade estas variables:

```bash
# ============================================
# BEDROCK - ACTIVAR CLAUDE VIA AWS
# ============================================
USE_BEDROCK=true

# Credenciales AWS (del paso anterior)
AWS_ACCESS_KEY_ID=AKIA.....................
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG...

# Región donde habilitaste Bedrock
AWS_REGION=us-east-1

# Modelo de Claude en Bedrock
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0

# ============================================
# FALLBACK (opcional - mantener OpenAI)
# ============================================
OPENAI_API_KEY=sk-proj-xxxxx  # Tu key actual
OPENAI_MODEL=gpt-4o-mini
```

### Modelos disponibles en Bedrock:

| Modelo | Model ID en Bedrock |
|--------|---------------------|
| Claude 3.5 Sonnet v2 **(Recomendado)** | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Claude 3 Opus | `anthropic.claude-3-opus-20240229-v1:0` |
| Claude 3 Sonnet | `anthropic.claude-3-sonnet-20240229-v1:0` |
| Claude 3 Haiku | `anthropic.claude-3-haiku-20240307-v1:0` |

---

## ✅ Verificar configuración

Después de añadir las variables en Railway:

### 1. Railway redesplegará automáticamente
Espera 1-2 minutos.

### 2. Revisa los logs
En Railway → **Deployments** → Último deploy → **View Logs**

Busca estas líneas:
```bash
✅ Claude via Bedrock configurado correctamente
Usando Claude via AWS Bedrock (región: us-east-1)
🚀 Analizando evento con Claude (Anthropic) + RAG...
```

### 3. Si ves errores

**Error: "AccessDeniedException"**
→ El IAM user no tiene permisos para Bedrock
→ Revisa la política IAM

**Error: "ValidationException: The provided model identifier is invalid"**
→ El BEDROCK_MODEL_ID no es correcto o no está habilitado
→ Verifica en AWS Bedrock → Model access

**Error: "ResourceNotFoundException"**
→ El modelo no está disponible en tu región
→ Cambia AWS_REGION a una región donde esté disponible (us-east-1 siempre funciona)

**Error: "ThrottlingException"**
→ Límite de requests excedido
→ Configura límites en AWS Bedrock o espera unos minutos

---

## 💰 Costes en Bedrock

**Claude 3.5 Sonnet v2** en Bedrock:

| Tipo | Precio | Por predicción* |
|------|--------|----------------|
| Input tokens | $3.00 / 1M tokens | ~$0.006 |
| Output tokens | $15.00 / 1M tokens | ~$0.004 |
| **Total por predicción** | | **~$0.01** |

*Estimado: 2K tokens input + 300 tokens output

**Comparación:**
- Bedrock: ~$0.01 por predicción
- API directa Anthropic: ~$0.01 por predicción (mismo precio)
- GPT-4o-mini: ~$0.001 por predicción (más barato pero menos accuracy)

💡 **Ventaja real**: Si tienes créditos de AWS o descuentos corporativos, Bedrock puede ser gratis o más barato.

---

## 🔒 Seguridad

### Permisos mínimos IAM (recomendado):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeOnly",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    }
  ]
}
```

### Configurar límites de gasto:

1. AWS Budgets: https://console.aws.amazon.com/billing/home#/budgets
2. **Create budget** → **Cost budget**
3. Budget amount: $50/mes (ajustar según necesidad)
4. Configurar alertas al 50%, 75%, 90%

---

## 🔄 Cambiar de Bedrock a API directa

Si en el futuro quieres cambiar:

**Bedrock → API directa:**
```bash
# Cambiar en Railway:
USE_BEDROCK=false
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

**API directa → Bedrock:**
```bash
# Cambiar en Railway:
USE_BEDROCK=true
# (mantener las variables AWS_*)
```

---

## 📊 Monitoreo de uso

### En AWS CloudWatch:
1. Ve a CloudWatch → **Metrics** → **Bedrock**
2. Puedes ver:
   - Número de invocaciones
   - Input/output tokens
   - Latencia
   - Errores

### Dashboard recomendado:
```
- InvocationCount (suma)
- InputTokens (suma)
- OutputTokens (suma)
- InvocationErrors (suma)
```

---

## 🚀 Quick Start Checklist

- [ ] Habilitar Claude 3.5 Sonnet v2 en AWS Bedrock
- [ ] Crear IAM user con permisos de Bedrock
- [ ] Copiar Access Key ID y Secret Access Key
- [ ] Añadir variables en Railway:
  - [ ] `USE_BEDROCK=true`
  - [ ] `AWS_ACCESS_KEY_ID=...`
  - [ ] `AWS_SECRET_ACCESS_KEY=...`
  - [ ] `AWS_REGION=us-east-1`
  - [ ] `BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0`
- [ ] Esperar redeploy en Railway (~1-2 min)
- [ ] Verificar logs: "✅ Claude via Bedrock configurado"
- [ ] Configurar alertas de presupuesto en AWS

---

## 🆘 Troubleshooting

### "Boto3 no está instalado"
```bash
pip install boto3>=1.28.0
```
O espera que Railway lo instale automáticamente del `requirements.txt`

### "No module named 'anthropic'"
```bash
pip install anthropic>=0.25.0
```

### "Bedrock no disponible en esta región"
Regiones con Claude disponibles:
- ✅ us-east-1 (Virginia)
- ✅ us-west-2 (Oregon)
- ✅ eu-west-1 (Ireland)
- ✅ eu-central-1 (Frankfurt)
- ✅ ap-northeast-1 (Tokyo)

### Sistema sigue usando OpenAI
Verifica que `USE_BEDROCK=true` esté en Railway (sensible a mayúsculas)

---

## 📈 Mejora esperada

Igual que con API directa:

| Métrica | Antes (GPT-3.5) | Con Claude + RAG | Mejora |
|---------|-----------------|------------------|--------|
| **Accuracy** | ~60-65% | ~75-80% | **+15-20%** |
| **High confidence** | ~70% | ~85%+ | **+15%** |
| **Falsos positivos** | Alto | Bajo | **-30%** |

**Mismo resultado**, diferente método de acceso.

---

¿Necesitas ayuda con algún paso específico de AWS o Railway?
