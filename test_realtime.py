"""
test_realtime.py — Script de prueba para verificar el sistema en tiempo real.

Comprueba:
1. Precios reales de activos (CoinGecko / yfinance)
2. Un ciclo del pipeline con noticias recientes
3. Top 3 eventos con alertas formateadas
4. Estadísticas de predicciones guardadas

Uso:
    python test_realtime.py
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

from src.services.real_price_fetcher import RealPriceFetcher
from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.alert_formatter import format_alert, MOCK_PRICES


def test_prices():
    print("\n" + "=" * 60)
    print("  💰 TEST 1: PRECIOS EN TIEMPO REAL")
    print("=" * 60)

    fetcher = RealPriceFetcher()
    assets_to_test = ["BTC", "ETH", "WTI_OIL", "SPX", "GOLD", "AAPL", "XRP"]

    for asset in assets_to_test:
        price = fetcher.get_price(asset)
        mock = MOCK_PRICES.get(asset.upper(), "N/A")
        if price is not None:
            source = "🟢 REAL"
        else:
            price = mock
            source = "🟡 MOCK"
        print(f"  {source} {asset:12s} : ${price:,.2f}" if isinstance(price, float) else f"  {source} {asset:12s} : {price}")

    print()


def test_pipeline():
    print("=" * 60)
    print("  🚀 TEST 2: CICLO DE PIPELINE")
    print("=" * 60)
    print()

    pipeline = AnalysisPipeline(db_path="/tmp/test_predictions.db")
    events = pipeline.run(minutes=180, min_score=30)

    print(f"\n✅ {len(events)} eventos relevantes encontrados\n")

    if not events:
        print("  (Sin eventos nuevos — puede que todos estén deduplicados)")
        return events

    print("=" * 60)
    print("  📊 TOP 3 EVENTOS CON ALERTAS")
    print("=" * 60)
    print()

    for event in events[:3]:
        analysis = event.get("analysis", {})
        alert = format_alert(event, analysis)
        print(alert)
        print()

    return events


def test_prediction_stats():
    print("=" * 60)
    print("  📈 TEST 3: ESTADÍSTICAS DE PREDICCIONES")
    print("=" * 60)
    print()

    tracker = PredictionTracker(db_path="/tmp/test_predictions.db")
    stats = tracker.get_accuracy_stats()
    recent = tracker.get_recent_predictions(limit=5)

    print(f"  Total predicciones: {stats['total']}")
    print(f"  Correctas:          {stats['correct']}")
    print(f"  Incorrectas:        {stats['incorrect']}")
    print(f"  Precisión:          {stats['accuracy_pct']}%")
    print()

    if recent:
        print("  Últimas predicciones:")
        for p in recent:
            status = {
                "pending": "⏳ PENDIENTE",
                "correct": "✅ CORRECTA",
                "incorrect": "❌ INCORRECTA",
            }.get(p.get("outcome", "pending"), "⏳")
            print(
                f"    {status} | {p.get('asset','?'):10s} | "
                f"dir:{p.get('direction','?'):4s} | "
                f"precio: ${p.get('price_at_prediction', 0):,.2f} | "
                f"{p.get('title','')[:40]}"
            )
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🌍 GEO-NEWSLETTER — TEST EN TIEMPO REAL")
    print("=" * 60)

    test_prices()
    events = test_pipeline()
    test_prediction_stats()

    print("=" * 60)
    print("  ✅ Tests completados")
    print("=" * 60)
    print()
