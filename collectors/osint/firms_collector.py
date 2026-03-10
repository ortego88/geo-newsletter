import requests

URL = "https://firms.modaps.eosdis.nasa.gov/api/country/csv/USA/1"

def fetch_firms():

    articles = []

    try:

        r = requests.get(URL, timeout=10)

        lines = r.text.split("\n")

        for l in lines[1:50]:

            parts = l.split(",")

            if len(parts) < 5:
                continue

            articles.append({

                "title": "Thermal anomaly detected",
                "description": "Possible fire detected by satellite",
                "url": "https://firms.modaps.eosdis.nasa.gov/",
                "publishedAt": parts[5],
                "source": "firms"

            })

    except:
        pass

    return articles