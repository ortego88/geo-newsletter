import feedparser

SEARCHES = [
    "iran oil attack",
    "refinery explosion",
    "pipeline sabotage",
    "strait of hormuz shipping",
    "energy infrastructure attack",
    "military escalation middle east"
]

def fetch_google_news():

    articles = []

    for query in SEARCHES:

        url = f"https://news.google.com/rss/search?q={query.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en"

        feed = feedparser.parse(url)

        for entry in feed.entries:

            articles.append({

                "title": entry.title,
                "description": entry.get("summary",""),
                "url": entry.link,
                "publishedAt": entry.get("published",""),
                "source": "google_news"

            })

    return articles