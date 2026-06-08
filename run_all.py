"""
run_all.py — Punto de entrada para producción en Railway.
Lanza el scheduler en un thread y Flask dashboard en el proceso principal.

Variables de entorno requeridas:
  DATABASE_URL    — conexión PostgreSQL (obligatorio en todos los entornos)
  OPENAI_API_KEY  — clave de OpenAI
  PORT            — puerto para el dashboard (Railway lo asigna automáticamente)
  DASHBOARD_PORT  — alternativa, por defecto 8080
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime

# Crear directorio data si no existe (para logs y caché de deduplicación)
os.makedirs("data", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Configurar logging con salida a stdout Y a fichero
file_handler = logging.FileHandler("data/scheduler.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), file_handler],
)
logger = logging.getLogger("run_all")

# Comprobar configuración de BD — DATABASE_URL es obligatorio
_db_url = os.getenv("DATABASE_URL", "").strip()
if not _db_url:
    logger.error(
        "❌ FATAL: DATABASE_URL no configurada. "
        "PostgreSQL es obligatorio en todos los entornos. "
        "Configura DATABASE_URL=postgresql://user:password@host:5432/dbname"
    )
    sys.exit(1)
logger.info("✅ DATABASE_URL detectada — usando PostgreSQL (datos persistentes entre deploys)")

from apscheduler.schedulers.background import BackgroundScheduler
from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.prediction_validator_scheduler import PredictionValidatorScheduler
from web.app import create_app

flask_app = create_app()

DB_PATH = "data/predictions.db"

pipeline = AnalysisPipeline(db_path=DB_PATH)
tracker = PredictionTracker(db_path=DB_PATH)
validator = PredictionValidatorScheduler(tracker=tracker, interval_minutes=5)


def _get_event_assets(event: dict) -> set:
    """Returns the set of uppercase asset symbols for a pipeline event."""
    return {a.upper() for a in event.get("analysis", {}).get("most_affected_assets", [])}


def _send_per_user_alerts(events: list, format_fn, send_fn) -> int:
    """
    Envía alertas de Telegram personalizadas a cada usuario activo que tenga
    configurado su telegram_chat_id y cuyos activos suscritos coincidan con
    alguno de los eventos. Registra cada envío exitoso en alert_log.
    
    ✅ Las alertas se envían 24/7 sin restricción de horarios.
    Los horarios de mercado solo afectan a la verificación posterior de predicciones.
    """
    try:
        from sqlalchemy import text as _text
        from web.db_engine import get_engine as _get_engine
        from web.models import PLANS
    except Exception as e:
        logger.error(f"Error importando dependencias para alertas per-usuario: {e}")
        return

    try:
        with _get_engine("app").connect() as conn:
            rows = conn.execute(_text("""
                SELECT u.id, u.telegram_chat_id, s.plan, s.status, s.selected_assets, u.language
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                WHERE u.telegram_chat_id IS NOT NULL
                  AND u.telegram_chat_id != ''
                  AND u.is_active = 1
                  AND s.status IN ('active', 'trial')
                ORDER BY u.id
            """)).fetchall()
    except Exception as e:
        logger.warning(f"No se pudo consultar usuarios para alertas: {e}")
        return

    if not rows:
        logger.info("Sin usuarios con Telegram configurado para alertas per-usuario")
        return

    now_iso = datetime.utcnow().isoformat()

    user_sent = 0
    for row in rows:
        user_id, chat_id, plan, status, selected_assets_raw, user_language = row
        user_language = user_language or "es"
        selected = {a.strip().upper() for a in (selected_assets_raw or "").split(",") if a.strip()}
        if not selected:
            continue

        plan_cfg = PLANS.get(plan, PLANS["basic"])
        max_daily = plan_cfg.get("max_daily_alerts", 5)

        # Check daily alert count for this user
        if max_daily != -1:
            try:
                day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                with _get_engine("app").connect() as conn:
                    daily_count = conn.execute(_text(
                        "SELECT COUNT(*) FROM alert_log WHERE user_id=:uid AND sent_at >= :day_start"
                    ), {"uid": user_id, "day_start": day_start}).fetchone()[0]
            except Exception:
                daily_count = 0
        else:
            daily_count = 0

        for event in events:
            if max_daily != -1 and daily_count >= max_daily:
                break

            event_assets = _get_event_assets(event)
            if not (event_assets & selected):
                continue

            msg = format_fn(event, event["analysis"], language=user_language)
            if send_fn(msg, chat_id=chat_id):
                user_sent += 1
                daily_count += 1
                asset_sent = next(iter(event_assets & selected), "")
                direction = event.get("analysis", {}).get("direction", "")
                score = int(event.get("score", 0))
                try:
                    with _get_engine("app").connect() as conn:
                        conn.execute(_text(
                            "INSERT INTO alert_log (user_id, asset, direction, score, sent_at) "
                            "VALUES (:uid, :asset, :dir, :score, :sent_at)"
                        ), {"uid": user_id, "asset": asset_sent, "dir": direction,
                            "score": score, "sent_at": now_iso})
                        conn.commit()
                except Exception as log_err:
                    logger.warning(f"No se pudo registrar en alert_log (user {user_id}): {log_err}")

    logger.info(f"📬 Alertas per-usuario enviadas: {user_sent} (a {len(rows)} usuarios con Telegram)")
    return user_sent


def _send_pipeline_alerts(events: list):
    """
    Envía alertas individuales de Telegram para cada evento relevante del ciclo.
    - Envía al canal global (TELEGRAM_CHAT_ID) si está configurado.
    - Envía también a cada usuario con telegram_chat_id y activos suscritos coincidentes.
    - Registra cada envío en la tabla alert_log.
    - Los conflictos de señal ya fueron resueltos por pipeline.run() (Paso 7).
    
    ✅ IMPORTANTE: Las alertas se envían 24/7 sin restricción de horarios.
    No se usa is_market_open() aquí. Solo se filtra por score >= 60.
    Los horarios de mercado solo afectan a la verificación posterior de predicciones
    en PredictionValidatorScheduler.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado — alertas desactivadas")
        return

    try:
        from src.services.telegram_sender import send_telegram, get_subscribed_assets
        from src.services.alert_formatter import format_telegram_alert
    except Exception as e:
        logger.error(f"Error importando módulos de alerta: {e}")
        return

    # Step 1: filter alertable events — exclude silent signals
    # News: DOWN>=65, UP>=75 (Claude analysis, strict)
    # Price signals: DOWN>=65, UP>=65 (real Binance data, objective)
    resolved = []
    for e in events:
        if e.get("_silent"):  # never send silent calibration signals to users
            continue
        if not e.get("analysis") or e.get("score", 0) < 60:
            continue
        conf = e.get("analysis", {}).get("confidence", 0)
        direction = e.get("analysis", {}).get("direction", "")
        is_price_signal = "price_signal" in e.get("source", "")
        if is_price_signal:
            min_conf = 65  # price signals are objective data, same threshold both ways
        else:
            min_conf = 75 if direction == "up" else 65  # news: stricter for UP
        if conf >= min_conf:
            resolved.append(e)

    if not resolved:
        logger.info("Sin eventos con confianza suficiente (DOWN≥65, UP≥75) para alertar")
        return

    # Only send alerts for events that were saved in the predictions DB.
    saved_predictions = [e for e in resolved if e.get("prediction_id")]
    if not saved_predictions:
        logger.info("Ninguna predicción guardada en DB para alertar")
        return

    # Step 1b: Apply historical accuracy filter
    try:
        from src.services.prediction_filter import should_send_alert
        filtered = []
        for event in saved_predictions:
            should_send, reason = should_send_alert(event)
            if should_send:
                filtered.append(event)
            else:
                logger.info(f"   🚫 Filtrada por histórico: {reason} | {event.get('title', '')[:50]}")
        if len(filtered) < len(saved_predictions):
            logger.info(f"📊 Filtro histórico: {len(saved_predictions)}→{len(filtered)} alertas")
        saved_predictions = filtered
    except Exception as e:
        logger.warning(f"Error en filtro histórico (enviando todas): {e}")

    if not saved_predictions:
        logger.info("Todas las alertas filtradas por histórico de accuracy")
        return

    logger.info(f"📊 {len(saved_predictions)} eventos listos para alertar")

    # Step 2: send per-user alerts based on telegram_chat_id + selected_assets
    # (the public channel only gets 1 BTC alert/day via send_daily_channel_alert + daily summary)
    alerted_prediction_ids = set()
    user_sent = _send_per_user_alerts(saved_predictions, format_telegram_alert, send_telegram)
    for event in saved_predictions:
        alerted_prediction_ids.add(event.get("prediction_id"))

    # Step 2b: send FCM push notifications — only to users who have the asset selected
    try:
        from src.services.firebase_push import send_push_to_user_tokens
        from web.db_engine import get_engine as _ge
        from sqlalchemy import text as _text

        with _ge("app").connect() as _conn:
            _user_tokens = _conn.execute(_text("""
                SELECT u.id, u.telegram_chat_id, s.plan, s.selected_assets, t.token
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                LEFT JOIN user_fcm_tokens t ON t.user_id = u.id
                WHERE t.token IS NOT NULL
                  AND s.status IN ('active', 'trial')
                  AND u.is_active = 1
            """)).fetchall()

        for event in saved_predictions:
            _asset = (event.get("analysis", {}).get("most_affected_assets", []) or [""])[0].upper()
            if not _asset:
                continue
            for _uid, _chat_id, _plan, _sel_raw, _token in _user_tokens:
                _selected = {a.strip().upper() for a in (_sel_raw or "").split(",") if a.strip()}
                if _asset in _selected:
                    send_push_to_user_tokens(event, event.get("analysis", {}), [_token])
    except Exception as e:
        logger.debug(f"FCM push skipped: {e}")

    # Step 3: mark sent predictions as alerted (for historical filter accuracy)
    for pid in alerted_prediction_ids:
        if pid:
            tracker.mark_as_alerted(pid)

    logger.info(f"📤 Total alertas per-usuario enviadas en este ciclo: {user_sent}")


def run_pipeline_cycle():
    logger.info("=" * 60)
    logger.info(f"⏱️  CICLO DE PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    try:
        events = pipeline.run(minutes=180, min_score=45)
        if not events:
            events = []
            logger.info("Sin eventos de noticias en este ciclo.")

        # Price signals via Binance (3-min cache, no rate limit):
        # - 2.5-5% move (_silent=False): ALERTABLE — early signal, user can still act
        # - >5% move (_silent=True): calibration only — too late to enter
        try:
            from src.services.price_signals import check_price_signals
            from src.services.real_price_fetcher import get_price as _gp

            price_events = check_price_signals()
            for pe in price_events:
                asset = pe.get("suggested_asset", "")
                change = pe.get("_change_pct", 0)
                price_now = _gp(asset) or 0.0
                if price_now <= 0:
                    continue
                direction = "down" if change < 0 else "up"
                pe["analysis"] = {
                    "direction": direction,
                    "confidence": 70,
                    "most_affected_assets": [asset],
                    "timeframe": "hours",
                    "reasoning": f"{asset} {change:+.1f}% en 24h — {'señal temprana' if not pe.get('_silent') else 'calibración'}",
                    "signal_strength": "high" if abs(change) >= 4 else "medium",
                    "verification_window_hours": 24,
                }
                pred_id = tracker.save_prediction(pe, price_now)
                if pred_id:
                    pe["prediction_id"] = pred_id
                    pe["price_at_prediction"] = price_now
                    if not pe.get("_silent"):
                        events.append(pe)  # early moves go to user alerts
            if price_events:
                early = sum(1 for p in price_events if not p.get("_silent"))
                late = len(price_events) - early
                logger.info(f"📊 Price signals: {early} alertables (2.5-5%), {late} silenciosas (>5%)")
        except Exception as e:
            logger.debug(f"Price signals error: {e}")

        if not events:
            return
        logger.info(f"✅ {len(events)} eventos relevantes encontrados")
        stats = tracker.get_accuracy_stats()
        logger.info(
            f"📊 Precisión: {stats['accuracy_pct']}% ({stats['correct']}/{stats['total']} correctas)"
        )

        # Send Telegram alerts
        _send_pipeline_alerts(events)

        # Send first BTC alert of the day to channel (immediate, max 1/day)
        try:
            from src.services.channel_alert import send_daily_channel_alert
            send_daily_channel_alert(events)
        except Exception as e:
            logger.warning(f"Error en alerta de canal: {e}")

    except Exception as e:
        logger.error(f"Error en ciclo de pipeline: {e}", exc_info=True)
    finally:
        try:
            from src.services.claude_analyzer import get_daily_token_usage
            usage = get_daily_token_usage()
            if usage["calls"] > 0:
                logger.info(
                    f"💰 Tokens hoy ({usage['date']}): "
                    f"input={usage['input_tokens']:,} output={usage['output_tokens']:,} "
                    f"calls={usage['calls']}"
                )
        except Exception:
            pass


def run_gem_scan_cycle():
    """Separate cycle for gem detection — isolated from main predictions."""
    try:
        from src.services.gem_scanner import (
            run_gem_scan, save_gem_signals, send_gem_alerts_admin, validate_pending_gems,
            _get_current_price_dexscreener, _get_current_price_binance,
        )
        admin_chat_id = os.getenv("GEM_ADMIN_CHAT_ID", "161542135")

        signals = run_gem_scan()
        if signals:
            for sig in signals:
                if "binance" in sig["source"]:
                    sig["_price"] = _get_current_price_binance(sig["symbol"])
                else:
                    sig["_price"] = _get_current_price_dexscreener(sig["address"])
            save_gem_signals(signals)
            send_gem_alerts_admin(signals, admin_chat_id)

        validate_pending_gems(admin_chat_id)
    except Exception as e:
        logger.warning(f"Error en gem scan: {e}")


def run_microstructure_cycle():
    """
    Runs every 3 minutes to catch whale trades/funding rate signals.
    Separate from the 10-min news pipeline to avoid missing short-lived events.
    """
    try:
        from src.services.market_microstructure import scan_microstructure_signals
        from src.services.real_price_fetcher import get_price
        micro_signals = scan_microstructure_signals()
        if not micro_signals:
            return

        events = []
        for ms in micro_signals:
            asset = ms.get("suggested_asset", "")
            price_now = get_price(asset) or 0.0
            if price_now <= 0:
                continue
            pred_id = tracker.save_prediction(ms, price_now)
            if pred_id:
                ms["prediction_id"] = pred_id
                ms["price_at_prediction"] = price_now
                events.append(ms)

        if events:
            logger.info(f"🔬 {len(events)} señales de microestructura guardadas")
            _send_pipeline_alerts(events)
    except Exception as e:
        logger.warning(f"Error en microstructure cycle: {e}")


def start_scheduler():
    validator.start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_pipeline_cycle,
        "interval",
        minutes=10,
        id="pipeline_cycle",
        next_run_time=datetime.now(),
    )
    # Microstructure: every 3 minutes (whale trades window = 3 min, no blind spots)
    scheduler.add_job(
        run_microstructure_cycle,
        "interval",
        minutes=3,
        id="microstructure_cycle",
        next_run_time=datetime.now(),
    )
    # Gem scanner: every 4 hours (max 1 signal/cycle = ~6 checks/day)
    scheduler.add_job(
        run_gem_scan_cycle,
        "interval",
        hours=4,
        id="gem_scan",
        next_run_time=datetime.now(),
    )
    # Weekly digest: every Sunday at 10:00 AM (Madrid time) for Premium/Pro users
    from src.services.weekly_digest import send_weekly_digest
    scheduler.add_job(
        lambda: send_weekly_digest(DB_PATH, os.getenv("APP_DB_PATH", "data/app.db")),
        "cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        timezone="Europe/Madrid",
        id="weekly_digest",
    )
    # Newsletter: every Monday at 8:00 AM (Madrid time) for all subscribers
    from src.services.newsletter_sender import send_weekly_newsletter
    scheduler.add_job(
        send_weekly_newsletter,
        "cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        timezone="Europe/Madrid",
        id="weekly_newsletter",
    )
    # Daily blog post: every day at 9:00 AM (Madrid time)
    def publish_daily_blog_post():
        try:
            import subprocess
            import sys
            result = subprocess.run(
                [sys.executable, "create_daily_blog_post.py"],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                logger.info("✅ Artículo de blog publicado correctamente")
            else:
                logger.warning(f"⚠️ Error publicando artículo: {result.stderr}")
        except Exception as e:
            logger.error(f"❌ Error en job de blog diario: {e}")

    scheduler.add_job(
        publish_daily_blog_post,
        "cron",
        hour=9,
        minute=0,
        timezone="Europe/Madrid",
        id="daily_blog_post",
    )
    # Daily channel summary: 10:00 Madrid — yesterday's prediction results
    def send_channel_summary():
        try:
            from src.services.channel_alert import send_daily_summary
            send_daily_summary()
        except Exception as e:
            logger.warning(f"Error enviando resumen diario al canal: {e}")

    scheduler.add_job(
        send_channel_summary,
        "cron",
        hour=10,
        minute=0,
        timezone="Europe/Madrid",
        id="daily_channel_summary",
    )
    # Channel membership sync: every hour, kick expired subscribers
    def sync_channel():
        try:
            from src.services.channel_members import sync_channel_members
            sync_channel_members()
        except Exception as e:
            logger.warning(f"Error en sync de canal: {e}")

    scheduler.add_job(
        sync_channel,
        "interval",
        hours=1,
        id="channel_sync",
    )
    scheduler.start()
    logger.info("✅ Scheduler iniciado (pipeline cada 10 min, canal sync cada 1h, blog diario 9:00 AM)")
    logger.info("✅ Alertas: canal (1ª BTC del día) + resumen 10:00 + bot individual (personalizadas)")
    logger.info("✅ Verificación: respeta horarios de mercado (Crypto 24/7)")
    return scheduler


def start_dashboard(port: int):
    """Inicia el servidor Flask del dashboard."""
    try:
        debug_mode = os.getenv("FLASK_ENV", "production") == "development" or os.getenv("DEBUG", "").lower() in ("1", "true")
        logger.info(f"🌐 Dashboard iniciando en puerto {port}{'  [modo desarrollo — hot-reload activo]' if debug_mode else ''}...")
        flask_app.run(host="0.0.0.0", port=port, debug=debug_mode, threaded=True, use_reloader=debug_mode)
    except Exception as e:
        logger.error(f"Error iniciando dashboard: {e}", exc_info=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))

    logger.info("=" * 60)
    logger.info("  🌍 Trianio — PRODUCCIÓN (Railway)")
    logger.info("=" * 60)
    logger.info(f"  Dashboard: http://0.0.0.0:{port}")
    logger.info(f"  OpenAI: {'✅ configurado' if os.getenv('OPENAI_API_KEY') else '⚠️  NO configurado (usando Ollama)'}")
    logger.info("=" * 60)

    # Iniciar scheduler en background thread
    scheduler = start_scheduler()

    # Iniciar Flask en el thread principal (Railway necesita que el proceso principal escuche en PORT)
    start_dashboard(port)
