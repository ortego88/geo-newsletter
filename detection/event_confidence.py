def event_confidence(sources):

    # si es lista de fuentes
    if isinstance(sources, list):
        source_count = len(sources)

    # si es una sola fuente
    elif isinstance(sources, str):
        source_count = 1

    # fallback
    else:
        source_count = 0


    if source_count >= 5:
        return "confirmed"

    if source_count >= 3:
        return "probable"

    if source_count >= 1:
        return "possible"

    return "low"