import feedparser

URL = "https://liveuamap.com/en/rss"

def fetch_liveuamap():

    feed = feedparser.parse(URL)

    articles = []

    for entry in feed.entries:

        articles.append({

            "title": entry.title,
            "description": entry.get("summary",""),
            "url": entry.link,
            "publishedAt": entry.get("published",""),
            "source": "liveuamap"

        })

    return articles