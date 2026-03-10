CHOKEPOINTS = {

"strait of hormuz": "oil chokepoint",
"suez canal": "shipping chokepoint",
"bab el-mandeb": "shipping chokepoint",
"malacca strait": "shipping chokepoint",
"panama canal": "shipping chokepoint"

}


def detect_chokepoint(text):

    text = text.lower()

    for cp, label in CHOKEPOINTS.items():

        if cp in text:

            return cp

    return None