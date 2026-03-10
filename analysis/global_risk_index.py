def compute_global_risk(events):

    score = 0

    for e in events:

        impact = e.get("impact_score",0)

        if impact > 70:
            score += 5

        elif impact > 50:
            score += 3

        elif impact > 30:
            score += 1

    return min(score,100)