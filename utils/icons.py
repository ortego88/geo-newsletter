COUNTRY_FLAGS = {

"Iran": "🇮🇷",
"Israel": "🇮🇱",
"Lebanon": "🇱🇧",
"Saudi Arabia": "🇸🇦",
"UAE": "🇦🇪",
"Russia": "🇷🇺",
"Ukraine": "🇺🇦",
"China": "🇨🇳",
"Taiwan": "🇹🇼",
"United States": "🇺🇸",
"USA": "🇺🇸",
"Spain": "🇪🇸",
"France": "🇫🇷",
"Germany": "🇩🇪",
"United Kingdom": "🇬🇧"

}

ASSET_ICONS = {

"oil": "🛢️",
"gas": "🔥",
"energy": "⚡",
"shipping": "🚢",
"commodities": "📦",
"stocks": "📈",
"currency": "💱",
"gold": "🥇",
"general markets": "📊",
"risk sentiment": "🌍"

}

EVENT_ICONS = {

"refinery attack": "🛢️",
"pipeline sabotage": "🛢️",
"energy disruption": "⚡",

"shipping disruption": "🚢",
"tanker seizure": "🚢",

"missile launch": "🚀",
"drone strike": "💣",
"airstrike": "💣",
"military escalation": "⚔️",

"sanctions escalation": "📜",
"trade war": "📜",

"cyber attack": "💻",

"government collapse": "🏛️",
"coup attempt": "⚠️"

}

def location_icon(location):

    for country,flag in COUNTRY_FLAGS.items():

        if country.lower() in location.lower():
            return flag

    return "📍"

def asset_icon(asset):

    asset = asset.lower()

    for k,icon in ASSET_ICONS.items():

        if k in asset:
            return icon

    return "📊"

def impact_icon(score):

    if score >= 75:
        return "🚨"

    if score >= 60:
        return "⚠️"

    if score >= 45:
        return "📊"

    return "ℹ️"

def event_icon(event):

    if not event:
        return "🌍"

    for k,icon in EVENT_ICONS.items():

        if k in event.lower():
            return icon

    return "🌍"