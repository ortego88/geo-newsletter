ENERGY_SIGNALS = [
    "refinery",
    "oil facility",
    "oil depot",
    "oil terminal",
    "pipeline",
    "gas pipeline",
    "lng terminal"
]

ATTACK_SIGNALS = [
    "explosion",
    "blast",
    "fire",
    "attack",
    "strike",
    "drone",
    "missile",
    "sabotage"
]

SHIPPING_SIGNALS = [

"tanker seized",
"vessel seized",
"ship captured",
"strait blocked",
"port closed",
"shipping halted",
"maritime blockade",
"shipping disrupted"
]


def correlate_events(articles):

    energy_mentions = 0
    attack_mentions = 0
    shipping_mentions = 0

    sources = set()
    urls = []

    for a in articles:

        text = (
            (a.get("title") or "") +
            " " +
            (a.get("description") or "")
        ).lower()

        source = a.get("source")

        if isinstance(source, dict):
            source = source.get("name")

        if source:
            sources.add(source)

        if a.get("url") and len(urls) < 5:
            urls.append(a["url"])

        if any(k in text for k in ENERGY_SIGNALS):
            energy_mentions += 1

        if any(k in text for k in ATTACK_SIGNALS):
            attack_mentions += 1

        if any(k in text for k in SHIPPING_SIGNALS):
            shipping_mentions += 1

    events = []

    if energy_mentions >= 2 and attack_mentions >= 2:

        events.append({
            "event": "possible energy infrastructure attack",
            "confidence": "medium",
            "sources": list(sources),
            "urls": urls
        })

    if shipping_mentions >= 3 and attack_mentions >= 1:

        events.append({
            "event": "possible shipping disruption",
            "confidence": "medium",
            "sources": list(sources),
            "urls": urls
        })

    return events