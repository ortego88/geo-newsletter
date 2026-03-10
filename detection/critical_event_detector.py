CRITICAL_PATTERNS = {

# ENERGY INFRASTRUCTURE
"refinery attack": {
"targets": ["refinery","oil facility","oil plant","energy facility"],
"actions": ["attack","strike","explosion","blast","fire","hit","drone","missile"]
},

"pipeline sabotage": {
"targets": ["pipeline","gas pipeline","oil pipeline"],
"actions": ["explosion","blast","rupture","sabotage","leak","damage"]
},

"energy disruption": {
"targets": ["oil","gas","energy","lng","crude"],
"actions": ["disrupted","halted","cut","shortage","supply risk"]
},

# SHIPPING
"shipping disruption": {
"targets": ["strait","port","canal","shipping lane","maritime"],
"actions": ["blocked","closed","halted","disrupted","restricted"]
},

"tanker seizure": {
"targets": ["tanker","oil tanker","vessel","cargo ship"],
"actions": ["seized","captured","detained","hijacked","intercepted"]
},

# MILITARY
"missile launch": {
"targets": ["missile","ballistic missile"],
"actions": ["launch","fired","launched"]
},

"drone strike": {
"targets": ["drone","uav"],
"actions": ["strike","attack","hit","launched"]
},

"airstrike": {
"targets": ["airstrike","fighter jet","bombing"],
"actions": ["strike","attack","bombed"]
},

"troop mobilization": {
"targets": ["troops","forces","army","military"],
"actions": ["mobilized","deployed","mass"]
},

# SANCTIONS
"sanctions escalation": {
"targets": ["sanctions","embargo","trade restriction"],
"actions": ["imposed","expanded","tightened","approved","announced"]
},

"trade war": {
"targets": ["tariff","trade war","trade dispute"],
"actions": ["imposed","raised","retaliated"]
},

# POLITICAL
"government collapse": {
"targets": ["government","prime minister","president"],
"actions": ["resigned","collapsed","overthrown","removed"]
},

"coup attempt": {
"targets": ["coup","military takeover"],
"actions": ["attempt","attempted","launched"]
},

# CYBER
"cyber attack": {
"targets": ["cyber","hack","cyberattack"],
"actions": ["attack","breach","targeted"]
}

}

def detect_critical_event(text):

    text = text.lower()

    for event, patterns in CRITICAL_PATTERNS.items():

        target_found = any(t in text for t in patterns["targets"])
        action_found = any(a in text for a in patterns["actions"])

        if target_found and action_found:
            return event

    # fallback military
    if any(x in text for x in ["missile","drone","airstrike","attack","strike"]):
        return "military escalation"

    # fallback energy
    if any(x in text for x in ["oil","gas","pipeline","refinery"]):
        return "energy risk"

    # fallback geopolitical
    if any(x in text for x in ["sanctions","conflict","war","military"]):
        return "geopolitical escalation"

    return "geopolitical development"