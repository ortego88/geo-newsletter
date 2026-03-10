from collections import defaultdict
import re


def normalize_title(title):

    title = title.lower()
    title = re.sub(r'[^a-z ]', '', title)

    words = title.split()

    return " ".join(words[:6])


def cluster_events(events):

    clusters = defaultdict(list)

    for e in events:

        title = e.get("title","")

        # evitar títulos muy cortos
        if len(title) < 30:
            continue

        title_key = normalize_title(title)

        region = e.get("region","global")

        critical = e.get("critical_event","event")

        key = f"{critical}_{region}_{title_key}"

        clusters[key].append(e)

    merged_events = []

    for key, group in clusters.items():

        base = group[0]

        # combinar fuentes
        source_set = set()

        for g in group:

            src = g.get("sources", [])

            if isinstance(src, list):
                source_set.update(src)

            elif isinstance(src, str):
                source_set.add(src)

        sources = list(source_set)

        base["sources"] = sources

        source_count = len(sources)

        # confidence
        if source_count >= 5:
            base["confidence"] = "confirmed"

        elif source_count >= 3:
            base["confidence"] = "probable"

        else:
            base["confidence"] = "low"

        # aumentar impacto si hay muchas fuentes
        base["impact_score"] = min(
            base["impact_score"] + (source_count * 2),
            100
        )

        merged_events.append(base)

    return merged_events