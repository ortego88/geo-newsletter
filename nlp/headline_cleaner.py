def clean_headline(title):

    if not title:
        return "Geopolitical event"

    # quitar separadores comunes
    for sep in ["|", " - ", " — ", ":"]:
        if sep in title:
            title = title.split(sep)[-1]

    title = title.strip()

    # limitar longitud
    words = title.split()

    if len(words) > 12:
        title = " ".join(words[:12]) + "..."

    return title