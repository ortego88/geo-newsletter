"""
Script de prueba — envía un resumen simulado al canal de Telegram.
Ejecutar en Railway: python send_test_summary.py

Usa datos simulados para que veas cómo se ve el formato.
Después puedes borrarlo.
"""
import os
import sys

if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHANNEL_ID"):
    print("ERROR: Necesitas TELEGRAM_BOT_TOKEN y TELEGRAM_CHANNEL_ID")
    sys.exit(1)

import requests
from datetime import datetime, timedelta

ASSET_ICONS = {'BTC': '₿', 'ETH': 'Ξ', 'SOL': '◎', 'XRP': '✕', 'ADA': '₳', 'DOT': '●', 'AVAX': '🔺', 'LINK': '⬡', 'MATIC': '⬟', 'DOGE': '🐕'}
ASSET_NAMES = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'XRP': 'Ripple', 'ADA': 'Cardano', 'DOT': 'Polkadot', 'AVAX': 'Avalanche', 'LINK': 'Chainlink', 'MATIC': 'Polygon', 'DOGE': 'Dogecoin'}

yesterday_display = (datetime.now() - timedelta(days=1)).strftime('%d/%m/%Y')

lines = []
lines.append("📊 RESUMEN DEL DÍA — Trianio")
lines.append(f"📅 {yesterday_display}")
lines.append("")
lines.append("🏆 Precisión: 73%")
lines.append("📬 Alertas enviadas: 12")
lines.append("✅ Correctas: 8")
lines.append("❌ Incorrectas: 3")
lines.append("⏳ Pendientes: 1")
lines.append("")
lines.append("━━━━━━━━━━━━━━━━━━━━")
lines.append("📋 Detalle por activo:")
lines.append("")
lines.append("  ₿ Bitcoin: ✅2 ❌1")
lines.append("  Ξ Ethereum: ✅2")
lines.append("  ◎ Solana: ✅1 ❌1")
lines.append("  ✕ Ripple: ✅1")
lines.append("  🔺 Avalanche: ✅1")
lines.append("  ₳ Cardano: ✅1")
lines.append("  ● Polkadot: ❌1")
lines.append("  ⬡ Chainlink: ⏳1")
lines.append("")
lines.append("━━━━━━━━━━━━━━━━━━━━")
lines.append("🔥 ¡Gran día! Nuestro sistema de IA sigue mejorando.")
lines.append("")
lines.append("💎 Recibe alertas personalizadas de +35 criptomonedas")
lines.append("👉 Suscríbete en trianio.com")

msg = "\n".join(lines)

token = os.getenv("TELEGRAM_BOT_TOKEN")
channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

resp = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data={"chat_id": channel_id, "text": msg},
    timeout=10,
)

if resp.status_code == 200:
    print("✅ Resumen de prueba enviado al canal")
else:
    print(f"❌ Error: {resp.status_code} — {resp.text[:200]}")
