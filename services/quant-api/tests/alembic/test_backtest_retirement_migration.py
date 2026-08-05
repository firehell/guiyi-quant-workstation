from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


PARENT_REVISION = "20260803_0032"
RETIREMENT_REVISION = "20260805_0033"
QUANT_API_ROOT = Path(__file__).resolve().parents[2]
RETIREMENT_SOURCE = (
    QUANT_API_ROOT / "alembic" / "versions" / "20260805_0033_retire_backtest.py"
)


def test_backtest_retirement_is_the_current_alembic_head() -> None:
    """The destructive retirement must be an explicit new head, never a rewritten history row."""

    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [RETIREMENT_REVISION]
    revision = scripts.get_revision(RETIREMENT_REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT_REVISION


def test_backtest_retirement_sql_deletes_only_scoped_legacy_rows() -> None:
    """Shared Task06 and non-backtest review/signal rows must survive the drop."""

    source = RETIREMENT_SOURCE.read_text(encoding="utf-8")

    assert "source_type = 'backtest_trade'" in source
    assert "htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f" in source
    assert "htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5" in source
    assert "htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee" in source
    assert "enterprise_wechat:signal_event:4" in source
    assert "DELETE FROM signal_notifications;" not in source
    assert "DELETE FROM signal_events;" not in source
    assert "DELETE FROM strategy_signals;" not in source
    assert "SELECT count(*) INTO review_count FROM review_notes;" not in source
    assert "SELECT count(*) INTO signal_count FROM strategy_signals;" not in source
    assert "main_contract_maps" not in source
    assert "market_data_files" not in source


def test_backtest_retirement_sql_requires_exact_identity_before_delete() -> None:
    """The migration is fail-closed and deletes its target types in dependency order."""

    source = RETIREMENT_SOURCE.read_text(encoding="utf-8")

    assert "legacy S6 retirement identity mismatch" in source
    assert "event.event_key = 'signal_created:' || signal.dedupe_key || ':created'" in source
    assert "event.decision_id IS NULL" in source
    assert "event.source_mode = 'live_realtime_repainting'" in source
    assert "notification.event_id" in source
    assert "notification.signal_id" in source
    assert "review_count = 7 AND notification_count = 1 AND event_count = 3" in source
    assert "signal_count = 3 AND task_count = 23 AND report_count = 15" in source
    assert "trade_count = 4361 AND order_count = 4225" in source

    review_delete = source.index("DELETE FROM review_notes WHERE source_type = 'backtest_trade'")
    notification_delete = source.index("DELETE FROM signal_notifications")
    event_delete = source.index("DELETE FROM signal_events")
    signal_delete = source.index("DELETE FROM strategy_signals")
    task_delete = source.index("DELETE FROM backtest_tasks")
    assert review_delete < notification_delete < event_delete < signal_delete < task_delete

    assert source.index('op.drop_table("backtest_orders")') < source.index(
        'op.drop_table("backtest_trades")'
    ) < source.index('op.drop_table("backtest_reports")') < source.index(
        'op.drop_table("backtest_tasks")'
    )
