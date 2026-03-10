import snscrape.modules.twitter as sntwitter


KEYWORDS = [
"explosion",
"missile",
"drone strike",
"pipeline",
"refinery",
"ship attack",
"tanker"
]


def fetch_twitter(limit=50):

    tweets = []

    query = " OR ".join(KEYWORDS)

    for tweet in sntwitter.TwitterSearchScraper(query).get_items():

        tweets.append({

            "title": tweet.content[:120],
            "description": tweet.content,
            "source": "twitter"

        })

        if len(tweets) >= limit:
            break

    return tweets