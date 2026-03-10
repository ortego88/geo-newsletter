RELATION_PATTERNS = {

"energy_supply_crisis": [
"refinery attack",
"pipeline sabotage",
"energy disruption"
],

"maritime_security_risk": [
"shipping disruption",
"tanker seizure"
],

"military_escalation_cluster": [
"missile launch",
"drone strike",
"airstrike"
]

}


def detect_event_clusters(events):

    clusters = []

    for name, patterns in RELATION_PATTERNS.items():

        matches = [
            e for e in events
            if e.get("critical_event") in patterns
        ]

        if len(matches) >= 4:

            clusters.append({
                "cluster": name,
                "events": matches,
                "count": len(matches)
            })

    return clusters