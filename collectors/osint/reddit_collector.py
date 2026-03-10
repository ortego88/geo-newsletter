import praw


def fetch_reddit():

    reddit = praw.Reddit(
        client_id="",
        client_secret="",
        user_agent="geo-news"
    )

    posts = []

    for post in reddit.subreddit("worldnews+geopolitics").new(limit=50):

        posts.append({

            "title": post.title,
            "description": post.selftext,
            "source": "reddit"

        })

    return posts