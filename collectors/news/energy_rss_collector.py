import feedparser

FEEDS = [

    "https://oilprice.com/rss/main",
    "https://www.energyvoice.com/feed/",
    "https://www.worldoil.com/rss",
]

def fetch_energy_news():

    articles = []

    for url in FEEDS:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            articles.append({

                "title": entry.title,
                "description": entry.get("summary",""),
                "url": entry.link,
                "publishedAt": entry.get("published",""),
                "source": "energy_rss"

            })

    return articles