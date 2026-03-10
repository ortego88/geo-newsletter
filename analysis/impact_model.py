import re
from detection.asset_detection import detect_assets, ASSET_WEIGHTS
from detection.critical_event_detector import detect_critical_event
from detection.energy_infrastructure_detector import detect_energy_event
from detection.chokepoint_detector import detect_chokepoint

# severidad de eventos
SEVERITY_KEYWORDS = {
    "attack": 1.0,
    "strike": 1.0,
    "missile": 0.9,
    "drone": 0.8,
    "war": 0.9,
    "conflict": 0.7,
    "sanctions": 0.8,
    "tensions": 0.5
}

# localizaciones estratégicas
STRATEGIC_REGIONS = {
    "strait of hormuz": 1.0,
    "suez canal": 0.9,
    "red sea": 0.9,
    "taiwan strait": 1.0,
    "south china sea": 0.8,
    "ukraine": 0.8,
    "iran": 0.8,
    "israel": 0.8,
    "russia": 0.7
}

ENERGY_TERMS = [
    "pipeline",
    "refinery",
    "lng",
    "energy",
    "oil",
    "gas"
]

OSINT_SOURCES = [
"LiveUAMap",
"Crisis24",
"ACLED",
"FIRMS",
"MarineTraffic"
]

def keyword_score(text, dictionary):

    score = 0

    for k, weight in dictionary.items():
        if k in text:
            score = max(score, weight)

    return score


def list_score(text, keywords):

    score = 0

    for k in keywords:
        if k in text:
            score += 0.2

    return min(score, 1)

def impact_score(text, tension_index):

    text = text.lower()

    severity = keyword_score(text, SEVERITY_KEYWORDS)
    geography = keyword_score(text, STRATEGIC_REGIONS)
    energy = list_score(text, ENERGY_TERMS)
    critical_event = detect_critical_event(text)
    assets = detect_assets(text)
    osint_bonus = 0

    for src in OSINT_SOURCES:

        if src.lower() in text:
            osint_bonus += 0.03

    asset_weight = 0

    for a in assets:
        if a in ASSET_WEIGHTS:
            asset_weight = max(asset_weight, ASSET_WEIGHTS[a])

    regional_tension = 0

    for region, value in tension_index.items():
        if region in text:
            regional_tension = max(regional_tension, value)

    base_score = (
        severity * 0.35 +
        geography * 0.2 +
        asset_weight * 0.15 +
        energy * 0.1 +
        regional_tension * 0.2
    )

    score = (base_score + osint_bonus) * 60

    try:
        energy_event = detect_energy_event(text)
    except:
        energy_event = None

    energy_event = detect_energy_event(text)
    chokepoint = detect_chokepoint(text)

    if energy_event:
        score += 15

    if chokepoint:
        score += 15

    if critical_event != "geopolitical development":
        score += 5

    if critical_event in [
        "refinery attack",
        "pipeline sabotage",
        "shipping disruption"
        ]:
            score += 12

    score += asset_weight * 2

    return round(min(score,100),1)