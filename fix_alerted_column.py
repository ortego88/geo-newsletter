#!/usr/bin/env python3
"""
Script para marcar como 'alerted=1' las predicciones que deberían haber sido alertadas.

Criterio: Todas las predicciones con score >= 65 y confidence >= 65
"""
from sqlalchemy import text
from web.db_engine import get_engine

def main():
    engine = get_engine("predictions")

    with engine.connect() as conn:
        # Count predictions that should have been alerted
        result = conn.execute(text("""
            SELECT COUNT(*) FROM predictions
            WHERE (alerted IS NULL OR alerted = 0)
              AND score >= 65
              AND confidence >= 65
              AND outcome != 'neutral'
        """)).fetchone()

        count = result[0] if result else 0
        print(f"Found {count} predictions to mark as alerted")

        if count > 0:
            # Update them
            conn.execute(text("""
                UPDATE predictions
                SET alerted = 1
                WHERE (alerted IS NULL OR alerted = 0)
                  AND score >= 65
                  AND confidence >= 65
                  AND outcome != 'neutral'
            """))
            conn.commit()
            print(f"✅ Updated {count} predictions to alerted=1")
        else:
            print("No predictions to update")

if __name__ == "__main__":
    main()
