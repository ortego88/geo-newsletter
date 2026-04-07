"""
signal_resolver.py — Resuelve conflictos de dirección entre múltiples eventos
que afectan al mismo activo en el mismo ciclo del pipeline.

Reglas de resolución (por orden de prioridad):
1. Si todos los eventos apuntan a la misma dirección → usa esa dirección.
2. Si hay conflicto (up vs down), elige la señal con MAYOR score × confidence.
3. Si hay empate exacto → marca como "neutral" con el reasoning de ambas señales.
4. Filtra señales con confidence < 40 antes de resolver.
"""

import logging
from collections import defaultdict

logger = logging.getLogger("signal_resolver")

MIN_CONFIDENCE_THRESHOLD = 40


def resolve_signals(events: list[dict]) -> list[dict]:
    """
    Recibe la lista de eventos analizados del pipeline.
    Devuelve una lista reducida donde cada activo principal tiene como máximo
    UNA señal resuelta (la más creíble, o neutral si hay empate).

    El evento devuelto es el original del pipeline, pero con el campo
    `analysis` actualizado si hubo resolución de conflicto, y con el campo
    `_conflict_resolved: True` añadido si se resolvió un conflicto.
    """
    # Agrupar por activo primario
    by_asset: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        analysis = event.get("analysis", {})
        assets = analysis.get("most_affected_assets", [])
        if not assets:
            continue
        primary = assets[0].upper()
        confidence = analysis.get("confidence", 0)
        if confidence < MIN_CONFIDENCE_THRESHOLD:
            logger.debug(f"Descartada señal baja confianza ({confidence}%) para {primary}: {event.get('title','')[:50]}")
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
            continue  # Already handled this asset
        seen_assets.add(primary)

        group = by_asset.get(primary, [])
        if len(group) <= 1:
            resolved_events.append(event)
            continue

        # Multiple events for same primary asset — resolve conflict
        resolved = _resolve_group(primary, group)
        resolved_events.append(resolved)

    return resolved_events


def _resolve_group(asset: str, group: list[dict]) -> dict:
    """Resuelve un grupo de eventos que comparten el mismo activo primario."""
    directions = {}
    for event in group:
        analysis = event.get("analysis", {})
        d = analysis.get("direction", "neutral")
        score = event.get("score", 50)
        confidence = analysis.get("confidence", 50)
        weight = score * confidence
        if d not in directions:
            directions[d] = []
        directions[d].append((weight, event))

    # Si solo hay una dirección real (o todos neutral) → keep best
    non_neutral = {d: evs for d, evs in directions.items() if d != "neutral"}

    if len(non_neutral) == 0:
        # All neutral → return highest score
        best = max(group, key=lambda e: e.get("score", 0) * e.get("analysis", {}).get("confidence", 50))
        return best

    if len(non_neutral) == 1:
        # Unanimous direction
        direction = list(non_neutral.keys())[0]
        best = max(non_neutral[direction], key=lambda t: t[0])[1]
        logger.info(f"✅ Señal unánime para {asset}: {direction} ({len(group)} fuentes)")
        return best

    # CONFLICT: up vs down
    up_weight = sum(w for w, _ in non_neutral.get("up", []))
    down_weight = sum(w for w, _ in non_neutral.get("down", []))

    logger.warning(
        f"⚠️  Conflicto detectado en {asset}: "
        f"up={up_weight:.0f} vs down={down_weight:.0f} "
        f"({len(group)} señales)"
    )

    margin = abs(up_weight - down_weight) / max(up_weight + down_weight, 1)

    if margin < 0.10:
        # Too close to call — pick majority direction with heavily reduced confidence
        winner_dir = "up" if up_weight >= down_weight else "down"
        best = max(non_neutral.get(winner_dir, [(0, group[0])]), key=lambda t: t[0])[1]
        resolved_event = dict(best)
        resolved_analysis = dict(resolved_event.get("analysis", {}))
        resolved_analysis["direction"] = winner_dir
        resolved_analysis["confidence"] = max(25, resolved_analysis.get("confidence", 50) - 25)
        resolved_analysis["reasoning"] = (
            f"Señales contradictorias ({len(group)} fuentes), dirección débil. "
            + resolved_analysis.get("reasoning", "")[:80]
        )
        resolved_event["analysis"] = resolved_analysis
        resolved_event["_conflict_resolved"] = True
        logger.info(f"⚖️  {asset}: empate cercano → {winner_dir} (confianza reducida)")
        return resolved_event
    else:
        # Clear winner
        winner_dir = "up" if up_weight > down_weight else "down"
        best = max(non_neutral[winner_dir], key=lambda t: t[0])[1]
        resolved_event = dict(best)
        resolved_analysis = dict(resolved_event.get("analysis", {}))
        # Slightly reduce confidence because there was a conflict
        resolved_analysis["confidence"] = max(30, resolved_analysis.get("confidence", 50) - 10)
        resolved_event["analysis"] = resolved_analysis
        resolved_event["_conflict_resolved"] = True
        logger.info(f"🏆 {asset}: ganadora → {winner_dir} (margen {margin:.0%})")
        return resolved_event
