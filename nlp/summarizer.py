import re


def clean_text(text):

    if not text:
        return ""

    # quitar html
    text = re.sub("<.*?>", "", text)

    # quitar saltos
    text = text.replace("\n", " ")

    # espacios extra
    text = re.sub("\s+", " ", text)

    return text.strip()


def summarize(text):

    text = clean_text(text)

    if not text:
        return ""

    sentences = text.split(".")

    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    if not sentences:
        return text[:160]

    summary = sentences[0]

    # añadir segunda frase si la primera es corta
    if len(summary) < 80 and len(sentences) > 1:
        summary = summary + ". " + sentences[1]

    summary = summary.replace("...", "")

    return summary[:200]