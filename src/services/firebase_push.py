"""
firebase_push.py — Push notifications via Firebase Cloud Messaging (FCM).

Uses topic-based subscriptions by plan:
  - alerts-basic: users on basic plan
  - alerts-premium: users on premium plan
  - alerts-pro: users on pro plan

The app subscribes the user to the correct topic on login/plan change.
This module sends notifications to topics when alerts fire.

Environment variables:
  FIREBASE_CREDENTIALS_JSON — JSON string of the Firebase service account key
"""

import json
import logging
import os

logger = logging.getLogger("firebase_push")

_app_initialized = False


def _init_firebase():
    """Initialize Firebase Admin SDK (once)."""
    global _app_initialized
    if _app_initialized:
        return True

    creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
    if not creds_json:
        logger.debug("FIREBASE_CREDENTIALS_JSON not set — push disabled")
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials

        creds_dict = json.loads(creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        _app_initialized = True
        logger.info("Firebase Admin SDK initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        return False


def _topic_for_plan(plan: str) -> str:
    """Returns the FCM topic name for a subscription plan."""
    if plan in ("basic", "premium", "pro"):
        return f"alerts-{plan}"
    return "alerts-basic"


def _all_plan_topics() -> list[str]:
    """Returns all plan topic names (most permissive first)."""
    return ["alerts-pro", "alerts-premium", "alerts-basic"]


def send_alert_to_topics(event: dict, analysis: dict, plans: list[str] | None = None) -> int:
    """
    Sends a push notification for an alert to the specified plan topics.

    Args:
        event: pipeline event dict (title, score, etc.)
        analysis: analysis dict (direction, confidence, assets, etc.)
        plans: list of plan names to notify. If None, sends to all plans.

    Returns:
        Number of topics successfully notified.
    """
    if not _init_firebase():
        return 0

    try:
        from firebase_admin import messaging
    except ImportError:
        logger.error("firebase-admin package not installed")
        return 0

    assets = analysis.get("most_affected_assets", [])
    primary_asset = assets[0].upper() if assets else "CRYPTO"
    direction = analysis.get("direction", "neutral")
    confidence = analysis.get("confidence", 0)
    score = event.get("score", 0)

    if direction in ("up", "bullish", "positive", "alza"):
        dir_emoji = "📈"
        dir_text = "Alcista"
    elif direction in ("down", "bearish", "negative", "baja"):
        dir_emoji = "📉"
        dir_text = "Bajista"
    else:
        dir_emoji = "➡️"
        dir_text = "Lateral"

    title = f"{dir_emoji} {primary_asset} — Señal {dir_text}"
    body = (event.get("title") or "Nueva alerta")[:100]
    if confidence:
        body += f" | Confianza: {confidence}%"

    data = {
        "type": "alert",
        "asset": primary_asset,
        "direction": direction,
        "confidence": str(confidence),
        "score": str(score),
        "prediction_id": str(event.get("prediction_id", "")),
    }

    target_plans = plans or ["basic", "premium", "pro"]
    sent = 0

    for plan in target_plans:
        topic = _topic_for_plan(plan)
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data,
                topic=topic,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="trianio_alerts",
                        sound="default",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", badge=1),
                    ),
                ),
            )
            response = messaging.send(message)
            logger.debug(f"FCM sent to topic {topic}: {response}")
            sent += 1
        except Exception as e:
            logger.warning(f"FCM send to {topic} failed: {e}")

    if sent:
        logger.info(f"🔔 Push sent to {sent} topic(s): {primary_asset} {dir_text}")
    return sent


def send_result_to_topics(prediction_id: int, asset: str, outcome: str,
                          plans: list[str] | None = None) -> int:
    """
    Sends a push notification with a prediction result.

    Args:
        prediction_id: ID of the prediction
        asset: asset symbol
        outcome: "correct" or "incorrect"
        plans: list of plan names to notify

    Returns:
        Number of topics successfully notified.
    """
    if not _init_firebase():
        return 0

    try:
        from firebase_admin import messaging
    except ImportError:
        return 0

    if outcome == "correct":
        title = f"✅ {asset} — Predicción acertada"
        body = f"La señal de {asset} fue correcta"
    else:
        title = f"❌ {asset} — Predicción fallida"
        body = f"La señal de {asset} no se cumplió"

    data = {
        "type": "result",
        "asset": asset,
        "outcome": outcome,
        "prediction_id": str(prediction_id),
    }

    target_plans = plans or ["basic", "premium", "pro"]
    sent = 0

    for plan in target_plans:
        topic = _topic_for_plan(plan)
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data,
                topic=topic,
            )
            messaging.send(message)
            sent += 1
        except Exception as e:
            logger.warning(f"FCM result to {topic} failed: {e}")

    return sent


def subscribe_user_to_topic(fcm_token: str, plan: str) -> bool:
    """
    Subscribes a user's FCM token to their plan topic.
    Call this when user logs in or changes plan.
    """
    if not _init_firebase():
        return False

    try:
        from firebase_admin import messaging

        topic = _topic_for_plan(plan)
        response = messaging.subscribe_to_topic([fcm_token], topic)
        if response.success_count > 0:
            logger.debug(f"Subscribed token to {topic}")
            return True
        else:
            logger.warning(f"Failed to subscribe to {topic}: {response.errors}")
            return False
    except Exception as e:
        logger.error(f"Error subscribing to topic: {e}")
        return False


def unsubscribe_user_from_all(fcm_token: str) -> bool:
    """
    Unsubscribes a user's FCM token from all plan topics.
    Call this before subscribing to a new plan topic (plan change).
    """
    if not _init_firebase():
        return False

    try:
        from firebase_admin import messaging

        for topic in _all_plan_topics():
            try:
                messaging.unsubscribe_from_topic([fcm_token], topic)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Error unsubscribing from topics: {e}")
        return False


def migrate_user_topic(fcm_token: str, new_plan: str) -> bool:
    """
    Moves a user from their current topic to the new plan's topic.
    """
    unsubscribe_user_from_all(fcm_token)
    return subscribe_user_to_topic(fcm_token, new_plan)
