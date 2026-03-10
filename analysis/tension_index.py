from collections import Counter


def compute_tension(articles):

    regions = []

    for a in articles:

        text = (a.get("title","") + " " + (a.get("description") or "")).lower()

        if "iran" in text:
            regions.append("iran")

        if "ukraine" in text:
            regions.append("ukraine")

        if "china" in text or "taiwan" in text:
            regions.append("taiwan")

        if "israel" in text or "gaza" in text:
            regions.append("middle east")

    counts = Counter(regions)

    tension = {}

    for r,c in counts.items():
        tension[r] = min(c/10,1)

    return tension