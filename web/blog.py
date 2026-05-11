"""
web/blog.py — Blog/Noticias con optimización SEO y AI-friendly.

Características:
- URLs amigables (/blog/slug-de-la-noticia)
- Meta tags Open Graph y Twitter Card
- Schema.org markup para Google
- Contenido optimizado para ser citado por IAs (Claude, ChatGPT, Perplexity)
- Sitemap automático
"""
from flask import Blueprint, render_template, abort, url_for
from sqlalchemy import text
from web.db_engine import get_engine
from datetime import datetime
import pytz
import re

blog_bp = Blueprint("blog", __name__)

_MADRID_TZ = pytz.timezone("Europe/Madrid")


def _slugify(text):
    """Convierte texto en slug URL-friendly."""
    text = text.lower()
    text = re.sub(r'[áàäâ]', 'a', text)
    text = re.sub(r'[éèëê]', 'e', text)
    text = re.sub(r'[íìïî]', 'i', text)
    text = re.sub(r'[óòöô]', 'o', text)
    text = re.sub(r'[úùüû]', 'u', text)
    text = re.sub(r'[ñ]', 'n', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text


def _init_blog_table():
    """Crea la tabla blog_posts si no existe."""
    try:
        from sqlalchemy import MetaData, Table, Column, Integer, Text, Boolean

        engine = get_engine("app")
        meta = MetaData()
        Table("blog_posts", meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("slug", Text, unique=True, nullable=False),
            Column("title", Text, nullable=False),
            Column("excerpt", Text),
            Column("content", Text, nullable=False),
            Column("author", Text, default="Equipo GEO-NEWSLETTER"),
            Column("published_at", Text),
            Column("updated_at", Text),
            Column("is_published", Boolean, default=True),
            Column("meta_description", Text),
            Column("keywords", Text),
            Column("featured_image", Text),
            Column("title_en", Text),
            Column("excerpt_en", Text),
            Column("content_en", Text),
        )
        meta.create_all(engine, checkfirst=True)

        # Migración: añadir columnas de traducción si no existen
        with engine.connect() as conn:
            for col in ("title_en", "excerpt_en", "content_en"):
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='blog_posts' AND LOWER(column_name)=:col"
                ), {"col": col}).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE blog_posts ADD COLUMN {col} TEXT"))
            conn.commit()

    except Exception as e:
        import logging
        logging.debug(f"No se pudo inicializar tabla blog_posts: {e}")


# Solo intentar crear tabla si DATABASE_URL está configurado
import os
if os.getenv("DATABASE_URL"):
    _init_blog_table()


def _get_user_lang():
    """Obtiene el idioma del usuario desde cookie/localStorage o sesión."""
    from flask import request as req
    from flask_login import current_user
    if hasattr(current_user, 'language') and current_user.is_authenticated:
        return current_user.language or "es"
    return req.args.get("lang", req.cookies.get("geo_lang", "es"))


@blog_bp.route("/blog")
def index():
    """Listado de artículos del blog."""
    lang = _get_user_lang()
    is_en = lang == "en"

    try:
        with get_engine("app").connect() as conn:
            rows = conn.execute(text("""
                SELECT id, slug, title, excerpt, author, published_at, featured_image,
                       title_en, excerpt_en
                FROM blog_posts
                WHERE is_published = TRUE
                ORDER BY published_at DESC
                LIMIT 20
            """)).mappings().fetchall()
    except Exception as e:
        import logging
        logging.error(f"Error loading blog posts: {e}", exc_info=True)
        rows = []

    posts = []
    for row in rows:
        d = dict(row)
        if is_en and d.get("title_en"):
            d["title"] = d["title_en"]
        if is_en and d.get("excerpt_en"):
            d["excerpt"] = d["excerpt_en"]
        if d.get("published_at"):
            try:
                dt = datetime.fromisoformat(d["published_at"])
                d["published_at_formatted"] = dt.astimezone(_MADRID_TZ).strftime("%d %b %Y")
            except Exception:
                d["published_at_formatted"] = d["published_at"][:10] if d["published_at"] else ""
        else:
            d["published_at_formatted"] = ""
        posts.append(d)

    return render_template("blog/index.html", posts=posts, lang=lang)


@blog_bp.route("/blog/<slug>")
def post(slug):
    """Detalle de un artículo del blog."""
    lang = _get_user_lang()
    is_en = lang == "en"

    try:
        with get_engine("app").connect() as conn:
            row = conn.execute(text("""
                SELECT id, slug, title, excerpt, content, author, published_at, updated_at,
                       meta_description, keywords, featured_image,
                       title_en, excerpt_en, content_en
                FROM blog_posts
                WHERE slug = :slug AND is_published = TRUE
            """), {"slug": slug}).mappings().fetchone()
    except Exception:
        row = None

    if not row:
        abort(404)

    post = dict(row)
    if is_en and post.get("title_en"):
        post["title"] = post["title_en"]
    if is_en and post.get("excerpt_en"):
        post["excerpt"] = post["excerpt_en"]
    if is_en and post.get("content_en"):
        post["content"] = post["content_en"]

    # Formatear fechas
    if post.get("published_at"):
        try:
            dt = datetime.fromisoformat(post["published_at"])
            post["published_at_formatted"] = dt.astimezone(_MADRID_TZ).strftime("%d de %B de %Y")
            post["published_at_iso"] = dt.isoformat()
        except:
            post["published_at_formatted"] = post["published_at"][:10]
            post["published_at_iso"] = post["published_at"]

    # URL canónica
    post["canonical_url"] = url_for("blog.post", slug=slug, _external=True)

    return render_template("blog/post.html", post=post)


@blog_bp.route("/blog/sitemap.xml")
def sitemap():
    """Sitemap XML para SEO."""
    try:
        with get_engine("app").connect() as conn:
            rows = conn.execute(text("""
                SELECT slug, updated_at, published_at
                FROM blog_posts
                WHERE is_published = TRUE
                ORDER BY published_at DESC
            """)).fetchall()
    except Exception:
        rows = []

    urls = []
    for row in rows:
        lastmod = row[1] or row[2]
        if lastmod:
            try:
                dt = datetime.fromisoformat(lastmod)
                lastmod = dt.strftime("%Y-%m-%d")
            except:
                lastmod = lastmod[:10]

        urls.append({
            "loc": url_for("blog.post", slug=row[0], _external=True),
            "lastmod": lastmod,
            "changefreq": "weekly",
            "priority": "0.8"
        })

    from flask import Response
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += '  <url>\n'
        xml += f'    <loc>{url["loc"]}</loc>\n'
        xml += f'    <lastmod>{url["lastmod"]}</lastmod>\n'
        xml += f'    <changefreq>{url["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{url["priority"]}</priority>\n'
        xml += '  </url>\n'
    xml += '</urlset>'

    return Response(xml, mimetype='application/xml')
