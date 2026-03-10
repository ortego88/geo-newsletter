import spacy
from geopy.geocoders import Nominatim

nlp = spacy.load("en_core_web_sm")

geolocator = Nominatim(user_agent="geo-news")

REGION_COORDS = {
    "Middle East": (29, 45),
    "Eastern Europe": (50, 30),
    "Asia": (35, 100),
    "Europe": (48, 10),
    "Americas": (40, -95),
    "Africa": (5, 20)
}

CHOKEPOINTS = {
    "Strait of Hormuz": ("Middle East",26.566,56.25),
    "Bab el-Mandeb": ("Middle East",12.585,43.333),
    "Suez Canal": ("Middle East",30.044,32.549),
    "Panama Canal": ("Americas",9.101,-79.402),
    "Malacca Strait": ("Asia",2.5,101.0)
}

LOCATION_CACHE = {}

def infer_region(lat, lon):

    if 20 <= lat <= 40 and 30 <= lon <= 60:
        return "Middle East"

    if 40 <= lat <= 60 and 20 <= lon <= 60:
        return "Eastern Europe"

    if 20 <= lat <= 50 and 60 <= lon <= 140:
        return "Asia"

    if 35 <= lat <= 60 and -10 <= lon <= 30:
        return "Europe"

    if -60 <= lon <= -30:
        return "Americas"

    if -20 <= lat <= 30 and -20 <= lon <= 50:
        return "Africa"

    return "Global"


def geocode_place(place):

    if place in LOCATION_CACHE:
        return LOCATION_CACHE[place]

    try:

        location = geolocator.geocode(place, timeout=3)

        if location:

            lat = location.latitude
            lon = location.longitude

            region = infer_region(lat, lon)

            result = {
                "location": place.title(),
                "region": region,
                "lat": lat,
                "lon": lon
            }

            LOCATION_CACHE[place] = result

            return result

    except:
        pass

    return None


def detect_location(text):

    text_lower = text.lower()

    # 1️⃣ chokepoints (prioridad máxima)

    for chokepoint,data in CHOKEPOINTS.items():

        if chokepoint.lower() in text_lower:

            region,lat,lon = data

            return {
                "location": chokepoint,
                "region": region,
                "lat": lat,
                "lon": lon
            }

    # 2️⃣ NER detection

    doc = nlp(text)

    for ent in doc.ents:

        if ent.label_ in ["GPE","LOC"]:

            geo = geocode_place(ent.text)

            if geo:
                return geo

    # 3️⃣ fallback

    return {
        "location": "Global",
        "region": "Global",
        "lat": 20,
        "lon": 0
    }