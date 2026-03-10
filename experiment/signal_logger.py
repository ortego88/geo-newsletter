import json
from datetime import datetime, UTC

FILE = "storage/early_signals.json"

def log_signal(signal, location, topic):

    entry = {
        "signal": signal,
        "location": location,
        "topic": topic,
        "timestamp": datetime.now(UTC).isoformat(),
        "confirmed": False,
        "confirmation_time": None,
        "source": None
    }

    try:
        with open(FILE) as f:
            data = json.load(f)
    except:
        data = []

    data.append(entry)

    with open(FILE,"w") as f:
        json.dump(data,f)