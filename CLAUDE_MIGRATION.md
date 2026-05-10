# Migración a Claude + RAG para Mejora de Accuracy

## 🎯 Objetivo
Mejorar el ratio de aciertos de predicciones migrando de GPT-3.5 a Claude 3.5 Sonnet con RAG (Retrieval-Augmented Generation).

## ✅ Cambios implementados

### 1. **Nuevo analizador con Claude** (`claude_analyzer.py`)
- **Modelo**: Claude 3.5 Sonnet (mejor razonamiento causal)
- **Contexto largo**: Hasta 200K tokens (vs 16K de GPT-3.5)
- **Temperatura**: 0.2 (balance entre creatividad y consistencia)

### 2. **RAG básico implementado**
Ahora el sistema aprende de eventos históricos similares:

```python
# Ejemplo: para una noticia sobre "Repsol y petróleo OPEC"
# Claude busca en la BD:
# - Eventos similares de los últimos 6 meses
# - Revisa qué predicciones fueron correctas/incorrectas
# - Calcula accuracy histórico para este tipo de eventos
# - Ajusta la confidence según el patrón histórico
```

**Ventajas**:
- Si eventos similares tuvieron 80% accuracy → aumenta confidence +5-10 puntos
- Si tuvieron 30% accuracy → reduce confidence -10-15 puntos
- Aprende continuamente de sus propios aciertos/errores

### 3. **Prompt mejorado**
- Instrucciones más claras sobre calibración de confidence
- Reglas explícitas de aprendizaje histórico
- Mejor detección de opiniones vs hechos confirmados

### 4. **Sistema de fallback robusto**
```
Claude (primary) → OpenAI (fallback) → Ollama (local) → Keywords (último recurso)
```

## 📦 Instalación

### 1. Instalar nueva dependencia:
```bash
pip install anthropic>=0.25.0
```

### 2. Configurar API key de Anthropic:
Añadir al archivo `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx
CLAUDE_MODEL=claude-3-5-sonnet-20241022  # Opcional, este es el default
```

### 3. (Opcional) Mantener OpenAI como fallback:
```bash
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx  # Mantener para fallback
OPENAI_MODEL=gpt-4o-mini  # O el modelo que prefieras
```

## 🚀 Uso

**No requiere cambios en el código existente**. El sistema automáticamente:

1. Intenta usar Claude (si `ANTHROPIC_API_KEY` está configurado)
2. Si falla, usa OpenAI (si `OPENAI_API_KEY` está configurado)
3. Si falla, usa Ollama local
4. Si falla, usa análisis por keywords

Para verificar que está funcionando, revisa los logs:
```bash
# Deberías ver:
🚀 Analizando evento con Claude (Anthropic) + RAG...
Buscando eventos históricos similares...
✅ Análisis completado con Claude
```

## 📊 Mejoras esperadas

### Accuracy estimado:
- **Actual (GPT-3.5)**: ~60-65%
- **Con Claude**: ~70-75% (+10-15 puntos)
- **Con Claude + RAG**: ~75-80% (+15-20 puntos)

### Beneficios específicos:

1. **Mejor razonamiento causal**: Claude entiende mejor cómo eventos geopolíticos afectan mercados
2. **Aprendizaje continuo**: El sistema mejora con cada predicción validada
3. **Calibración mejorada**: Confidence más precisa basada en historia
4. **Menos falsos positivos**: Mejor detección de noticias especulativas

## 🔍 Ejemplos de mejora

### Antes (GPT-3.5):
```json
{
  "title": "Según analistas, Repsol podría subir por OPEC",
  "direction": "up",
  "confidence": 65,  // ❌ Demasiado alto para una opinión
  "reasoning": "OPEC puede impactar precios del petróleo"
}
```

### Ahora (Claude + RAG):
```json
{
  "title": "Según analistas, Repsol podría subir por OPEC",
  "direction": "up",
  "confidence": 45,  // ✅ Correcto: es opinión, no hecho
  "reasoning": "OPEC históricamente impacta petróleo, pero esto es solo opinión de analista",
  "historical_learning": "Eventos similares con 'según analistas' tienen 35% accuracy — confidence reducida"
}
```

## 🔧 Troubleshooting

### Error: "ANTHROPIC_API_KEY no configurada"
→ Añadir la key al archivo `.env`

### Error: "No module named 'anthropic'"
→ Ejecutar: `pip install anthropic>=0.25.0`

### El sistema sigue usando OpenAI
→ Verificar que `ANTHROPIC_API_KEY` está en `.env` y que el archivo está cargado

### Quiero volver a GPT
→ Simplemente comentar o eliminar `ANTHROPIC_API_KEY` del `.env`

## 📈 Monitoreo

Para verificar la mejora, compara métricas antes/después en el dashboard:
- **Accuracy total** (`/dashboard`)
- **Accuracy por tipo de activo** (crypto vs IBEX35)
- **Accuracy por confidence range** (predicciones >70% confidence)

## 🚧 Próximas mejoras

Estas mejoras están preparadas pero no implementadas:

1. **Vector search**: Usar embeddings para encontrar eventos más similares (mejor que keyword matching)
2. **Fine-tuning**: Entrenar modelo específico con tu histórico
3. **Ensemble**: Combinar predicciones de Claude + GPT-4 + modelo propio
4. **Prompt caching**: Reducir costes cacheando el system prompt
5. **A/B testing**: 50% Claude, 50% GPT para comparar accuracy real

## 💰 Costes

**Claude 3.5 Sonnet** (precio aprox.):
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

**Estimado por predicción**:
- ~2,000 tokens input (evento + contexto histórico)
- ~300 tokens output
- **Coste**: ~$0.01 por predicción

Si generas 100 predicciones/día: **~$1/día = $30/mes**

Comparado con el valor de mejorar accuracy del 60% al 75%, es un coste muy razonable.

## 📝 Notas técnicas

- El código es **retrocompatible** - si no configuras Anthropic, sigue usando OpenAI
- Los eventos históricos se buscan en los últimos 180 días
- El matching usa keywords simples (puede mejorarse con embeddings)
- La calibración de confidence es conservadora (reduce en caso de duda)

## ✅ Checklist de migración

- [ ] Instalar `pip install anthropic>=0.25.0`
- [ ] Obtener API key de Anthropic: https://console.anthropic.com/
- [ ] Añadir `ANTHROPIC_API_KEY` al `.env`
- [ ] Reiniciar el servicio de predicciones
- [ ] Verificar logs que digan "🚀 Analizando evento con Claude"
- [ ] Monitorear accuracy durante 1 semana
- [ ] Comparar métricas con período anterior

---

**¿Preguntas?** Revisa los logs en busca de errores o verifica que la API key esté correctamente configurada.
