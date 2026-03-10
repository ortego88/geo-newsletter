import json
from datetime import datetime

FILE = "storage/early_signals.json"


def analyze():

    with open(FILE) as f:
        data = json.load(f)

    results = []

    for s in data:

        if not s["confirmed"]:
            continue

        t1 = datetime.fromisoformat(s["timestamp"])
        t2 = datetime.fromisoformat(s["confirmation_time"])

        minutes = (t2 - t1).total_seconds() / 60

        results.append(minutes)

    if not results:
        print("No confirmations yet")
        return

    avg = sum(results)/len(results)

    print("Average lead time:", round(avg,1),"minutes")
    print("Max lead time:", round(max(results),1))