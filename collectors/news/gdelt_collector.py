import requests
from config.config import GDELT_QUERY
import time

time.sleep(5)

import time

LAST_FETCH = 0
CACHE = []

def fetch_gdelt():

    global LAST_FETCH, CACHE

    now = time.time()

    # solo consultar cada 10 minutos
    if now - LAST_FETCH < 600:
        return CACHE

    try:
        articles = real_gdelt_request()
        CACHE = articles
        LAST_FETCH = now
        return articles

    except:
        return CACHE

    url = "https://api.gdeltproject.org/api/v2/doc/doc"

    params = {
        "query": GDELT_QUERY,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 100,
        "timespan": "1h"
    }

    try:

        response = requests.get(url, params=params)

        if response.status_code == 429:

            print("⚠️ Rate limit hit, waiting 10 seconds...")
            time.sleep(10)

            response = requests.get(url, params=params)

        if response.status_code != 200:

            print("⚠️ GDELT request failed:", response.status_code)
            return []

        import json

        try:
            data = response.json()
        except Exception as e:
            print("⚠️ GDELT JSON error:", e)
            return []

        return data.get("articles", [])

    except Exception as e:

        print("⚠️ Error fetching GDELT:", e)
        return []