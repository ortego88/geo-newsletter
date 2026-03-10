from rapidfuzz import fuzz


def deduplicate(articles):

    unique = []

    for a in articles:

        title_a = (a.get("title") or "").lower()

        duplicate = False

        for b in unique:

            title_b = (b.get("title") or "").lower()

            similarity = fuzz.ratio(title_a, title_b)

            if similarity > 85:
                duplicate = True
                break

        if not duplicate:
            unique.append(a)

    return unique