#!/usr/bin/env python3
"""
seed_first_blog_post.py - Crea el primer artículo de blog para evitar error 500
Ejecutar una sola vez para tener contenido inicial
"""
import os
import sys
from datetime import datetime
from sqlalchemy import text
from web.db_engine import get_engine

def _slugify(text):
    """Convierte texto en slug URL-friendly."""
    import re
    text = text.lower()
    text = re.sub(r'[áàäâ]', 'a', text)
    text = re.sub(r'[éèëê]', 'e', text)
    text = re.sub(r'[íìïî]', 'i', text)
    text = re.sub(r'[óòöô]', 'o', text)
    text = re.sub(r'[úùüû]', 'u', text)
    text = re.sub(r'[ñ]', 'n', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


# Artículo inicial de bienvenida
FIRST_POST = {
    "title": "Bienvenido a GEO-NEWSLETTER: Tu fuente de alertas geopolíticas con IA",
    "excerpt": "Descubre cómo la inteligencia artificial puede ayudarte a anticipar movimientos de mercado analizando eventos geopolíticos en tiempo real.",
    "keywords": "alertas geopolíticas, trading IA, inteligencia artificial, análisis mercados",
    "content": """
<h2>¿Qué es GEO-NEWSLETTER?</h2>

<p>GEO-NEWSLETTER es una plataforma innovadora que utiliza inteligencia artificial para analizar eventos geopolíticos globales y generar alertas de trading en tiempo real. Nuestro sistema monitoriza más de 50 fuentes de noticias las 24 horas del día, 7 días a la semana.</p>

<h2>¿Cómo funciona?</h2>

<p>Nuestro modelo de IA analiza cada evento geopolítico (conflictos armados, sanciones económicas, elecciones, crisis energéticas) y determina su posible impacto en diferentes activos financieros:</p>

<ul>
<li><strong>Criptomonedas</strong>: Bitcoin, Ethereum, Ripple, Solana y más</li>
<li><strong>IBEX 35</strong>: Empresas españolas cotizadas</li>
<li><strong>ETFs</strong>: Fondos cotizados internacionales</li>
</ul>

<h2>Ventajas de usar IA para trading</h2>

<p>A diferencia del análisis manual, nuestro sistema:</p>

<ul>
<li>Procesa cientos de noticias simultáneamente</li>
<li>Identifica patrones que los humanos pueden pasar por alto</li>
<li>Genera alertas en segundos, no en horas</li>
<li>Aprende continuamente de los mercados</li>
</ul>

<h2>Accuracy del 44.8%</h2>

<p>Nuestro sistema ha validado más de 500 predicciones con una tasa de acierto del 44.8%, superior a la media del mercado. Cada predicción incluye:</p>

<ul>
<li>Activo afectado</li>
<li>Dirección esperada (subida/bajada)</li>
<li>Nivel de confianza (0-100)</li>
<li>Razonamiento completo en español</li>
</ul>

<h2>Empieza gratis hoy</h2>

<p>Prueba GEO-NEWSLETTER durante 7 días sin compromiso. Sin tarjeta de crédito requerida hasta el día 8. Recibe alertas reales desde el primer día y comprueba por ti mismo el poder de la inteligencia artificial aplicada al trading.</p>

<blockquote>
<p>"La geopolítica mueve los mercados. Ahora puedes estar un paso adelante."</p>
</blockquote>

<h2>Próximos artículos</h2>

<p>En este blog encontrarás:</p>

<ul>
<li>Análisis de eventos geopolíticos recientes</li>
<li>Guías sobre cómo interpretar alertas</li>
<li>Casos de estudio reales</li>
<li>Estrategias de trading con IA</li>
</ul>

<p>¡Mantente atento a nuestras actualizaciones diarias!</p>
"""
}


def main():
    print("=" * 60)
    print("📝 CREANDO PRIMER ARTÍCULO DEL BLOG")
    print("=" * 60)

    try:
        engine = get_engine("app")
        slug = _slugify(FIRST_POST["title"])
        now = datetime.utcnow().isoformat()

        with engine.connect() as conn:
            # Verificar si ya existe
            exists = conn.execute(text(
                "SELECT 1 FROM blog_posts WHERE slug = :slug"
            ), {"slug": slug}).fetchone()

            if exists:
                print(f"⚠️  El artículo ya existe")
                return

            # Insertar
            conn.execute(text("""
                INSERT INTO blog_posts
                (slug, title, excerpt, content, author, published_at, updated_at, is_published, meta_description, keywords)
                VALUES (:slug, :title, :excerpt, :content, :author, :published, :updated, TRUE, :meta_desc, :keywords)
            """), {
                "slug": slug,
                "title": FIRST_POST["title"],
                "excerpt": FIRST_POST["excerpt"],
                "content": FIRST_POST["content"],
                "author": "Equipo GEO-NEWSLETTER",
                "published": now,
                "updated": now,
                "meta_desc": FIRST_POST["excerpt"][:160],
                "keywords": FIRST_POST["keywords"]
            })
            conn.commit()

        print(f"✅ Artículo publicado: {FIRST_POST['title']}")
        print(f"   URL: /blog/{slug}")
        print("\n🎉 Blog listo! Ya no dará error 500")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
