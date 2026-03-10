import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from analysis.early_signal_detector import detect_early_signals

articles = [

{
"title":"large fire reported at iran refinery near abadan",
"description":"industrial fire reported at oil refinery facility",
"source":"local media"
},

{
"title":"explosion reported near oil depot in iran",
"description":"possible refinery explosion",
"source":"regional news"
},

{
"title":"smoke visible near refinery complex",
"description":"fire trucks responding to refinery fire",
"source":"osint"
}

]

signals = detect_early_signals(articles)

print("\nDETECTED SIGNALS\n")

for s in signals:

    print(
        s["signal"],
        "| mentions:",
        s["mentions"],
        "| sources:",
        len(s["sources"])
    )