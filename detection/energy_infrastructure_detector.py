ENERGY_INFRA = {

"refinery": [
"refinery",
"oil refinery",
"petroleum refinery"
],

"pipeline": [
"pipeline",
"gas pipeline",
"oil pipeline"
],

"oil terminal": [
"oil terminal",
"storage facility",
"fuel depot"
],

"lng terminal": [
"lng terminal",
"liquefied natural gas facility"
],

"oil field": [
"oil field",
"gas field"
]

}


ATTACK_WORDS = [

"explosion",
"blast",
"fire",
"attack",
"strike",
"drone",
"missile",
"sabotage"

]


def detect_energy_event(text):

    text = text.lower()

    infra = None
    attack = None

    for k, terms in ENERGY_INFRA.items():

        if any(t in text for t in terms):
            infra = k
            break

    for w in ATTACK_WORDS:

        if w in text:
            attack = w
            break

    if infra and attack:

        return f"{infra} {attack}"

    if infra:

        return f"{infra} disruption"

    return None