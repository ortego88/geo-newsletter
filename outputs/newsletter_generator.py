from utils.icons import location_icon, asset_icon, impact_icon, event_icon

TRUSTED_SOURCES = [

"Reuters",
"Bloomberg",
"Financial Times",
"Wall Street Journal",
"BBC",
"Associated Press",
"Al Jazeera",
"Politico",
"CNBC"

]

def classify_market_shock(event):

    critical = event.get("critical_event","")
    assets = event.get("assets",[])
    region = event.get("region","")

    if "refinery attack" in critical or "pipeline sabotage" in critical:
        return "🚨 Energy Supply Shock"

    if "shipping disruption" in critical or "tanker seizure" in critical:
        return "🚨 Shipping Disruption Risk"

    if "missile" in critical or "drone" in critical:
        return "🚨 Military Escalation"

    if "sanctions" in critical:
        return "🚨 Sanctions Shock"

    if "oil" in assets or "energy" in assets:
        return "⚠️ Energy Market Risk"

    return "⚠️ Geopolitical Risk"
    
def market_impact_label(score):

    if score >= 75:
        return "Very High"

    if score >= 60:
        return "High"

    if score >= 45:
        return "Moderate"

    return "Low"


def get_trusted_sources(events):

    sources = []

    for e in events:

        src = e.get("source","")

        if src in TRUSTED_SOURCES and src not in sources:

            sources.append(src)

        if len(sources) == 3:
            break

    return sources

def generate_newsletter(events):

    text = "⚠️ Geopolitical Risk Alert\n\n"

    for e in events:

        location = e.get("location","Unknown")
        assets = ", ".join(e.get("assets",["general markets"]))
        score = e.get("impact_score",0)

        loc_icon = location_icon(location)
        asset_i = asset_icon(assets)
        impact_i = impact_icon(score)
        event_i = event_icon(e.get("critical_event"))

        text += f"""
{event_i} {e.get("title","")}

Summary:
{e.get("summary","")}

{loc_icon} Location:
{location}

{asset_i} Assets impacted:
{assets}

💰 Market impact:
{market_impact_label(score)}

📰 Sources:
"""

        for s in e.get("sources",[])[:3]:
            text += f"- {s}\n"

        text += "\n---------------------\n\n"

    return text