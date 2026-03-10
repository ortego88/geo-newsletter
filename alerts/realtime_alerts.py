def select_alerts(events):

    alerts = []

    for e in events:

        if e["impact_score"] >= 70 and e["confidence"] != "low":
            alerts.append(e)

    alerts = sorted(
        alerts,
        key=lambda x: x["impact_score"],
        reverse=True
    )

    return alerts[:5]