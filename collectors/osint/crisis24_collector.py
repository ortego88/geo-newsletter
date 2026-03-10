import feedparser

URL = "https://crisis24.garda.com/alerts/rss"

def fetch_crisis24():

    feed = feedparser.parse(URL)

    articles = []

    for entry in feed.entries:

        articles.append({

            "title": entry.title,
            "description": entry.get("summary",""),
            "url": entry.link,
            "publishedAt": entry.get("published",""),
            "source": "crisis24"

        })

    return articles