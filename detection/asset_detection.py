ASSET_KEYWORDS = {

"oil": ["oil","crude","brent"],
"gas": ["gas","lng"],
"energy": ["energy","pipeline","refinery"],
"shipping": ["shipping","tanker","strait"],
"commodities": ["commodities","metals"],
"stocks": ["stocks","equities"],
"currencies": ["currency","fx","dollar"]

}

ASSET_WEIGHTS = {

"oil": 1.0,
"gas": 0.9,
"energy": 0.8,
"shipping": 0.8,
"commodities": 0.7,
"stocks": 0.6,
"currencies": 0.6

}

def detect_assets(text):

    text = text.lower()

    assets = []

    if any(x in text for x in ["oil","refinery","pipeline","crude"]):
        assets.append("oil")

    if any(x in text for x in ["gas","lng"]):
        assets.append("gas")

    if any(x in text for x in ["shipping","tanker","strait"]):
        assets.append("shipping")

    if any(x in text for x in ["sanction","trade restriction"]):
        assets.append("commodities")

    if any(x in text for x in ["military","missile","drone","troops"]):
        assets.append("risk sentiment")

    if len(assets) == 0:
        assets.append("general markets")

    return assets