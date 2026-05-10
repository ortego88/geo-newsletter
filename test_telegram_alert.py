#!/usr/bin/env python3
"""
Script para testear el envío de alertas de Telegram manualmente.
Crea una predicción de prueba y fuerza su envío sin esperar al ciclo del scheduler.
"""
import os
import sys
from datetime import datetime

# Asegurar que el path incluye el directorio del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.telegram_sender import send_telegram
from src.services.alert_formatter import format_telegram_alert

def test_alert():
    """Envía una alerta de prueba a Telegram."""

    # Evento de prueba
    test_event = {
        "title": "🧪 ALERTA DE PRUEBA - Sistema de notificaciones activo",
        "description": "Esta es una alerta de prueba para verificar que Telegram está funcionando correctamente.",
        "score": 75,
        "category": "test",
        "sources": ["test_script"],
        "prediction_id": 999999,
        "analysis": {
            "direction": "up",
            "confidence": 85,
            "most_affected_assets": ["BTC", "ETH"],
            "signal_strength": "high",
            "timeframe": "hours",
            "reasoning": "Prueba del sistema de alertas - Si recibes esto, todo funciona correctamente ✅",
            "market_impact_percent": 2.5,
        }
    }

    # Formatear mensaje
    msg = format_telegram_alert(test_event, test_event["analysis"])

    print("=" * 60)
    print("ENVIANDO ALERTA DE PRUEBA A TELEGRAM")
    print("=" * 60)
    print("\nMensaje a enviar:")
    print("-" * 60)
    print(msg)
    print("-" * 60)

    # Enviar
    success = send_telegram(msg)

    if success:
        print("\n✅ Alerta enviada correctamente a Telegram")
        print("Revisa tu canal/chat de Telegram")
    else:
        print("\n❌ Error al enviar alerta")
        print("Verifica:")
        print("  1. TELEGRAM_BOT_TOKEN está configurado")
        print("  2. TELEGRAM_CHAT_ID está configurado")
        print("  3. El bot tiene permisos para enviar mensajes al canal")

    return success


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN no configurado")
        sys.exit(1)

    if not chat_id:
        print("❌ TELEGRAM_CHAT_ID no configurado")
        sys.exit(1)

    print(f"Bot Token: {token[:10]}...{token[-4:]}")
    print(f"Chat ID: {chat_id}")
    print()

    success = test_alert()
    sys.exit(0 if success else 1)
