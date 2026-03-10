CATEGORIES = {

"military escalation": [
"missile","drone","troops","airstrike","attack","strike","military","bomb"
],

"energy disruption": [
"oil","pipeline","refinery","lng","energy","gas"
],

"shipping disruption": [
"tanker","shipping","strait","port","blockade","vessel"
],

"sanctions": [
"sanction","embargo","trade restriction","blacklist"
],

"political tension": [
"election","diplomatic","government","minister","parliament"
]

}


def classify_event(text):

    text = text.lower()

    scores = {}

    for category, keywords in CATEGORIES.items():

        score = 0

        for k in keywords:

            if k in text:
                score += 1

        scores[category] = score

    # elegir la categoría con mayor score
    best_category = max(scores, key=scores.get)

    if scores[best_category] == 0:
        return "general geopolitical"

    return best_category