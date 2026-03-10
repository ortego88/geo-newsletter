import json
from datetime import date

FILE = "storage/alerts_sent.json"

import json
from datetime import date

FILE = "storage/alerts_sent.json"

def load_memory():

    try:
        with open(FILE) as f:
            data = json.load(f)

            # si por error es una lista, lo convertimos
            if isinstance(data, list):
                return {}

            return data

    except:
        return {}

def already_sent(alert_id):

    data = load_memory()
    today = str(date.today())

    return alert_id in data.get(today,[])

def store_alert(alert_id):

    data = load_memory()
    today = str(date.today())

    if today not in data:
        data[today] = []

    if alert_id not in data[today]:
        data[today].append(alert_id)

    with open(FILE,"w") as f:
        json.dump(data,f,indent=2)