from __future__ import annotations

from app.backtest.runner import BacktestTaskRunner
from app.db.session import SessionLocal
from app.services.batch_backtest import BatchBacktestRunner


def run_backtest_task(task_id: int) -> dict:
    with SessionLocal() as session:
        return BacktestTaskRunner(session).run(task_id)


def run_batch_backtest_task(task_id: int) -> dict:
    with SessionLocal() as session:
        return BatchBacktestRunner(session).run(task_id)
