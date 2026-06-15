# 🎯 Recomendaciones para Mejorar el Modelo de Predicción

**Fecha:** 15 de junio de 2026  
**Accuracy actual:** 44.5% (objetivo: 65-70%)

---

## 🔍 Problemas Detectados

### 1. ⚠️ BUG CRÍTICO: Señales de SUBIDA nunca se alertan

**Ubicación:** `src/services/price_signals.py:275`

```python
is_alertable = is_down and is_early  # ❌ Solo bajadas tempranas
```

**Impacto:**
- **TODAS las señales de subida (UP) son silenciosas** → No se envían a usuarios
- Solo se alertan bajadas tempranas (2.5-5%)
- Esto sesga el sistema hacia predicciones bajistas

**Evidencia en datos:**
- 124 de 131 predicciones vienen de "Price Monitor"
- Solo señales DOWN se han estado alertando a usuarios
- Las UP se guardan en BD pero nunca se notifican

**Solución propuesta:**
```python
# Opción A: Alertar tanto subidas como bajadas tempranas
is_alertable = is_early  # 2.5-5% en cualquier dirección

# Opción B: Solo subidas (protección bajista)
is_alertable = not is_down and is_early  # Solo UP 2.5-5%

# Opción C: Ambas direcciones pero con filtro adicional
is_alertable = is_early and abs(change) >= 3.0  # 3-5% en cualquier dirección
```

### 2. 🐛 Precios de validación incorrectos

**Activos afectados:**
- GRT: $0.0209 → $0.4543 (x21 error)
- EOS: $0.7799 → $0.0735 (/10 error)  
- TAO: $270.57 → $0.00

**Causa probable:** Problemas en `RealPriceFetcher` con ciertos símbolos de Binance o fallback a fuentes incorrectas.

### 3. 📊 Accuracy muy baja (44.5%)

**Distribución de aciertos:**
- Activos 100%: PENDLE, XLM, DYDX, WIF (pequeña muestra)
- Activos 0%: PEPE, XRP, ATOM, LDO, SNX, ETH
- BTC: solo 25% (4 predicciones)

---

## 🤔 ¿Dejar correr o hacer cambios?

### Opción A: 🟢 HACER CAMBIOS AHORA (Recomendado)

**Por qué:**

1. **Bug crítico de señales UP silenciosas**
   - Es un error de lógica, no una decisión de diseño consciente
   - Está sesgando todo el sistema hacia bajadas
   - Fix es simple y de bajo riesgo

2. **Precios incorrectos invalidan validaciones**
   - GRT, EOS, TAO tienen datos corruptos
   - Las validaciones de estas predicciones son inútiles
   - Corrompe las métricas de accuracy

3. **Bajo volumen aún (131 predicciones)**
   - Todavía estamos en fase temprana
   - Mejor corregir ahora que después de 1000+ predicciones
   - Los datos actuales ya son valiosos para aprender

4. **Cambios que SÍ podemos hacer sin perder histórico:**
   - ✅ Fix bug de señales UP → no afecta predicciones ya guardadas
   - ✅ Fix precios incorrectos → mejora validaciones futuras
   - ✅ Ajustar umbrales (THRESHOLD_PCT, confidence) → aplicable hacia adelante
   - ✅ Mejorar prompt de Claude → no rompe nada

**Cambios propuestos (bajo riesgo):**

1. **Corregir señales UP silenciosas** (CRÍTICO)
2. **Investigar y fix precios incorrectos** (CRÍTICO)
3. **Ajustar ventana de análisis** de 4h a 6-8h (reducir ruido)
4. **Mejorar el prompt de Claude:**
   - Añadir contexto de volumen
   - Mejor calibración de confidence
   - Referencias históricas por activo

### Opción B: 🟡 DEJAR CORRER (No recomendado)

**Cuándo tendría sentido:**
- Si ya tuviéramos 500+ predicciones validadas
- Si el accuracy fuera ~55-60% (cerca del target)
- Si no hubiera bugs críticos

**Problema:**
- Con bugs activos, cada día que pasa genera datos corruptos
- El modelo está aprendiendo de señales incorrectas
- La accuracy puede empeorar en lugar de mejorar

---

## 📋 Plan de Acción Propuesto

### 🔴 Fase 1: Fixes Críticos (HOY)

1. **Fix señales UP silenciosas**
   - Cambiar `is_alertable = is_down and is_early` 
   - A: `is_alertable = is_early`
   - **Impacto:** Empieza a alertar señales de subida

2. **Investigar precios incorrectos**
   - Revisar `RealPriceFetcher` para GRT, EOS, TAO
   - Añadir validación de precios (detectar outliers)
   - Añadir logging cuando precio cambia >50%

3. **Validar las 21 predicciones pendientes manualmente**
   - Revisar si los precios actuales son correctos
   - Forzar validación si ya pasaron 24h

### 🟡 Fase 2: Mejoras de Accuracy (Esta semana)

1. **Mejorar prompt de Claude:**
   - Añadir contexto de volumen 24h
   - Incluir RSI o indicadores de momentum
   - Mejores ejemplos históricos por activo

2. **Ajustar parámetros:**
   - Cambiar ventana de 4h → 6h (menos ruido)
   - Subir threshold de 2.5% → 3.0% (señales más fuertes)
   - Aumentar confidence mínimo de 65% → 70%

3. **Filtrar activos problemáticos temporalmente:**
   - Excluir PEPE, XRP, ATOM, LDO, SNX (0% accuracy)
   - Re-evaluar después de mejorar el prompt

### 🟢 Fase 3: Optimización (Próximas 2 semanas)

1. **Sistema de aprendizaje adaptativo:**
   - Usar datos históricos reales por activo
   - Ajustar confidence según accuracy histórica del activo
   - Prompt personalizado por categoría (memecoins vs DeFi vs L1)

2. **Métricas adicionales:**
   - Añadir Sharpe ratio de las predicciones
   - Tracking de profit/loss hipotético
   - Análisis de timing (¿cuánto tarda en validarse?)

3. **A/B testing:**
   - Probar diferentes ventanas (4h vs 6h vs 8h)
   - Probar diferentes thresholds (2.5% vs 3% vs 3.5%)
   - Comparar prompts con/sin contexto de volumen

---

## 💡 Recomendación Final

### ✅ HACER CAMBIOS AHORA

**Razones:**
1. Bug de señales UP es crítico y fácil de fix
2. Precios incorrectos invalidan validaciones
3. Bajo volumen aún → buen momento para iterar
4. Los cambios no destruyen histórico, lo complementan

**Enfoque recomendado:**
1. Fix bugs críticos HOY (señales UP + precios)
2. Dejar correr 3-4 días con los fixes
3. Analizar nuevas métricas el viernes
4. Iterar sobre prompt/parámetros la próxima semana

**Resultado esperado:**
- Accuracy pasa de 44.5% → 55-60% en 1 semana
- Mayor balance entre UP/DOWN predicciones
- Datos más limpios para aprendizaje futuro

---

## 📊 Métricas a Monitorear Post-Fix

1. **Accuracy por dirección:**
   - UP vs DOWN (debe ser similar)
   
2. **Distribución de señales:**
   - Alertables vs silenciosas
   - UP vs DOWN
   
3. **Precios de validación:**
   - % de precios que difieren >10% del precio de predicción
   - Assets con precios sospechosos
   
4. **Tiempo hasta validación:**
   - ¿Cuánto tarda en alcanzar ±2%?
   - ¿Muchas señales quedan pendientes?

---

## 🎯 Objetivo: Alcanzar 65% Accuracy

**Hoja de ruta:**
- **Semana 1 (esta):** Fix bugs → 55-60% accuracy
- **Semana 2:** Optimizar prompt → 60-65% accuracy  
- **Semana 3:** Fine-tuning parámetros → 65-70% accuracy
- **Semana 4+:** Mantener y optimizar

**Señal de éxito:**
- 65% accuracy sostenido por 7 días
- Balance 50/50 entre UP/DOWN
- Sin precios corruptos en validaciones
