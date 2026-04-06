"""
Filtro de contenido para excluir ruido de entretenimiento/famosos.
Evita que noticias de celebridades sean clasificadas como eventos geopolíticos.
"""

ENTERTAINMENT_KEYWORDS = [
    "celebrity", "actor", "actress", "singer", "rapper", "musician",
    "movie", "film", "tv show", "television", "netflix original",
    "oscar", "grammy", "emmy", "golden globe",
    "marriage", "divorce", "wedding", "engaged", "engagement", "breakup",
    "pregnant", "pregnancy", "expecting", "baby shower",
    "delist", "celebrity home", "celebrity mansion",
    "viral", "tiktok", "instagram followers", "youtube views", "influencer",
    "kardashian", "jenner", "beyonce", "rihanna", "drake", "bieber",
    "chris pratt", "katherine schwarzenegger", "katy perry", "taylor swift",
    "britney", "madonna", "selena gomez", "ariana grande",
]

FINANCIAL_OVERRIDE_KEYWORDS = [
    "ipo", "merger", "acquisition", "earnings", "revenue", "market cap",
    "stock", "shares", "nasdaq", "nyse", "sec filing",
]


def is_entertainment_noise(title: str, description: str = "") -> bool:
    """
    Retorna True si el título/descripción corresponde a ruido de entretenimiento.
    Las keywords financieras tienen prioridad y pueden anular el filtro.
    """
    text = (title + " " + description).lower()
    if any(kw in text for kw in FINANCIAL_OVERRIDE_KEYWORDS):
        return False
    if any(kw in text for kw in ENTERTAINMENT_KEYWORDS):
        return True
    return False
