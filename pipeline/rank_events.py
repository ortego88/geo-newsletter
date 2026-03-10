def rank_events(events):

    ranked = []

    for e in events:

        impact = e.get("impact_score",0)

        confidence = e.get("confidence","possible")

        confidence_weight = {
            "weak signal":0.6,
            "possible":0.8,
            "probable":1.0,
            "very likely":1.2,
            "confirmed":1.4
        }

        weight = confidence_weight.get(confidence,1)

        score = impact * weight

        ranked.append((score,e))

    ranked.sort(key=lambda x: x[0], reverse=True)

    return sorted(
        events,
        key=lambda e: (
            e.get("impact_score",0),
            e.get("sources",0)
        ),
        reverse=True
    )