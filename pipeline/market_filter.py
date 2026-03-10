MARKET_KEYWORDS = [

# energy
"oil",
"crude",
"gas",
"lng",
"refinery",
"pipeline",
"energy",

# shipping
"shipping",
"tanker",
"strait",
"port",
"canal",
"maritime",

# military
"missile",
"drone",
"airstrike",
"military",
"troops",
"navy",
"attack",
"strike",

# geopolitics
"sanctions",
"trade war",
"embargo",
"conflict",
"war",

# strategic regions
"iran",
"israel",
"ukraine",
"russia",
"taiwan",
"china"
]

MARKET_ASSETS = [
"oil",
"gas",
"energy",
"shipping",
"commodities",
"currency"
]

BLOCKED_DOMAINS = [
"memeorandum.com",
"github.com",
"medium.com",
"substack.com",
"producthunt.com",
"stackoverflow.com",
"footballtoday.com",
"comicbook.com",
"menshealth.com",
"bringatrailer.com",
"mcsweeneys.net",
"decider.com",
"electrek.co"
]

BAD_TERMS = [
"podcast",
"opinion",
"analysis",
"newsletter",
"github"
]

def market_relevant(article):

    url = article.get("url","")
    title = article.get("title","").lower()

    for d in BLOCKED_DOMAINS:
        if d in url:
            return False

    for term in BAD_TERMS:
        if term in title:
            return False

    description = (
        article.get("description")
        or article.get("summary")
        or ""
    )

    if len(title) < 25:
        return False

    text = f"{title} {description}".lower()

    for k in MARKET_KEYWORDS:

        if k in text:
            return True

    for a in MARKET_ASSETS:
        if a in text:
            return True

    return False