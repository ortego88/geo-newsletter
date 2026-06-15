# 🔧 Changelog - Mejoras del Modelo de Predicción

**Fecha:** 15 de junio de 2026  
**Objetivo:** Mejorar accuracy de 44.5% → 55-60% en 1 semana

---

## 🐛 Fixes Críticos Implementados

### 1. ✅ Corregido Bug de Señales UP Silenciosas
**Archivo:** `src/services/price_signals.py:275`

**Antes:**
```python
is_alertable = is_down and is_early  # ❌ Solo bajadas tempranas
```

**Después:**
```python
is_alertable = is_early  # ✅ Alertar 3-5% en AMBAS direcciones
```

**Impacto:** 
- Ahora se alertan movimientos de SUBIDA del 3-5% (antes eran todos silenciosos)
- Se mantienen silenciosos los movimientos >5% (demasiado tarde para actuar)
- Esperamos ver ~50% de señales UP / 50% DOWN en lugar del sesgo actual

---

### 2. ✅ Validación de Precios Outliers
**Archivo:** `src/services/prediction_tracker.py:324-347`

**Cambios:**
- Añadida validación para rechazar precios ≤ 0
- Detección de outliers (ratio >10x o <0.1x respecto a precio anterior)
- Logging de advertencia cuando se detectan precios sospechosos
- Previene que precios corruptos entren en la base de datos

**Impacto:**
- Evita validaciones incorrectas como GRT: $0.0209 → $0.4543
- Facilita debugging de problemas en RealPriceFetcher

---

### 3. ✅ Logging Mejorado en RealPriceFetcher
**Archivo:** `src/services/real_price_fetcher.py:257-273`

**Cambios:**
- Validación de precio > 0 antes de cachear
- Logging automático cuando el precio cambia >50% desde el caché
- Ayuda a detectar problemas en las fuentes de datos

**Impacto:**
- Detección temprana de precios incorrectos
- Mejor debugging de problemas de caché

---

## 🎯 Optimizaciones de Parámetros

### 4. ✅ Ventana de Análisis: 4h → 6h
**Archivo:** `src/services/price_signals.py:109`

**Cambio:**
```python
_KLINE_INTERVAL = "6h"  # Antes: "4h"
```

**Razón:** Reducir ruido del mercado y mejorar calidad de señales

**Impacto esperado:**
- Menos señales falsas por volatilidad a corto plazo
- Movimientos más sostenidos y confirmados

---

### 5. ✅ Threshold Mínimo: 2.5% → 3.0%
**Archivo:** `src/services/price_signals.py:17`

**Cambio:**
```python
THRESHOLD_PCT = 3.0  # Antes: 2.5%
```

**Razón:** Generar solo señales fuertes, descartar movimientos menores

**Impacto esperado:**
- Menos volumen de predicciones
- Mayor accuracy por señal más fuerte

---

## 🧠 Mejoras en el Modelo

### 6. ✅ Prompt de Claude Mejorado
**Archivo:** `src/services/claude_analyzer.py:68-100`

**Mejoras:**
1. **Nueva regla para movimientos de precio:**
   - Movimiento 3-5% CON volumen alto Y tendencia 24h alineada → confidence 70-75
   - Movimiento SIN momentum o contra-tendencia → confidence < 60

2. **Criterios más específicos:**
   - Explica cuándo dar confidence 70-79 para price signals
   - Añade criterio de momentum y alineación de tendencia

3. **Mejor calibración:**
   - Movimientos con momentum fuerte ahora pueden alcanzar confidence 70-79
   - Reduce predicciones de movimientos contra-tendencia

**Impacto esperado:**
- Mejor discriminación entre señales fuertes y débiles
- Más contexto para evaluar movimientos de precio ya ocurridos

---

### 7. ✅ Exclusión Temporal de Activos con 0% Accuracy
**Archivo:** `src/services/price_signals.py:23-45`

**Activos excluidos:**
- PEPE (0/3 predicciones correctas)
- XRP (0/2)
- ATOM (0/2)
- LDO (0/2)
- SNX (0/2)

**Activos mantenidos pese a baja accuracy:**
- BTC (25% - 1/4) → mantener para aprendizaje
- ETH (0% - 0/1) → solo 1 muestra, mantener

**Re-evaluación:** 22 de junio de 2026

**Impacto esperado:**
- Evita acumular más predicciones incorrectas en estos activos
- Se reevaluarán cuando mejore el prompt

---

### 8. ✅ Source Mejorado para Señales
**Archivo:** `src/services/price_signals.py:285`

**Cambio:**
```python
"source": f"Price Monitor ({'alerta temprana' if is_alertable else 'calibración silenciosa'})"
```

**Impacto:**
- Mejor tracking de qué señales fueron alertadas vs silenciosas
- Facilita análisis de métricas por tipo de señal

---

## 📊 Resultados Esperados

### Antes de los cambios (9-15 Jun):
- **Accuracy:** 44.5% (49/110)
- **Señales UP alertadas:** 0% (todas silenciosas)
- **Señales DOWN alertadas:** 100%
- **Threshold:** 2.5%
- **Ventana:** 4h

### Después de los cambios (esperado para 16-22 Jun):
- **Accuracy objetivo:** 55-60%
- **Señales UP alertadas:** ~50%
- **Señales DOWN alertadas:** ~50%
- **Threshold:** 3.0%
- **Ventana:** 6h

---

## 🔄 Próximos Pasos

### Esta semana (16-22 Jun):
1. ✅ Monitorear accuracy diaria
2. ✅ Verificar distribución UP/DOWN
3. ✅ Revisar logs de precios outliers
4. ✅ Analizar resultados el viernes 20 Jun

### Semana siguiente (23-29 Jun):
1. Fine-tuning de confidence thresholds
2. Evaluar re-inclusión de activos excluidos
3. Considerar añadir contexto de volumen al prompt
4. Implementar A/B testing de parámetros

---

## 📝 Archivos Modificados

1. `src/services/price_signals.py` - Fixes críticos + optimización parámetros
2. `src/services/prediction_tracker.py` - Validación de precios outliers
3. `src/services/real_price_fetcher.py` - Logging mejorado
4. `src/services/claude_analyzer.py` - Prompt mejorado + nuevas reglas

---

## 🎯 Métricas a Monitorear

1. **Accuracy global** (objetivo: 55-60%)
2. **Accuracy por dirección** (UP vs DOWN, objetivo: similar en ambas)
3. **Volumen de señales** (esperado: reducción ~20% por threshold más alto)
4. **Distribución alertables/silenciosas** (objetivo: 70% alertables, 30% silenciosas)
5. **Precios outliers detectados** (revisar logs diariamente)

---

**Revisión programada:** Viernes 20 de junio de 2026
