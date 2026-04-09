"""
Dashboard web para geo-newsletter.
Ejecutar con: python dashboard.py
Abrir en: http://localhost:5000
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytz
from flask import Flask, Response, jsonify, render_template, request

from src.services.prediction_tracker import PredictionTracker

_MADRID_TZ = pytz.timezone("Europe/Madrid")


def _now_madrid():
    return datetime.now(_MADRID_TZ)

app = Flask(__name__)

DB_PATH = "data/predictions.db"
LOG_PATH = "data/scheduler.log"
DEDUP_PATH = "data/seen_articles.txt"

tracker = PredictionTracker(db_path=DB_PATH)

_pipeline_running = False
_last_run = None
_last_run_count = 0


def tail_log_file(path, n=200):
    try:
        p = Path(path)
        if not p.exists():
            return ["(Sin logs aun. Arranca run_scheduler.py en otra terminal para ver logs aqui)"]
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip() for line in lines[-n:]]
    except Exception:
        return ["Error leyendo log."]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    stats = tracker.get_accuracy_stats()
    return jsonify({
        "total": stats.get("total", 0),
        "correct": stats.get("correct", 0),
        "incorrect": stats.get("incorrect", 0),
        "accuracy_pct": stats.get("accuracy_pct", 0.0),
        "last_run": _last_run,
        "last_run_count": _last_run_count,
        "pipeline_running": _pipeline_running,
    })


@app.route("/api/predictions")
def api_predictions():
    period = request.args.get("period", "24h")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    result = tracker.get_predictions_paginated(period=period, page=page, page_size=page_size)
    return jsonify(result)


@app.route("/api/logs")
def api_logs():
    n = int(request.args.get("n", 200))
    lines = tail_log_file(LOG_PATH, n)
    return jsonify({"lines": lines, "count": len(lines)})


@app.route("/api/status")
def api_status():
    dedup_exists = Path(DEDUP_PATH).exists()
    dedup_count = 0
    if dedup_exists:
        try:
            with open(DEDUP_PATH) as f:
                dedup_count = sum(1 for _ in f)
        except Exception:
            pass

    log_exists = Path(LOG_PATH).exists()
    scheduler_active = False
    if log_exists:
        try:
            mtime = Path(LOG_PATH).stat().st_mtime
            age_minutes = (time.time() - mtime) / 60
            scheduler_active = age_minutes < 15
        except Exception:
            pass

    return jsonify({
        "scheduler_log_exists": log_exists,
        "scheduler_active": scheduler_active,
        "dedup_file_exists": dedup_exists,
        "dedup_articles_seen": dedup_count,
        "db_exists": Path(DB_PATH).exists(),
        "pipeline_running": _pipeline_running,
        "last_run": _last_run,
        "timestamp": _now_madrid().isoformat(),
    })


@app.route("/api/run-pipeline", methods=["POST"])
def api_run_pipeline():
    global _pipeline_running, _last_run, _last_run_count

    if _pipeline_running:
        return jsonify({"status": "already_running", "message": "Pipeline ya en ejecucion"}), 409

    def _run():
        global _pipeline_running, _last_run, _last_run_count
        _pipeline_running = True
        try:
            from src.services.pipeline_v2 import AnalysisPipeline
            pl = AnalysisPipeline(db_path=DB_PATH)
            events = pl.run(minutes=360, min_score=30)
            _last_run_count = len(events) if events else 0
            _last_run = _now_madrid().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            _last_run = "ERROR: Pipeline falló. Revisa los logs."
        finally:
            _pipeline_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"status": "started", "message": "Pipeline iniciado en segundo plano"})


@app.route("/api/reset-dedup", methods=["POST"])
def api_reset_dedup():
    try:
        p = Path(DEDUP_PATH)
        if p.exists():
            p.unlink()
        return jsonify({"status": "ok", "message": "Deduplicador reseteado."})
    except Exception as e:
        return jsonify({"status": "error", "message": "Error al resetear el deduplicador."}), 500


@app.route("/stream/logs")
def stream_logs():
    def generate():
        last_size = 0
        while True:
            try:
                p = Path(LOG_PATH)
                if p.exists():
                    current_size = p.stat().st_size
                    if current_size != last_size:
                        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_size)
                            new_content = f.read()
                        last_size = current_size
                        for line in new_content.splitlines():
                            if line.strip():
                                yield f"data: {json.dumps(line)}\n\n"
            except Exception:
                pass
            time.sleep(2)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print("=" * 60)
    print("  GEO-NEWSLETTER DASHBOARD")
    print("=" * 60)
    print("  Abre en tu navegador: http://localhost:5000")
    print(f"  Base de datos:        {DB_PATH}")
    print(f"  Log del scheduler:    {LOG_PATH}")
    print("=" * 60)
    os.makedirs("data", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
