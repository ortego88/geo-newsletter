from experiment.signal_logger import log_signal
from datetime import datetime, UTC
import time

# simulamos alerta temprana
log_signal("refinery fire", "Iran", "energy")

print("Early signal logged")

# esperamos 10 segundos
time.sleep(10)

# simulamos noticia confirmada
confirmation_time = datetime.now(UTC)

print("Reuters article appears at:", confirmation_time)