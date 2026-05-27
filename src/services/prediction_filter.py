"""
prediction_filter.py — Filtro basado en patrones históricos de aciertos/fallos.

Analiza la BD de predicciones pasadas para identificar qué condiciones producen
predicciones correctas vs incorrectas, y aplica ese conocimiento como filtro
antes de enviar alertas.

Factores analizados:
- Score range (¿las predicciones con score 45-60 aciertan menos que las de 70+?)
- Confidence range (¿por encima de qué umbral se acierta consistentemente?)
- Asset (¿hay activos donde siempre fallamos?)
- Source (¿hay fuentes más fiables?)
- Direction (¿acertamos más "up" que "down" o viceversa?)
- Timeframe (¿"hours" es más fiable que "days"?)
- Signal strength (¿las "high" realmente aciertan más?)
- Hour of day (¿hay horas donde acertamos más?)

El filtro se recalcula cada hora y cachea los resultados.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from web.db_engine import get_engine

logger = logging.getLogger("prediction_filter")

# Minimum sample size to consider a pattern statistically meaningful
_MIN_SAMPLES = 10
# Minimum accuracy to consider a condition "good"
_MIN_ACCURACY_PCT = 55
# Cache duration
_CACHE_TTL_SECONDS = 3600

_cached_rules: dict | None = None
_cached_at: float = 0


def _compute_accuracy_rules() -> dict:
    """Analyzes historical predictions to find patterns of success/failure."""
    rules = {
        "min_score": 45,
        "min_confidence": 55,
        "blocked_sources": set(),
        "preferred_direction": None,
        "preferred_timeframes": set(),
        "min_score_by_asset": {},
        "stats": {},
    }

    try:
        engine = get_engine("predictions")
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT asset, direction, confidence, score, source, timeframe,
                       outcome, predicted_at
                FROM predictions
                WHERE outcome IN ('correct', 'incorrect')
                AND predicted_at >= :since
                ORDER BY predicted_at DESC
            """), {"since": (datetime.utcnow() - timedelta(days=30)).isoformat()}).fetchall()
    except Exception as e:
        logger.warning(f"Error reading predictions for filter: {e}")
        return rules

    if len(rows) < _MIN_SAMPLES:
        logger.info(f"Insufficient data for filter ({len(rows)} predictions, need {_MIN_SAMPLES})")
        return rules

    total = len(rows)
    correct = sum(1 for r in rows if r[6] == "correct")
    overall_accuracy = correct / total * 100 if total else 0
    rules["stats"]["overall"] = {"total": total, "correct": correct, "accuracy": round(overall_accuracy, 1)}

    # Analyze by asset
    by_asset: dict[str, dict] = {}
    for row in rows:
        asset = row[0] or "UNKNOWN"
        if asset not in by_asset:
            by_asset[asset] = {"correct": 0, "total": 0}
        by_asset[asset]["total"] += 1
        if row[6] == "correct":
            by_asset[asset]["correct"] += 1

    for asset, stats in by_asset.items():
        if stats["total"] >= _MIN_SAMPLES:
            acc = stats["correct"] / stats["total"] * 100
            if acc < 35:
                # Don't hard-block; raise confidence threshold for this asset
                rules["min_score_by_asset"][asset] = 75
                logger.info(f"Filter: raising threshold for {asset} (accuracy {acc:.0f}% over {stats['total']} → needs conf>=75)")

    rules["stats"]["by_asset"] = {
        k: {**v, "accuracy": round(v["correct"] / v["total"] * 100, 1)}
        for k, v in by_asset.items() if v["total"] >= 3
    }

    # Analyze by confidence ranges
    conf_ranges = [(55, 65), (65, 75), (75, 85), (85, 95)]
    best_min_conf = 55
    for low, high in conf_ranges:
        in_range = [r for r in rows if low <= (r[2] or 0) < high]
        if len(in_range) >= _MIN_SAMPLES:
            acc = sum(1 for r in in_range if r[6] == "correct") / len(in_range) * 100
            if acc >= _MIN_ACCURACY_PCT:
                best_min_conf = low
                break

    rules["min_confidence"] = best_min_conf
    rules["stats"]["confidence_analysis"] = best_min_conf

    # Analyze by score ranges
    score_ranges = [(45, 55), (55, 65), (65, 75), (75, 95)]
    best_min_score = 45
    for low, high in score_ranges:
        in_range = [r for r in rows if low <= (r[3] or 0) < high]
        if len(in_range) >= _MIN_SAMPLES:
            acc = sum(1 for r in in_range if r[6] == "correct") / len(in_range) * 100
            if acc < 40:
                best_min_score = high
                logger.info(f"Filter: raising min_score to {high} (score {low}-{high} accuracy: {acc:.0f}%)")

    rules["min_score"] = best_min_score

    # Analyze by direction
    by_dir: dict[str, dict] = {}
    for row in rows:
        d = row[1] or "neutral"
        if d not in by_dir:
            by_dir[d] = {"correct": 0, "total": 0}
        by_dir[d]["total"] += 1
        if row[6] == "correct":
            by_dir[d]["correct"] += 1

    rules["stats"]["by_direction"] = {
        k: {**v, "accuracy": round(v["correct"] / v["total"] * 100, 1)}
        for k, v in by_dir.items() if v["total"] >= 3
    }

    # Analyze by source
    by_source: dict[str, dict] = {}
    for row in rows:
        source = (row[4] or "").split(",")[0].strip().lower()
        if not source:
            continue
        if source not in by_source:
            by_source[source] = {"correct": 0, "total": 0}
        by_source[source]["total"] += 1
        if row[6] == "correct":
            by_source[source]["correct"] += 1

    for source, stats in by_source.items():
        if stats["total"] >= _MIN_SAMPLES:
            acc = stats["correct"] / stats["total"] * 100
            if acc < 30:
                rules["blocked_sources"].add(source)
                logger.info(f"Filter: blocking source '{source}' (accuracy {acc:.0f}%)")

    rules["stats"]["by_source"] = {
        k: {**v, "accuracy": round(v["correct"] / v["total"] * 100, 1)}
        for k, v in by_source.items() if v["total"] >= 3
    }

    # Analyze by timeframe
    by_tf: dict[str, dict] = {}
    for row in rows:
        tf = row[5] or "hours"
        if tf not in by_tf:
            by_tf[tf] = {"correct": 0, "total": 0}
        by_tf[tf]["total"] += 1
        if row[6] == "correct":
            by_tf[tf]["correct"] += 1

    for tf, stats in by_tf.items():
        if stats["total"] >= _MIN_SAMPLES:
            acc = stats["correct"] / stats["total"] * 100
            if acc >= _MIN_ACCURACY_PCT:
                rules["preferred_timeframes"].add(tf)

    rules["stats"]["by_timeframe"] = {
        k: {**v, "accuracy": round(v["correct"] / v["total"] * 100, 1)}
        for k, v in by_tf.items() if v["total"] >= 3
    }

    logger.info(
        f"Filter rules updated: min_score={rules['min_score']}, "
        f"min_conf={rules['min_confidence']}, "
        f"raised_threshold_assets={list(rules['min_score_by_asset'].keys()) or 'none'}, "
        f"overall_accuracy={overall_accuracy:.1f}%"
    )

    return rules


def get_filter_rules() -> dict:
    """Returns cached filter rules, recomputing if stale."""
    global _cached_rules, _cached_at
    import time
    now = time.time()
    if _cached_rules is None or (now - _cached_at) > _CACHE_TTL_SECONDS:
        _cached_rules = _compute_accuracy_rules()
        _cached_at = now
    return _cached_rules


def should_send_alert(event: dict) -> tuple[bool, str]:
    """
    Determines if an alert should be sent based on historical patterns.

    Returns (should_send, reason).
    If should_send is False, reason explains why it was filtered.
    """
    rules = get_filter_rules()
    analysis = event.get("analysis", {})

    score = event.get("score", 0)
    confidence = analysis.get("confidence", 0)
    assets = analysis.get("most_affected_assets", [])
    primary_asset = assets[0].upper() if assets else ""
    source = (event.get("sources", [""])[0] if isinstance(event.get("sources"), list) else "").lower()
    direction = analysis.get("direction", "neutral")

    # Check minimum score (dynamic based on historical performance)
    if score < rules.get("min_score", 45):
        return False, f"score {score} < dynamic min {rules['min_score']}"

    # Check minimum confidence (dynamic)
    if confidence < rules.get("min_confidence", 55):
        return False, f"confidence {confidence} < dynamic min {rules['min_confidence']}"

    # Check assets with raised thresholds (not blocked, just higher bar)
    asset_min_conf = rules.get("min_score_by_asset", {}).get(primary_asset)
    if asset_min_conf and confidence < asset_min_conf:
        return False, f"asset {primary_asset} needs conf>={asset_min_conf} (low historical accuracy)"

    # Check blocked sources (only hard-blocks sources, not assets)
    if source in rules.get("blocked_sources", set()):
        return False, f"source '{source}' blocked (historically low accuracy)"

    return True, "passed"


def get_filter_stats() -> dict:
    """Returns the current filter statistics for display in dashboard."""
    rules = get_filter_rules()
    return rules.get("stats", {})
