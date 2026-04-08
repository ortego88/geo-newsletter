"""
signal_resolver.py — Resuelve conflictos de dirección entre múltiples eventos
que afectan al mismo activo en el mismo ciclo del pipeline.

Reglas de resolución (por orden de prioridad):
1. Si todos los eventos apuntan a la misma dirección → usa esa dirección.
2. Si hay conflicto (up vs down), elige la señal con mayor peso combinado
   (score × confidence × fuente × tipo_evento × signal_strength).
3. Si el ganador supera al perdedor en >30% → descarta el perdedor.
4. Si la diferencia es <30% → guarda solo la ganadora con confidence reducida.
5. Si la confidence final es < MIN_FINAL_CONFIDENCE → no se guarda nada (None).
6. Filtra señales con confidence < MIN_CONFIDENCE_THRESHOLD antes de resolver.
"""

import logging
from collections import defaultdict

logger = logging.getLogger("signal_resolver")

MIN_CONFIDENCE_THRESHOLD = 45  # Subido de 40 a 45
CONFLICT_DISCARD_MARGIN = 0.30  # 30% — ganador claro vs perdedor
MIN_FINAL_CONFIDENCE = 35  # Umbral mínimo para guardar una predicción

# ---------------------------------------------------------------------------
# Pesos por fuente (calidad periodística)
# ---------------------------------------------------------------------------
SOURCE_WEIGHTS: dict[str, float] = {
    # Crypto — fuentes especializadas de alta calidad
    "coindesk": 1.5,
    "cointelegraph": 1.4,
    "decrypt": 1.3,
    "bitcoin magazine": 1.4,
    # Mercados españoles — fuentes de referencia
    "expansión": 1.5,
    "expansión mercados": 1.5,
    "el economista": 1.4,
    "cincodías": 1.4,
    "cinco días": 1.4,
    "bolsamanía": 1.3,
    "el confidencial": 1.3,
    "investing.com": 1.2,
    # Fuentes de menor peso
    "criptoblog": 0.8,
    "beincrypto": 0.9,
    "criptonoticias": 0.9,
}

# Pesos por signal_strength reportada por la IA
SIGNAL_STRENGTH_WEIGHTS: dict[str, float] = {
    "high": 1.4,
    "medium": 1.0,
    "low": 0.7,
}

# Palabras clave de alto impacto confirmado
_HIGH_IMPACT_KEYWORDS = [
    "resultados", "beneficios", "pérdidas", "earnings", "quiebra", "bankruptcy",
    "fusión", "adquisición", "merger", "acquisition", "opa", "takeover",
    "regulación", "regulation", "sec", "cnmv", "ban", "prohibición",
    "fed", "bce", "tipos de interés", "interest rate", "inflación", "inflation",
    "etf aprobado", "etf approved", "halving", "hard fork",
    "multa", "sanción", "fine", "sanction",
    "profit warning", "revisión al alza", "revisión a la baja",
]

# Palabras clave de bajo impacto (opiniones, análisis)
_LOW_IMPACT_KEYWORDS = [
    "según", "according to", "dice que", "says that", "opina", "cree que",
    "podría", "could", "might", "may", "posiblemente", "possibly",
    "analista", "analyst", "predicción", "prediction", "objetivo de precio",
    "price target", "rumor", "fuentes", "sources say",
]


def _get_source_weight(event: dict) -> float:
    """Devuelve el multiplicador de peso según la fuente de la noticia."""
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_str = " ".join(sources).lower()
    for key, weight in SOURCE_WEIGHTS.items():
        if key in source_str:
            return weight
    return 1.0


def _get_event_type_weight(event: dict) -> float:
    """Devuelve el multiplicador según el tipo/impacto del evento."""
    title = (event.get("title") or "").lower()
    desc = (event.get("description") or "").lower()
    text = title + " " + desc

    high_hits = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in text)
    low_hits = sum(1 for kw in _LOW_IMPACT_KEYWORDS if kw in text)

    if high_hits >= 2:
        return 1.6   # Evento confirmado de alto impacto
    elif high_hits == 1:
        return 1.3   # Evento de impacto moderado-alto
    elif low_hits >= 2:
        return 0.7   # Opinión/análisis, bajo impacto
    elif low_hits == 1:
        return 0.85  # Ligero descuento por incertidumbre
    return 1.0       # Neutro


def _get_signal_strength_weight(event: dict) -> float:
    """Devuelve el multiplicador según la signal_strength reportada por la IA."""
    strength = event.get("analysis", {}).get("signal_strength", "medium")
    return SIGNAL_STRENGTH_WEIGHTS.get(strength, 1.0)


def _calculate_signal_weight(event: dict) -> float:
    """
    Calcula el peso total de una señal combinando:
    - score del pipeline (relevancia temática)
    - confidence de la IA (certeza de la dirección)
    - peso de la fuente (calidad periodística)
    - tipo de evento (impacto real en mercado)
    - signal_strength reportada por la IA
    """
    score = event.get("score", 50)
    analysis = event.get("analysis", {})
    confidence = analysis.get("confidence", 50)
    source_weight = _get_source_weight(event)
    event_type_weight = _get_event_type_weight(event)
    signal_strength_weight = _get_signal_strength_weight(event)

    return score * confidence * source_weight * event_type_weight * signal_strength_weight


def resolve_signals(events: list[dict]) -> list[dict]:
    """
    Recibe la lista de eventos analizados del pipeline.
    Devuelve una lista reducida donde cada activo principal tiene como máximo
    UNA señal resuelta (la más creíble según criterios de mercado real).

    El evento devuelto es el original del pipeline, pero con el campo
    `analysis` actualizado si hubo resolución de conflicto, y con el campo
    `_conflict_resolved: True` añadido si se resolvió un conflicto.

    Si `_resolve_group()` devuelve None (señal insuficiente), el activo
    no produce ninguna entrada en la lista de salida.
    """
    # Agrupar por activo primario, descartando señales de baja confianza
    by_asset: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        analysis = event.get("analysis", {})
        assets = analysis.get("most_affected_assets", [])
        if not assets:
            continue
        primary = assets[0].upper()
        confidence = analysis.get("confidence", 0)
        if confidence < MIN_CONFIDENCE_THRESHOLD:
            logger.debug(
                f"Descartada señal baja confianza ({confidence}%) para {primary}: "
                f"{event.get('title', '')[:50]}"
            )
            continue
        by_asset[primary].append(event)

    resolved_events = []
    seen_assets = set()

    for event in events:
        analysis = event.get("analysis", {})
        assets = analysis.get("most_affected_assets", [])
        if not assets:
            resolved_events.append(event)
            continue

        primary = assets[0].upper()
        if primary in seen_assets:
            continue  # Ya procesado este activo
        seen_assets.add(primary)

        group = by_asset.get(primary, [])
        if len(group) <= 1:
            if group:
                resolved_events.append(event)
            continue

        # Múltiples eventos para el mismo activo → resolver conflicto
        resolved = _resolve_group(primary, group)
        if resolved is not None:
            resolved_events.append(resolved)
        # Si None → señal descartada por calidad insuficiente

    return resolved_events


def _resolve_group(asset: str, group: list[dict]) -> dict | None:
    """
    Resuelve un grupo de eventos que comparten el mismo activo primario.
    Devuelve el mejor evento (posiblemente modificado) o None si no hay señal fiable.
    """
    # Separar por dirección usando el peso combinado
    up_events: list[tuple[float, dict]] = []
    down_events: list[tuple[float, dict]] = []
    neutral_events: list[tuple[float, dict]] = []

    for event in group:
        analysis = event.get("analysis", {})
        direction = analysis.get("direction", "neutral")
        weight = _calculate_signal_weight(event)

        if direction in ("up", "bullish", "positive", "alza"):
            up_events.append((weight, event))
        elif direction in ("down", "bearish", "negative", "baja"):
            down_events.append((weight, event))
        else:
            neutral_events.append((weight, event))

    # Solo hay neutrales → devolver el de mayor peso
    if not up_events and not down_events:
        best = max(neutral_events, key=lambda t: t[0])[1]
        return best

    # Solo hay una dirección → devolver el mejor de esa dirección
    if not up_events:
        best = max(down_events, key=lambda t: t[0])[1]
        logger.info(f"✅ Señal unánime DOWN para {asset} ({len(down_events)} fuentes)")
        return best

    if not down_events:
        best = max(up_events, key=lambda t: t[0])[1]
        logger.info(f"✅ Señal unánime UP para {asset} ({len(up_events)} fuentes)")
        return best

    # CONFLICTO: hay señales UP y DOWN
    total_up = sum(w for w, _ in up_events)
    total_down = sum(w for w, _ in down_events)
    total = total_up + total_down

    winner_dir = "up" if total_up >= total_down else "down"
    loser_dir = "down" if winner_dir == "up" else "up"
    winner_events = up_events if winner_dir == "up" else down_events
    winner_total = total_up if winner_dir == "up" else total_down
    loser_total = total_down if winner_dir == "up" else total_up

    margin = (winner_total - loser_total) / total

    logger.warning(
        f"⚠️ Conflicto {asset}: UP={total_up:.0f} vs DOWN={total_down:.0f} "
        f"| Ganador: {winner_dir} (margen {margin:.0%})"
    )

    # Seleccionar el mejor evento de la dirección ganadora
    best_event = max(winner_events, key=lambda t: t[0])[1]
    resolved_event = dict(best_event)
    resolved_analysis = dict(resolved_event.get("analysis", {}))

    if margin >= CONFLICT_DISCARD_MARGIN:
        # Ganador claro (>30% de diferencia) → leve reducción de confidence
        confidence_penalty = 5
        logger.info(f"🏆 {asset}: {winner_dir} gana claramente (margen {margin:.0%})")
    else:
        # Señales muy parejas → mayor penalización
        confidence_penalty = 20
        logger.info(
            f"⚖️ {asset}: {winner_dir} gana por poco (margen {margin:.0%}), reduciendo confidence"
        )

    new_confidence = max(
        MIN_FINAL_CONFIDENCE,
        resolved_analysis.get("confidence", 50) - confidence_penalty,
    )
    resolved_analysis["confidence"] = new_confidence
    resolved_analysis["reasoning"] = (
        f"[Conflicto resuelto: {winner_dir.upper()} vs {loser_dir.upper()}, margen {margin:.0%}] "
        + resolved_analysis.get("reasoning", "")
    )
    resolved_event["analysis"] = resolved_analysis
    resolved_event["_conflict_resolved"] = True

    return resolved_event
