import feedparser

RSS_FEEDS = [

    "https://www.reuters.com/world/rss",
    "https://www.reuters.com/markets/rss",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml"

]

def fetch_rss():

    articles = []

    for url in RSS_FEEDS:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            feed_title = feed.feed.get("title","rss")

            articles.append({
            "title": entry.title,
            "url": entry.link,
            "description": entry.get("summary",""),
            "publishedAt": entry.get("published",""),
            "source": feed_title
            })

    return articles