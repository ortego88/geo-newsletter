import json
from datetime import datetime

FILE = "storage/last_run.json"


def load_last_run():

    try:
        with open(FILE) as f:
            data = json.load(f)
            return data.get("last_run")
    except:
        return None


def save_last_run():

    data = {
        "last_run": datetime.utcnow().isoformat()
    }

    with open(FILE,"w") as f:
        json.dump(data,f)