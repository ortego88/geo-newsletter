"""
seed_test_users.py — Creates 10 test accounts with @trianio.com emails.
Run once: python3 seed_test_users.py

All accounts get plan=pro, status=active (no trial expiry).
Password for all: Trianio2026!
"""
import os
import sys

os.makedirs("data", exist_ok=True)

from web.models import User, init_db, get_conn
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

SHARED_PASSWORD = "Trianio2026!"

TEST_USERS = [
    {"email": "demo1@trianio.com", "name": "Demo User 1"},
    {"email": "demo2@trianio.com", "name": "Demo User 2"},
    {"email": "demo3@trianio.com", "name": "Demo User 3"},
    {"email": "demo4@trianio.com", "name": "Demo User 4"},
    {"email": "demo5@trianio.com", "name": "Demo User 5"},
    {"email": "demo6@trianio.com", "name": "Demo User 6"},
    {"email": "demo7@trianio.com", "name": "Demo User 7"},
    {"email": "demo8@trianio.com", "name": "Demo User 8"},
    {"email": "demo9@trianio.com", "name": "Demo User 9"},
    {"email": "demo10@trianio.com", "name": "Demo User 10"},
]


def main():
    init_db()
    pw_hash = generate_password_hash(SHARED_PASSWORD)
    now = datetime.now(timezone.utc).isoformat()
    created = 0

    with get_conn() as conn:
        for u in TEST_USERS:
            existing = conn.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": u["email"]},
            ).fetchone()
            if existing:
                print(f"  ⏭️  {u['email']} ya existe (id={existing[0]})")
                continue

            result = conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, name, language, created_at, is_active) "
                    "VALUES (:email, :pw, :name, 'es', :now, 1) RETURNING id"
                ),
                {"email": u["email"], "pw": pw_hash, "name": u["name"], "now": now},
            )
            user_id = result.fetchone()[0]

            conn.execute(
                text(
                    "INSERT INTO subscriptions (user_id, plan, billing_cycle, status, created_at, updated_at) "
                    "VALUES (:uid, 'pro', 'monthly', 'active', :now, :now)"
                ),
                {"uid": user_id, "now": now},
            )
            created += 1
            print(f"  ✅ {u['email']} creado (id={user_id}, plan=pro, status=active)")

        conn.commit()

    print(f"\n{'='*50}")
    print(f"✅ {created} usuarios creados")
    print(f"📧 Dominio: @trianio.com")
    print(f"🔑 Contraseña compartida: {SHARED_PASSWORD}")
    print(f"📋 Plan: Profesional (pro) — activo, sin trial")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
