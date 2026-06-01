#!/usr/bin/env python3
"""test_push.py — Envía una alerta push de prueba a todos los topics."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

fake_event = {
    "title": "Test: Reserva Federal mantiene tipos de interés sin cambios",
    "score": 82,
    "prediction_id": 9999,
}

fake_analysis = {
    "direction": "up",
    "confidence": 78,
    "most_affected_assets": ["BTC"],
    "timeframe": "hours",
}

from src.services.firebase_push import send_alert_to_topics
sent = send_alert_to_topics(fake_event, fake_analysis)
print(f"Push enviado a {sent} topics")
