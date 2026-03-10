import feedparser

URL = "https://www.maritime-executive.com/rss"

def fetch_shipping():

    feed = feedparser.parse(URL)

    articles = []

    for entry in feed.entries:

        articles.append({

            "title": entry.title,
            "description": entry.get("summary",""),
            "url": entry.link,
            "publishedAt": entry.get("published",""),
            "source": "shipping"

        })

    return articles