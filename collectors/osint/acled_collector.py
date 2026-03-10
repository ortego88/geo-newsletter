import requests

URL = "https://api.acleddata.com/acled/read"

def fetch_acled():

    articles = []

    try:

        r = requests.get(URL, timeout=10)

        data = r.json()

        for e in data.get("data",[])[:50]:

            articles.append({

                "title": e.get("event_type","conflict event"),
                "description": e.get("notes",""),
                "url": "https://acleddata.com",
                "publishedAt": e.get("event_date",""),
                "source": "acled"

            })

    except:
        pass

    return articles