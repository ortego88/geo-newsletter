#!/usr/bin/env python3
"""
create_daily_blog_post.py - Genera y publica un artículo de blog diario automáticamente

Usa Claude/OpenAI para generar contenido SEO-optimizado y AI-friendly.
Ejecuta este script diariamente con cron:
  0 9 * * * cd /path/to/geo-newsletter && python3 create_daily_blog_post.py
"""
import hashlib
import os
import sys
from datetime import datetime
from sqlalchemy import text
from web.db_engine import get_engine
import re


# Pool amplio de imágenes gratuitas (Unsplash + Pexels) — crypto/finanzas/trading
_IMAGE_POOL = [
    # Unsplash — crypto & trading
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1611606063065-ee7946f0787a?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1518546305927-5a555bb7020d?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1621761191319-c6fb62004040?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1622630998477-20aa696ecb05?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1642790106117-e829e14a795f?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1605792657660-596af9009e82?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1634704784915-aacf363b021f?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1516245834210-c4c142787335?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1559526324-593bc073d938?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1620321023374-d1a68fbc720d?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1642543492481-44e81e3914a7?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1625806786037-2af608423424?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1643101809204-6fb869816dbe?w=1200&h=630&fit=crop",
    "https://images.unsplash.com/photo-1609554496796-c345a5335ceb?w=1200&h=630&fit=crop",
    # Pexels — crypto & finance (direct image URLs, free to use)
    "https://images.pexels.com/photos/6771900/pexels-photo-6771900.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/8370752/pexels-photo-8370752.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/7567443/pexels-photo-7567443.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6781273/pexels-photo-6781273.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6770609/pexels-photo-6770609.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6765369/pexels-photo-6765369.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/7567565/pexels-photo-7567565.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/8369648/pexels-photo-8369648.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6772076/pexels-photo-6772076.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6781340/pexels-photo-6781340.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/5980856/pexels-photo-5980856.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6802042/pexels-photo-6802042.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/7788009/pexels-photo-7788009.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6771607/pexels-photo-6771607.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
    "https://images.pexels.com/photos/6780789/pexels-photo-6780789.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop",
]


def _get_daily_image(date_str: str = None) -> str:
    """Picks a unique image based on day-of-year — cycles through entire pool before repeating."""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    day_of_year = datetime.strptime(date_str, "%Y-%m-%d").timetuple().tm_yday
    idx = day_of_year % len(_IMAGE_POOL)
    return _IMAGE_POOL[idx]

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
        "title": "Telegram: La mejor herramienta para alertas de trading en tiempo real",
        "keywords": "alertas telegram, señales trading, bot telegram crypto",
        "prompt": "Artículo sobre las ventajas de recibir alertas de trading en Telegram vs email o apps dedicadas. Velocidad, bots, canales, conveniencia, ejemplos de uso."
    },
    {
        "title": "Criptomonedas y geopolítica: ¿Cómo se relacionan?",
        "keywords": "criptomonedas, bitcoin, geopolítica, trading crypto",
        "prompt": "Análisis de la relación entre eventos geopolíticos y el mercado crypto. Regulación, sanciones, adopción institucional, casos de uso reales."
    },
    {
        "title": "Cómo funciona el scoring de eventos en Trianio",
        "keywords": "scoring eventos, sistema de puntuación, alertas automáticas",
        "prompt": "Explica cómo nuestro sistema de IA puntúa cada evento de 0 a 100 según su relevancia de mercado. Habla de factores: fuente, impacto potencial, confianza, y cómo se traduce en alertas."
    },
    {
        "title": "IBEX 35: Guía completa para inversores en el mercado español",
        "keywords": "IBEX 35, bolsa española, invertir en España, mercado continuo",
        "prompt": "Guía educativa sobre el IBEX 35: qué es, qué empresas lo componen, cómo invertir, y cómo los eventos geopolíticos afectan específicamente al mercado español."
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
Escribe un artículo de blog profesional en español para Trianio.

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


def publish_post(title, content, keywords, excerpt=None, featured_image=None):
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

    # Traducir con DeepL si está configurado
    title_en = ""
    excerpt_en = ""
    content_en = ""
    try:
        from src.services.translator import translate_blog_post
        translations = translate_blog_post(title, excerpt, content)
        title_en = translations.get("title_en", "")
        excerpt_en = translations.get("excerpt_en", "")
        content_en = translations.get("content_en", "")
        if title_en:
            print(f"   Traducido a EN: {title_en[:60]}...")
        else:
            print("   DeepL no disponible, artículo solo en ES")
    except Exception as e:
        print(f"   Traducción no disponible: {e}")

    try:
        engine = get_engine("app")
        with engine.connect() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM blog_posts WHERE slug = :slug"
            ), {"slug": slug}).fetchone()

            if exists:
                print(f"El articulo '{title}' ya existe con slug '{slug}'")
                return False

            conn.execute(text("""
                INSERT INTO blog_posts
                (slug, title, excerpt, content, author, published_at, updated_at,
                 is_published, meta_description, keywords, featured_image,
                 title_en, excerpt_en, content_en)
                VALUES (:slug, :title, :excerpt, :content, :author, :published, :updated,
                        TRUE, :meta_desc, :keywords, :featured_image,
                        :title_en, :excerpt_en, :content_en)
            """), {
                "slug": slug,
                "title": title,
                "excerpt": excerpt,
                "content": content,
                "author": "Equipo Trianio",
                "published": now,
                "updated": now,
                "meta_desc": meta_description,
                "keywords": keywords,
                "featured_image": featured_image or "",
                "title_en": title_en,
                "excerpt_en": excerpt_en,
                "content_en": content_en,
            })
            conn.commit()

        print(f"Articulo publicado: {title}")
        print(f"   URL: /blog/{slug}")
        return True

    except Exception as e:
        print(f"❌ Error publicando artículo: {e}")
        return False


def _generate_daily_topic():
    """Genera un tema basado en la fecha actual para garantizar unicidad."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    day_of_week = datetime.utcnow().weekday()

    themes = [
        {
            "angle": "análisis semanal",
            "prompt": "Escribe un análisis semanal de los mercados crypto. Cubre los movimientos más importantes de Bitcoin, Ethereum y altcoins. Incluye datos de precios y volúmenes reales recientes, y qué esperar la próxima semana.",
            "keywords": "crypto semanal, análisis bitcoin, mercado criptomonedas",
        },
        {
            "angle": "educación trading",
            "prompt": "Escribe un artículo educativo sobre una estrategia o concepto de trading crypto (puede ser RSI, MACD, análisis on-chain, DCA, o gestión de riesgo). Incluye ejemplos prácticos.",
            "keywords": "trading crypto, estrategia inversión, educación financiera",
        },
        {
            "angle": "IA y mercados",
            "prompt": "Escribe sobre cómo la inteligencia artificial está cambiando el trading de criptomonedas. Habla de predicciones algorítmicas, análisis de sentimiento, y ventajas de sistemas automatizados.",
            "keywords": "inteligencia artificial, trading automatizado, predicciones crypto",
        },
        {
            "angle": "regulación y noticias",
            "prompt": "Escribe sobre los últimos desarrollos regulatorios en crypto a nivel global (EEUU, Europa, Asia). Cómo afectan a los inversores minoristas y qué oportunidades o riesgos presentan.",
            "keywords": "regulación crypto, legislación blockchain, mercados globales",
        },
        {
            "angle": "altcoins emergentes",
            "prompt": "Análisis de altcoins que están ganando tracción: nuevos proyectos DeFi, Layer 2, o tokens con fundamentos sólidos. Explica por qué podrían ser relevantes para inversores.",
            "keywords": "altcoins, DeFi, inversión crypto, tokens emergentes",
        },
        {
            "angle": "gestión de riesgo",
            "prompt": "Artículo sobre gestión de riesgo en crypto: position sizing, stop-losses, diversificación, y cómo proteger el capital en mercados volátiles.",
            "keywords": "gestión riesgo, stop loss crypto, proteger inversión",
        },
        {
            "angle": "análisis on-chain",
            "prompt": "Explica métricas on-chain importantes para evaluar Bitcoin y Ethereum: MVRV, NUPL, exchange flows, whale activity. Cómo interpretarlas para tomar decisiones de inversión.",
            "keywords": "on-chain, métricas blockchain, análisis fundamental crypto",
        },
    ]

    theme = themes[day_of_week]

    title_prompt = f"""
Genera SOLO un título corto (máximo 10 palabras) para un artículo de blog sobre crypto.
Ángulo: {theme['angle']}
Fecha: {today}
El título debe ser específico, actual y atractivo. NO uses comillas. Responde SOLO con el título.
"""
    title = None
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=50,
                messages=[{"role": "user", "content": title_prompt}]
            )
            title = resp.content[0].text.strip().strip('"').strip("'")
    except Exception:
        pass

    if not title:
        try:
            import openai
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                client = openai.OpenAI(api_key=api_key)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": title_prompt}],
                    max_tokens=50
                )
                title = resp.choices[0].message.content.strip().strip('"').strip("'")
        except Exception:
            pass

    if not title:
        title = f"Mercados crypto: resumen del {today}"

    return {
        "title": title,
        "keywords": theme["keywords"],
        "image": _get_daily_image(today),
        "prompt": theme["prompt"] + f"\n\nFecha de publicación: {today}. Incluye datos actuales y relevantes.",
    }


def main():
    """Genera y publica un artículo diario."""
    print("=" * 60)
    print("📝 GENERANDO ARTÍCULO DIARIO DEL BLOG")
    print("=" * 60)

    topic = _generate_daily_topic()
    print(f"\n📌 Tema seleccionado: {topic['title']}")

    print("\n🤖 Generando contenido con IA...")
    content = generate_content_with_ai(topic)

    print("\n📤 Publicando articulo...")
    success = publish_post(
        title=topic['title'],
        content=content,
        keywords=topic['keywords'],
        featured_image=topic.get('image', _get_daily_image())
    )

    if success:
        print("\n🎉 ¡Artículo publicado exitosamente!")
    else:
        print("\n⚠️  No se pudo publicar el artículo")
        sys.exit(1)


if __name__ == "__main__":
    main()
