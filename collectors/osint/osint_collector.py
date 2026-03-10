import feedparser

REDDIT_FEEDS = [

"https://www.reddit.com/r/worldnews/new/.rss",
"https://www.reddit.com/r/geopolitics/new/.rss",
"https://www.reddit.com/r/combatfootage/new/.rss"

]

OSINT_FEEDS = [

"https://www.osintdefender.com/feed",
"https://www.bnonews.com/index.php/feed",
"https://liveuamap.com/en/rss"

]


def fetch_osint():

    posts = []

    for url in OSINT_FEEDS:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            posts.append({

                "title": entry.title,
                "description": entry.get("summary",""),
                "source": "osint",
                "url": entry.get("link","")

            })

    return posts

def fetch_reddit():

    posts = []

    for url in REDDIT_FEEDS:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            posts.append({
                "title": entry.title,
                "description": entry.get("summary",""),
                "url": entry.get("link",""),
                "source": "reddit"
            })

    return posts