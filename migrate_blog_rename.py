#!/usr/bin/env python3
"""
migrate_blog_rename.py - Reemplaza "GEO-NEWSLETTER" por "Trianio" en blog_posts existentes.
Ejecutar una sola vez.
"""
import os
import sys
from sqlalchemy import text
from web.db_engine import get_engine


def main():
    print("=" * 60)
    print("Reemplazando GEO-NEWSLETTER → Trianio en blog_posts")
    print("=" * 60)

    engine = get_engine("app")
    columns = ["title", "excerpt", "content", "author", "meta_description",
               "title_en", "excerpt_en", "content_en"]

    with engine.connect() as conn:
        total = 0
        for col in columns:
            result = conn.execute(text(f"""
                UPDATE blog_posts
                SET {col} = REPLACE({col}, 'GEO-NEWSLETTER', 'Trianio')
                WHERE {col} LIKE '%GEO-NEWSLETTER%'
            """))
            if result.rowcount:
                print(f"  {col}: {result.rowcount} filas actualizadas")
                total += result.rowcount

        # Also handle lowercase/variations
        for col in columns:
            result = conn.execute(text(f"""
                UPDATE blog_posts
                SET {col} = REPLACE({col}, 'Geo-Newsletter', 'Trianio')
                WHERE {col} LIKE '%Geo-Newsletter%'
            """))
            if result.rowcount:
                print(f"  {col} (Geo-Newsletter): {result.rowcount} filas actualizadas")
                total += result.rowcount

        conn.commit()

    if total:
        print(f"\nTotal: {total} actualizaciones realizadas")
    else:
        print("\nNo se encontraron referencias a GEO-NEWSLETTER")


if __name__ == "__main__":
    main()
