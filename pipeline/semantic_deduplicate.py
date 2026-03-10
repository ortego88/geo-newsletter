from difflib import SequenceMatcher

def similarity(a, b):

    return SequenceMatcher(None, a, b).ratio()


def semantic_deduplicate(articles, threshold=0.8):

    unique = []

    for a in articles:

        title = (a.get("title") or "").lower()

        duplicate = False

        for u in unique:

            utitle = (u.get("title") or "").lower()

            if similarity(title, utitle) > threshold:
                duplicate = True
                break

        if not duplicate:
            unique.append(a)

    return unique