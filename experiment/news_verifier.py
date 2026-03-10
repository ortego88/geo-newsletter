import json
from datetime import datetime
from collectors.news.google_news_collector import fetch_google_news

TRUSTED = [
"Reuters",
"BBC",
"Financial Times",
"Bloomberg"
]

FILE = "storage/early_signals.json"


def verify_signals():

    articles = fetch_google_news()

    try:
        with open(FILE) as f:
            signals = json.load(f)
    except:
        return

    for s in signals:

        if s["confirmed"]:
            continue

        for a in articles:

            title = a.get("title","").lower()

            if s["signal"].lower() in title:

                source = a.get("source","")

                if source in TRUSTED:

                    s["confirmed"] = True
                    s["confirmation_time"] = datetime.utcnow().isoformat()
                    s["source"] = source

    with open(FILE,"w") as f:
        json.dump(signals,f)