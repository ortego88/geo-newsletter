import requests
from config.config import NEWS_API_KEY

def fetch_news():

    url = "https://newsapi.org/v2/everything"

    params = {
        "q": "(oil OR gas OR military OR sanctions OR war OR conflict)",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 100,
        "apiKey": NEWS_API_KEY
    }

    r = requests.get(url, params=params)

    data = r.json()

    return data.get("articles", [])