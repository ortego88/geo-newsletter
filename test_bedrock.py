#!/usr/bin/env python3
"""
Script de prueba para verificar que Claude via Bedrock funciona correctamente.
Ejecutar: python test_bedrock.py
"""
import os
import sys
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_bedrock_config():
    """Verifica la configuración de Bedrock."""
    print("\n" + "="*60)
    print("🔍 VERIFICANDO CONFIGURACIÓN DE BEDROCK")
    print("="*60 + "\n")

    config = {
        "USE_BEDROCK": os.getenv("USE_BEDROCK", "NOT SET"),
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID", "NOT SET")[:20] + "..." if os.getenv("AWS_ACCESS_KEY_ID") else "NOT SET",
        "AWS_SECRET_ACCESS_KEY": "***" if os.getenv("AWS_SECRET_ACCESS_KEY") else "NOT SET",
        "AWS_REGION": os.getenv("AWS_REGION", "NOT SET"),
        "BEDROCK_MODEL_ID": os.getenv("BEDROCK_MODEL_ID", "NOT SET"),
        "OPENAI_API_KEY": "***" if os.getenv("OPENAI_API_KEY") else "NOT SET",
    }

    for key, value in config.items():
        status = "✅" if value != "NOT SET" else "❌"
        print(f"{status} {key}: {value}")

    use_bedrock = os.getenv("USE_BEDROCK", "").lower() in ("true", "1", "yes")
    print(f"\n{'✅' if use_bedrock else '❌'} Bedrock está {'ACTIVADO' if use_bedrock else 'DESACTIVADO'}")

    return use_bedrock


def test_claude_import():
    """Verifica que el módulo de Claude se puede importar."""
    print("\n" + "="*60)
    print("📦 VERIFICANDO IMPORTS")
    print("="*60 + "\n")

    try:
        from src.services.claude_analyzer import analyze_event_with_claude, ClaudeAnalyzer
        print("✅ claude_analyzer importado correctamente")

        analyzer = ClaudeAnalyzer()
        is_available = analyzer.is_available()
        print(f"{'✅' if is_available else '❌'} Claude está {'disponible' if is_available else 'NO disponible'}")

        return True, analyzer
    except Exception as e:
        print(f"❌ Error importando claude_analyzer: {e}")
        return False, None


def test_prediction():
    """Prueba una predicción real."""
    print("\n" + "="*60)
    print("🧪 PROBANDO PREDICCIÓN CON CLAUDE")
    print("="*60 + "\n")

    # Evento de prueba
    test_event = {
        "title": "Repsol sube un 3% tras anuncio de OPEC de recorte de producción",
        "description": "La OPEC ha anunciado un recorte de producción de 1 millón de barriles diarios, lo que impulsa los precios del petróleo.",
        "category": "energy",
        "score": 75,
        "suggested_asset": "REP"
    }

    try:
        from src.services.claude_analyzer import analyze_event_with_claude

        print("Analizando evento de prueba...")
        print(f"📰 Título: {test_event['title']}\n")

        result = analyze_event_with_claude(test_event)

        if result:
            print("✅ PREDICCIÓN EXITOSA:\n")
            print(f"  🎯 Dirección: {result.get('direction')}")
            print(f"  📊 Confidence: {result.get('confidence')}%")
            print(f"  💪 Signal strength: {result.get('signal_strength')}")
            print(f"  📈 Activos: {', '.join(result.get('most_affected_assets', []))}")
            print(f"  💭 Reasoning: {result.get('reasoning', '')}")

            if result.get('historical_learning'):
                print(f"  🧠 Historical learning: {result.get('historical_learning')}")

            return True
        else:
            print("❌ La predicción devolvió None (probablemente cayó a fallback)")
            return False

    except Exception as e:
        print(f"❌ Error en predicción: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta todas las pruebas."""
    print("\n" + "🚀"*30)
    print("SCRIPT DE DIAGNÓSTICO - CLAUDE VIA BEDROCK")
    print("🚀"*30 + "\n")

    # Test 1: Configuración
    bedrock_enabled = test_bedrock_config()

    # Test 2: Imports
    can_import, analyzer = test_claude_import()

    if not can_import:
        print("\n❌ No se puede continuar: error en imports")
        return

    # Test 3: Predicción
    if bedrock_enabled:
        success = test_prediction()

        if success:
            print("\n" + "="*60)
            print("✅ TODO FUNCIONA CORRECTAMENTE")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("⚠️  LA PREDICCIÓN FALLÓ - Revisa los logs arriba")
            print("="*60)
    else:
        print("\n⚠️  Bedrock está desactivado, no se puede probar predicción")

    print("\n" + "🏁"*30)
    print("FIN DEL DIAGNÓSTICO")
    print("🏁"*30 + "\n")


if __name__ == "__main__":
    main()
