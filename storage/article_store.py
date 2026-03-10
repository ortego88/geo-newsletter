import json
import hashlib

FILE = "storage/processed_articles.json"


def load_processed():

    try:
        with open(FILE) as f:
            data = json.load(f)

            if not isinstance(data, list):
                return set()

            return set(data)

    except:
        return set()


def save_processed(ids):

    with open(FILE, "w") as f:
        json.dump(list(ids), f)


def article_id(article):

    text = (
        (article.get("title") or "")
        + (article.get("url") or article.get("link") or "")
    )

    return hashlib.md5(text.encode()).hexdigest()