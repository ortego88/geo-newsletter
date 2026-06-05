#!/usr/bin/env python3
"""
add_internal_links.py - Añade sección "Artículos relacionados" al final
de cada artículo existente sin modificar el contenido original.
"""
import os
import sys
from sqlalchemy import text
from web.db_engine import get_engine

RELATED_SECTION_MARKER = "<!-- trianio-related-links -->"


def _get_related(current_slug: str, current_title: str, all_posts: list) -> list:
    """Returns 3 posts most related to the current one (excluding itself)."""
    # Simple keyword matching on title words
    current_words = set(current_title.lower().split())
    stopwords = {"de", "en", "el", "la", "los", "las", "un", "una", "y", "a", "del",
                 "para", "con", "que", "por", "su", "es", "al", "se", "más", "como"}
    current_keywords = current_words - stopwords

    scored = []
    for slug, title in all_posts:
        if slug == current_slug:
            continue
        title_words = set(title.lower().split()) - stopwords
        overlap = len(current_keywords & title_words)
        scored.append((overlap, slug, title))

    scored.sort(reverse=True)
    # Take top 3, fallback to most recent if no overlap
    top = [x for x in scored if x[0] > 0][:3]
    if len(top) < 3:
        fallback = [x for x in scored if x[0] == 0]
        top += fallback[:3 - len(top)]
    return [(s, t) for _, s, t in top[:3]]


def _build_related_html(related: list) -> str:
    links = "\n".join([
        f'  <li><a href="/blog/{slug}">{title}</a></li>'
        for slug, title in related
    ])
    return f"""
{RELATED_SECTION_MARKER}
<div class="related-articles" style="margin-top:2em;padding-top:1.5em;border-top:1px solid #334155;">
  <h3>Artículos relacionados</h3>
  <ul>
{links}
  </ul>
</div>
"""


def main():
    engine = get_engine("app")
    with engine.connect() as conn:
        posts = conn.execute(text(
            "SELECT slug, title, content FROM blog_posts WHERE is_published = TRUE ORDER BY published_at ASC"
        )).fetchall()

    all_posts = [(r[0], r[1]) for r in posts]
    updated = 0
    skipped = 0

    with engine.connect() as conn:
        for slug, title, content in posts:
            # Skip if already has related section
            if RELATED_SECTION_MARKER in (content or ""):
                skipped += 1
                continue

            related = _get_related(slug, title, all_posts)
            if not related:
                skipped += 1
                continue

            new_content = (content or "") + _build_related_html(related)
            conn.execute(text(
                "UPDATE blog_posts SET content = :content WHERE slug = :slug"
            ), {"content": new_content, "slug": slug})
            updated += 1
            print(f"  ✅ {slug[:50]}")
            for rs, rt in related:
                print(f"     → {rt[:50]}")

        conn.commit()

    print(f"\nDone: {updated} updated, {skipped} skipped")


if __name__ == "__main__":
    main()
