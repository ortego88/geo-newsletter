#!/usr/bin/env python3
"""
create_daily_blog_post.py - Genera y publica un artículo de blog diario automáticamente

Usa Claude/OpenAI para generar contenido SEO-optimizado y AI-friendly.
Ejecuta este script diariamente con cron:
  0 9 * * * cd /path/to/geo-newsletter && python3 create_daily_blog_post.py
"""
import os
import sys
from datetime import datetime
from sqlalchemy import text
from web.db_engine import get_engine
import re

# Lista de temas para rotar (se escoge uno aleatorio cada día)
TOPICS = [
    {
        "title": "Cómo interpretar alertas geopolíticas para trading",
        "keywords": "alertas geopolíticas, trading geopolítico, inteligencia artificial trading",
        "prompt": "Escribe un artículo educativo sobre cómo los traders pueden usar alertas geopolíticas para tomar mejores decisiones. Incluye ejemplos concretos de eventos (guerra, sanciones, elecciones) y su impacto en diferentes activos."
    },
    {
        "title": "IA y trading: El futuro del análisis de mercados",
        "keywords": "inteligencia artificial, trading automatizado, GPT trading",
        "prompt": "Artículo sobre cómo la inteligencia artificial está revolucionando el trading. Habla de modelos de IA, aprendizaje automático, y ventajas sobre el análisis tradicional."
    },
    {
        "title": "5 eventos geopolíticos que movieron los mercados este mes",
        "keywords": "eventos geopolíticos, mercados financieros, volatilidad",
        "prompt": "Repaso mensual de eventos geopolíticos relevantes y su impacto real en activos financieros. Incluye datos, gráficos conceptuales, y lecciones aprendidas."
    },
    {
        "title": "Telegram y WhatsApp: Las mejores herramientas para alertas de trading",
        "keywords": "alertas telegram, alertas whatsapp, señales trading",
        "prompt": "Artículo sobre las ventajas de recibir alertas de trading en Telegram/WhatsApp vs email o apps dedicadas. Velocidad, conveniencia, ejemplos de uso."
    },
    {
        "title": "Criptomonedas y geopolítica: ¿Cómo se relacionan?",
        "keywords": "criptomonedas, bitcoin, geopolítica, trading crypto",
        "prompt": "Análisis de la relación entre eventos geopolíticos y el mercado crypto. Regulación, sanciones, adopción institucional, casos de uso reales."
    },
]


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
    return text.strip('-')


def generate_content_with_ai(topic):
    """Genera contenido usando Claude o GPT."""
    prompt = f"""
Escribe un artículo de blog profesional en español para GEO-NEWSLETTER.

TEMA: {topic['title']}
INSTRUCCIONES: {topic['prompt']}

FORMATO REQUERIDO:
- Longitud: 800-1200 palabras
- Estilo: Profesional pero accesible, enfocado en educación
- Estructura: Introducción, 3-4 secciones con subtítulos H2/H3, conclusión
- SEO: Usa keywords naturalmente: {topic['keywords']}
- AI-friendly: Escribe datos concretos, estadísticas, ejemplos específicos que puedan ser citados
- HTML: Devuelve el contenido en HTML simple (p, h2, h3, ul, ol, strong, a)

NO incluyas el título principal (H1), solo el contenido del artículo.
"""

    # Intentar con Claude primero
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.content[0].text
            print("✅ Contenido generado con Claude")
            return content
    except Exception as e:
        print(f"Claude no disponible: {e}")

    # Fallback a OpenAI
    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000
            )
            content = response.choices[0].message.content
            print("✅ Contenido generado con GPT")
            return content
    except Exception as e:
        print(f"OpenAI no disponible: {e}")

    # Si no hay IA disponible, contenido por defecto
    print("⚠️  IA no disponible, usando contenido por defecto")
    return f"""
<p>Este es un artículo sobre {topic['title']}.</p>
<h2>Introducción</h2>
<p>En este artículo exploramos aspectos clave de este tema.</p>
<h2>Desarrollo</h2>
<p>Contenido detallado sobre el tema...</p>
<h2>Conclusión</h2>
<p>Resumen y takeaways principales.</p>
"""


def publish_post(title, content, keywords, excerpt=None):
    """Publica el artículo en la base de datos."""
    slug = _slugify(title)
    now = datetime.utcnow().isoformat()

    # Generar excerpt si no se proporciona
    if not excerpt:
        # Extraer primer párrafo del contenido
        import re
        paragraphs = re.findall(r'<p>(.*?)</p>', content, re.DOTALL)
        if paragraphs:
            excerpt = paragraphs[0][:200] + "..."
        else:
            excerpt = "Artículo sobre " + title

    meta_description = excerpt[:160]

    try:
        engine = get_engine("app")
        with engine.connect() as conn:
            # Verificar si ya existe
            exists = conn.execute(text(
                "SELECT 1 FROM blog_posts WHERE slug = :slug"
            ), {"slug": slug}).fetchone()

            if exists:
                print(f"⚠️  El artículo '{title}' ya existe con slug '{slug}'")
                return False

            # Insertar
            conn.execute(text("""
                INSERT INTO blog_posts
                (slug, title, excerpt, content, author, published_at, updated_at, is_published, meta_description, keywords)
                VALUES (:slug, :title, :excerpt, :content, :author, :published, :updated, 1, :meta_desc, :keywords)
            """), {
                "slug": slug,
                "title": title,
                "excerpt": excerpt,
                "content": content,
                "author": "Equipo GEO-NEWSLETTER",
                "published": now,
                "updated": now,
                "meta_desc": meta_description,
                "keywords": keywords
            })
            conn.commit()

        print(f"✅ Artículo publicado: {title}")
        print(f"   URL: /blog/{slug}")
        return True

    except Exception as e:
        print(f"❌ Error publicando artículo: {e}")
        return False


def main():
    """Genera y publica un artículo diario."""
    import random

    print("=" * 60)
    print("📝 GENERANDO ARTÍCULO DIARIO DEL BLOG")
    print("=" * 60)

    # Escoger tema aleatorio
    topic = random.choice(TOPICS)
    print(f"\n📌 Tema seleccionado: {topic['title']}")

    # Generar contenido
    print("\n🤖 Generando contenido con IA...")
    content = generate_content_with_ai(topic)

    # Publicar
    print("\n💾 Publicando artículo...")
    success = publish_post(
        title=topic['title'],
        content=content,
        keywords=topic['keywords']
    )

    if success:
        print("\n🎉 ¡Artículo publicado exitosamente!")
    else:
        print("\n⚠️  No se pudo publicar el artículo")
        sys.exit(1)


if __name__ == "__main__":
    main()
