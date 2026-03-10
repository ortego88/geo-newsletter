from collections import defaultdict
from analysis.early_signal_keywords import EARLY_SIGNALS


def detect_early_signals(articles):

    signals = defaultdict(lambda:{
        "mentions":0,
        "examples":[],
        "sources":set(),
        "urls":[]
    })

    for a in articles:

        title = (a.get("title") or "").lower()
        desc = (a.get("description") or "").lower()

        text = f"{title} {desc}"

        source = a.get("source","unknown")
        url = a.get("url") or a.get("link")

        for signal,keywords in EARLY_SIGNALS.items():

            for k in keywords:

                if k in text:

                    signals[signal]["mentions"] += 1

                    if len(signals[signal]["examples"]) < 5:
                        signals[signal]["examples"].append(title)

                    signals[signal]["sources"].add(source)

                    if url:
                        signals[signal]["urls"].append(url)

    results = []

    for s,data in signals.items():

        results.append({

            "signal": s,
            "mentions": data["mentions"],
            "examples": data["examples"],
            "sources": list(data["sources"]),
            "urls": data["urls"]

        })

    return results