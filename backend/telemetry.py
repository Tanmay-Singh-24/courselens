"""CourseLens — lightweight query telemetry.

Appends one row per query (latency, token usage, retrieval attempts, #sources) to a
local CSV. Cheap "production-mindset" instrumentation; the file is gitignored and
best-effort — logging must never break a response.
"""
import csv
import os
from datetime import datetime

from backend.config import PROJECT_DIR

LOG_PATH = os.path.join(PROJECT_DIR, "query_log.csv")
_FIELDS = ["ts", "question", "latency_s", "total_tokens", "attempts", "n_sources"]


def log_query(question, latency_s, total_tokens, attempts, n_sources):
    try:
        is_new = not os.path.exists(LOG_PATH)
        with open(LOG_PATH, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_FIELDS)
            if is_new:
                w.writeheader()
            w.writerow({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "question": question[:120],
                "latency_s": round(latency_s, 2),
                "total_tokens": total_tokens,
                "attempts": attempts,
                "n_sources": n_sources,
            })
    except Exception:
        pass
