"""
src/services/twitter_bot.py — Integración con Twitter/X para Trianio.

Publica alertas automáticas (2/día: mañana + tarde) y resultados cuando
se validan las predicciones. También publica hilos explicativos.
"""

import logging
import os
import time
from datetime import datetime, timezone

import tweepy

logger = logging.getLogger("twitter_bot")

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")


def _get_client() -> tweepy.Client | None:
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        logger.warning("Twitter credentials not configured")
        return None
    return tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True,
    )


def post_tweet(text: str, reply_to: str | None = None) -> str | None:
    """Posts a tweet. Returns tweet ID or None on failure."""
    client = _get_client()
    if not client:
        return None
    try:
        params = {"text": text}
        if reply_to:
            params["in_reply_to_tweet_id"] = reply_to
        response = client.create_tweet(**params)
        tweet_id = response.data["id"]
        logger.info(f"Tweet posted: {tweet_id} ({text[:50]}...)")
        return tweet_id
    except Exception as e:
        logger.error(f"Error posting tweet: {e}")
        return None


def post_thread(tweets: list[str]) -> list[str]:
    """Posts a thread (list of tweets). Returns list of tweet IDs."""
    ids = []
    reply_to = None
    for tweet_text in tweets:
        tweet_id = post_tweet(tweet_text, reply_to=reply_to)
        if tweet_id:
            ids.append(tweet_id)
            reply_to = tweet_id
        else:
            break
        time.sleep(1)
    return ids


def post_alert_tweet(prediction: dict) -> str | None:
    """Posts a prediction alert as a tweet."""
    asset = prediction.get("asset", "?")
    direction = prediction.get("direction", "?")
    confidence = prediction.get("confidence", 0)
    reasoning = prediction.get("reasoning", "")

    arrow = "📈" if direction == "up" else "📉"
    dir_text = "ALCISTA" if direction == "up" else "BAJISTA"

    tweet = (
        f"{arrow} #{asset} — Señal {dir_text}\n\n"
        f"Confianza: {confidence}%\n"
        f"{reasoning}\n\n"
        f"⏱️ Ventana: 24h\n"
        f"🎯 Verificaremos el resultado y lo publicaremos aquí\n\n"
        f"#crypto #trading #{asset} #Trianio"
    )

    if len(tweet) > 280:
        tweet = (
            f"{arrow} #{asset} — Señal {dir_text} (conf: {confidence}%)\n\n"
            f"{reasoning[:120]}\n\n"
            f"⏱️ 24h | Resultado próximamente\n"
            f"#crypto #{asset} #Trianio"
        )

    return post_tweet(tweet)


def post_result_tweet(prediction: dict, reply_to_tweet_id: str | None = None) -> str | None:
    """Posts the result of a validated prediction."""
    asset = prediction.get("asset", "?")
    outcome = prediction.get("outcome", "?")
    direction = prediction.get("direction", "?")
    price_pred = prediction.get("price_at_prediction", 0)
    price_val = prediction.get("price_at_validation", 0)

    if price_pred and price_val and price_pred > 0:
        move_pct = (price_val - price_pred) / price_pred * 100
        if direction in ("down", "bearish"):
            move_pct = -move_pct
    else:
        move_pct = 0

    if outcome == "correct":
        emoji = "✅"
        result_text = f"ACERTADA (+{abs(move_pct):.1f}% en dirección predicha)"
    else:
        emoji = "❌"
        result_text = f"FALLADA ({move_pct:+.1f}%)"

    tweet = (
        f"{emoji} Resultado #{asset}:\n\n"
        f"{result_text}\n\n"
        f"💰 Precio entrada: ${price_pred:.4g}\n"
        f"💰 Precio cierre: ${price_val:.4g}\n\n"
        f"Transparencia total. Publicamos todos los resultados.\n"
        f"#crypto #{asset} #Trianio"
    )

    if len(tweet) > 280:
        tweet = (
            f"{emoji} #{asset}: {result_text}\n"
            f"${price_pred:.4g} → ${price_val:.4g}\n\n"
            f"#crypto #{asset} #Trianio"
        )

    return post_tweet(tweet, reply_to=reply_to_tweet_id)


def get_daily_best_predictions(n: int = 2) -> list[dict]:
    """Gets the N best predictions from the current cycle for tweeting."""
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text

        with get_engine("predictions").connect() as conn:
            rows = conn.execute(text("""
                SELECT id, asset, direction, confidence, reasoning,
                       price_at_prediction, predicted_at, source
                FROM predictions
                WHERE outcome = 'pending'
                  AND alerted = 1
                  AND predicted_at >= (NOW() - INTERVAL '4 hours')
                ORDER BY confidence DESC
                LIMIT :n
            """), {"n": n}).mappings().fetchall()

        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error getting predictions for twitter: {e}")
        return []


def get_recently_validated(hours: int = 8) -> list[dict]:
    """Gets recently validated predictions that were tweeted."""
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text

        with get_engine("predictions").connect() as conn:
            rows = conn.execute(text("""
                SELECT id, asset, direction, confidence, outcome,
                       price_at_prediction, price_at_validation,
                       reasoning, twitter_tweet_id
                FROM predictions
                WHERE outcome IN ('correct', 'incorrect')
                  AND validated_at >= (NOW() - INTERVAL ':hours hours')
                  AND twitter_tweet_id IS NOT NULL
                  AND twitter_result_posted = FALSE
                ORDER BY validated_at DESC
            """).bindparams(hours=hours)).mappings().fetchall()

        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error getting validated predictions for twitter: {e}")
        return []


def run_twitter_alert_cycle():
    """
    Called twice daily (morning + afternoon). Posts the best current prediction.
    Stores the tweet ID in the prediction for later result posting.
    """
    if not TWITTER_API_KEY:
        return

    predictions = get_daily_best_predictions(n=1)
    if not predictions:
        logger.info("Twitter: no pending predictions to tweet")
        return

    pred = predictions[0]
    tweet_id = post_alert_tweet(pred)

    if tweet_id:
        try:
            from web.db_engine import get_engine
            from sqlalchemy import text
            with get_engine("predictions").connect() as conn:
                conn.execute(text(
                    "UPDATE predictions SET twitter_tweet_id = :tid WHERE id = :pid"
                ), {"tid": tweet_id, "pid": pred["id"]})
                conn.commit()
            logger.info(f"Twitter alert posted for {pred['asset']} (tweet {tweet_id})")
        except Exception as e:
            logger.warning(f"Error saving tweet ID: {e}")


def run_twitter_result_cycle():
    """
    Called periodically. Checks for validated predictions that were tweeted
    and posts the result as a reply.
    """
    if not TWITTER_API_KEY:
        return

    validated = get_recently_validated(hours=12)
    for pred in validated:
        tweet_id = pred.get("twitter_tweet_id")
        if not tweet_id:
            continue

        result_id = post_result_tweet(pred, reply_to_tweet_id=tweet_id)
        if result_id:
            try:
                from web.db_engine import get_engine
                from sqlalchemy import text
                with get_engine("predictions").connect() as conn:
                    conn.execute(text(
                        "UPDATE predictions SET twitter_result_posted = TRUE WHERE id = :pid"
                    ), {"pid": pred["id"]})
                    conn.commit()
            except Exception as e:
                logger.warning(f"Error marking result as posted: {e}")

        time.sleep(2)


def post_intro_thread():
    """Posts the introductory thread explaining Trianio."""
    tweets = [
        (
            "🚀 Presentamos Trianio — Inteligencia crypto antes de que el mercado se mueva\n\n"
            "Usamos IA (Claude) para analizar señales técnicas en tiempo real y predecir "
            "movimientos de +50 criptomonedas.\n\n"
            "Transparencia total: publicamos TODAS nuestras predicciones y resultados. 🧵👇"
        ),
        (
            "📊 ¿Cómo funciona?\n\n"
            "1️⃣ Cada 8h, nuestra IA analiza RSI, volumen, funding rate y tendencias multi-timeframe\n"
            "2️⃣ Genera predicciones con un nivel de confianza (60-82%)\n"
            "3️⃣ Se validan automáticamente en 24h contra el precio real\n\n"
            "Sin trucos. Sin cherry-picking."
        ),
        (
            "🎯 Resultados actuales:\n\n"
            "• Accuracy global: ~63%\n"
            "• Mejores assets: ADA (83%), ETH (80%), ENJ (79%), NEAR (76%), BTC (75%)\n"
            "• Umbrales dinámicos: BTC/ETH necesitan moverse ≥1%, mid-caps ≥1.5%, small ≥2%\n\n"
            "Cada semana publicamos un resumen verificable."
        ),
        (
            "⚡ ¿Qué incluye el servicio?\n\n"
            "• Alertas en Telegram personalizadas (elige tus activos)\n"
            "• Predicciones priorizadas por accuracy histórica\n"
            "• Historial completo verificable en trianio.com/historial\n"
            "• 7 días de prueba gratis\n\n"
            "🔗 https://trianio.com"
        ),
        (
            "📢 En esta cuenta publicaremos:\n\n"
            "• 2 alertas diarias (mañana y tarde) con nuestras mejores señales\n"
            "• El resultado verificado de cada predicción\n"
            "• Resumen semanal de accuracy\n\n"
            "Síguenos para ver en tiempo real si nuestra IA acierta o falla.\n\n"
            "#crypto #trading #IA #Bitcoin #Ethereum"
        ),
    ]

    ids = post_thread(tweets)
    logger.info(f"Intro thread posted: {len(ids)} tweets")
    return ids


CRYPTO_ACCOUNTS_TO_FOLLOW = [
    "CryptoBanterGroup",
    "AltcoinDailyio",
    "CoinDesk",
    "Cointelegraph",
    "WuBlockchain",
    "lookonchain",
    "whale_alert",
    "EmberCN",
    "ali_charts",
    "CryptoQuant_com",
    "glaborofficial",
    "santaborofficial",
    "DaanCrypto",
    "CryptoBirb",
    "CryptoCapo_",
    "inversorfx",
    "CryptoNoticias",
    "CoinTelegraph_ES",
    "Bit2Me_ES",
]


def follow_crypto_accounts():
    """Follows relevant crypto accounts."""
    client = _get_client()
    if not client:
        return

    me = client.get_me()
    if not me or not me.data:
        logger.error("Could not get own user ID")
        return

    my_id = me.data.id
    followed = 0

    for username in CRYPTO_ACCOUNTS_TO_FOLLOW:
        try:
            user = client.get_user(username=username)
            if user and user.data:
                client.follow_user(user.data.id)
                followed += 1
                logger.info(f"Followed @{username}")
                time.sleep(2)
        except Exception as e:
            logger.debug(f"Could not follow @{username}: {e}")

    logger.info(f"Twitter: followed {followed}/{len(CRYPTO_ACCOUNTS_TO_FOLLOW)} accounts")


# Influencer outreach DM template
INFLUENCER_DM_TEMPLATE = """Hola {name} 👋

Somos Trianio, un servicio de alertas crypto con IA que predice movimientos de +50 activos con un 63% de accuracy verificable.

Lo que nos diferencia:
• Publicamos TODOS los resultados (aciertos y fallos) en tiempo real
• BTC 75%, ETH 80%, ADA 83% de acierto en las últimas 2 semanas
• Historial público: trianio.com/historial

Nos encantaría que lo probaras gratis (7 días) y si te convence, explorar una colaboración.

¿Te interesa? Te paso acceso directo.

Un saludo,
Equipo Trianio
trianio.com"""

INFLUENCER_DM_TEMPLATE_EN = """Hi {name} 👋

We're Trianio, an AI-powered crypto alert service that predicts price movements for 50+ assets with 63% verified accuracy.

What makes us different:
• We publish ALL results (wins AND losses) in real-time
• BTC 75%, ETH 80%, ADA 83% accuracy over the past 2 weeks
• Public track record: trianio.com/historial

We'd love for you to try it free (7 days) and if you like it, explore a collaboration.

Interested? I'll send you direct access.

Best,
Trianio Team
trianio.com"""
