from __future__ import annotations

from app.db.session import SessionLocal
from app.signal.scanner import SignalScanner


def run_signal_scan_task(task_id: int) -> dict:
    with SessionLocal() as session:
        return SignalScanner(session).run(task_id)
