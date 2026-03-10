SIGNAL_TERMS = [

"explosion",
"strike",
"missile",
"drone",
"attack",
"pipeline",
"refinery",
"ship",
"tanker",
"port",
"military"

]


def detect_signal(text):

    text = text.lower()

    matches = 0

    for term in SIGNAL_TERMS:

        if term in text:
            matches += 1

    return matches