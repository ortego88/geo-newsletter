import sys
import os
from experiment.news_verifier import verify_signals

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

from main import run
from alerts.morning_digest import run_morning_digest

scheduler = BlockingScheduler()

def realtime():

    from datetime import datetime, UTC

    print("Running realtime alerts:", datetime.now(UTC))
    run()

scheduler.add_job(realtime, "interval", minutes=10)

scheduler.add_job(run_morning_digest, "cron", hour=9)

scheduler.add_job(verify_signals, "interval", minutes=30)

scheduler.start()