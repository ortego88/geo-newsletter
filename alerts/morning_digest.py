import json
from datetime import datetime, timedelta
from outputs.telegram_sender import send_telegram


FILE = "storage/alerts_history.json"


def run_morning_digest():

    try:

        with open(FILE) as f:
            alerts = json.load(f)

    except:
        alerts = []

    since = datetime.utcnow() - timedelta(hours=24)

    recent = []

    for a in alerts:

        ts = a.get("timestamp")

        if not ts:
            continue

        try:

            dt = datetime.fromisoformat(ts)

            if dt > since:
                recent.append(a)

        except:
            continue

    recent = sorted(
        recent,
        key=lambda x: x.get("impact_score",0),
        reverse=True
    )

    assets = {}

    for a in recent:

        for asset in a.get("assets",["other"]):

            assets.setdefault(asset, []).append(a)

    msg = "🌍 Geopolitical Risk Digest (24h)\n\n"

    for asset, events in assets.items():

        msg += f"📊 {asset.upper()}\n"

        for e in events[:3]:

            msg += (
                f"- {e['title']}\n"
                f"Impact: {e['impact_score']}\n"
                f"{e['url']}\n\n"
            )

    send_telegram(msg)