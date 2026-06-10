# Revisión semanal del modelo — 16 junio 2026

## Contexto
- Semana 1 con datos limpios (umbral 2%/2%, validación por máximo 24h)
- Resultado actual: DOWN 76% accuracy, UP 17% accuracy
- UP desactivadas para usuarios desde 10 junio 2026

## Queries a ejecutar

### 1. ¿Las UP habrían llegado al 2% aunque cerraran peor?
```sql
SELECT asset, direction,
    price_at_prediction,
    price_at_validation as max_reached,
    ROUND(((price_at_validation - price_at_prediction) / price_at_prediction * 100)::numeric, 2) as max_pct,
    outcome, predicted_at
FROM predictions
WHERE direction = 'up'
  AND outcome = 'incorrect'
  AND price_at_prediction > 0
ORDER BY max_pct DESC;
```
→ Si muchas llegaron al 1.5-1.9% pero no al 2%, quizás bajar umbral a 1.5% para UP.

### 2. ¿Las UP correctas coinciden con BTC alcista?
```sql
SELECT p.asset, p.direction, p.outcome, p.predicted_at,
    p.price_at_prediction, p.price_at_validation
FROM predictions p
WHERE p.direction = 'up' AND p.outcome IN ('correct','incorrect')
ORDER BY p.predicted_at;
```
→ Correlacionar manualmente con BTC price chart ese día.

### 3. Accuracy por tipo de señal (news vs price vs microstructure)
```sql
SELECT source, direction,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE outcome='correct') as correct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE outcome='correct') / NULLIF(COUNT(*) FILTER (WHERE outcome IN ('correct','incorrect')),0), 1) as accuracy_pct
FROM predictions
WHERE outcome IN ('correct','incorrect')
GROUP BY source, direction
ORDER BY accuracy_pct DESC;
```

### 4. ¿Microstructure UP funciona mejor que price signal UP?
```sql
SELECT source,
    COUNT(*) FILTER (WHERE direction='up' AND outcome='correct') as up_correct,
    COUNT(*) FILTER (WHERE direction='up' AND outcome='incorrect') as up_incorrect,
    COUNT(*) FILTER (WHERE direction='down' AND outcome='correct') as down_correct,
    COUNT(*) FILTER (WHERE direction='down' AND outcome='incorrect') as down_incorrect
FROM predictions
WHERE outcome IN ('correct','incorrect')
GROUP BY source;
```

### 5. Estado de GEMs (validadas a 7 días)
```sql
SELECT symbol, source, price_change_24h, price_at_detection,
    price_at_validation, outcome, detected_at
FROM gem_signals
WHERE detected_at < NOW() - INTERVAL '7 days'
ORDER BY detected_at DESC;
```

## Hipótesis a validar
1. UP de price signal solo funciona cuando BTC también sube >1% en las mismas 24h
2. Whale accumulation (microstructure) tiene mejor accuracy en UP que price signals
3. El umbral óptimo para UP puede ser diferente al 2% (quizás 1.5%)
4. UP de activos correlacionados con BTC (ETH, SOL) pueden ser más fiables que altcoins

## Decisiones a tomar según resultados
- Si UP microstructure > 60% accuracy → reactivar solo esas para usuarios
- Si UP price signal > 50% con filtro BTC alcista → añadir ese filtro y reactivar
- Si todo < 50% → mantener solo DOWN por otras 2 semanas
