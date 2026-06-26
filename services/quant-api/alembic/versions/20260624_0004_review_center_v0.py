"""review center v0

Revision ID: 20260624_0004
Revises: 20260624_0003
Create Date: 2026-06-24

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260624_0004"
down_revision: Union[str, Sequence[str], None] = "20260624_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TAG_ROWS = [
    ("mistake", "追价", 10),
    ("mistake", "震荡区交易", 20),
    ("mistake", "逆势", 30),
    ("mistake", "过早进场", 40),
    ("mistake", "止损过大", 50),
    ("mistake", "止损过小", 60),
    ("mistake", "盈亏比不足", 70),
    ("mistake", "未按信号执行", 80),
    ("mistake", "看到信号没做", 90),
    ("mistake", "人工提前平仓", 100),
    ("market_phase", "趋势启动", 10),
    ("market_phase", "趋势中继", 20),
    ("market_phase", "震荡假突破", 30),
    ("market_phase", "趋势衰竭", 40),
    ("market_phase", "无效样本", 50),
    ("entry_rule", "EMA21方向过滤", 10),
    ("entry_rule", "MACD零轴附近交叉", 20),
    ("entry_rule", "成交量放大", 30),
    ("entry_rule", "多周期共振", 40),
    ("entry_rule", "带量突破试单", 50),
    ("exit_rule", "破EMA21", 10),
    ("exit_rule", "破上一根K高低点", 20),
    ("exit_rule", "止损", 30),
    ("exit_rule", "止盈", 40),
    ("exit_rule", "反向信号", 50),
    ("emotion", "犹豫", 10),
    ("emotion", "冲动", 20),
    ("emotion", "恐惧", 30),
    ("emotion", "贪婪", 40),
]


def upgrade() -> None:
    op.create_table(
        "review_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("contract", sa.String(length=64), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("strategy_name", sa.String(length=64), nullable=True),
        sa.Column("strategy_version", sa.String(length=32), nullable=True),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("net_pnl", sa.Float(), nullable=True),
        sa.Column("entry_reason", sa.Text(), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("market_phase", sa.String(length=32), nullable=True),
        sa.Column("is_system_compliant", sa.Boolean(), nullable=True),
        sa.Column("mistake_tags", sa.JSON(), nullable=False),
        sa.Column("rule_tags", sa.JSON(), nullable=False),
        sa.Column("emotion_tags", sa.JSON(), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=True),
        sa.Column("screenshot_paths", sa.JSON(), nullable=False),
        sa.Column("kline_focus_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kline_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kline_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_score", sa.Integer(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_status", sa.String(length=32), nullable=False),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_type", "source_id", name="uq_review_source"),
    )
    for name, columns in [
        ("ix_review_notes_source_type", ["source_type"]),
        ("ix_review_notes_source_id", ["source_id"]),
        ("ix_review_notes_symbol", ["symbol"]),
        ("ix_review_notes_contract", ["contract"]),
        ("ix_review_notes_period", ["period"]),
        ("ix_review_notes_direction", ["direction"]),
        ("ix_review_notes_strategy_name", ["strategy_name"]),
        ("ix_review_notes_strategy_version", ["strategy_version"]),
        ("ix_review_notes_open_time", ["open_time"]),
        ("ix_review_notes_close_time", ["close_time"]),
        ("ix_review_notes_net_pnl", ["net_pnl"]),
        ("ix_review_notes_market_phase", ["market_phase"]),
        ("ix_review_notes_is_system_compliant", ["is_system_compliant"]),
        ("ix_review_notes_ai_status", ["ai_status"]),
    ]:
        op.create_index(name, "review_notes", columns)

    op.create_table(
        "review_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tag_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tag_type", "name", name="uq_review_tag_type_name"),
    )
    op.create_index("ix_review_tags_tag_type", "review_tags", ["tag_type"])
    op.create_index("ix_review_tags_name", "review_tags", ["name"])
    op.create_index("ix_review_tags_is_active", "review_tags", ["is_active"])

    op.create_table(
        "review_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_attachments_review_id", "review_attachments", ["review_id"])
    op.create_index("ix_review_attachments_file_type", "review_attachments", ["file_type"])
    op.create_index("ix_review_attachments_created_at", "review_attachments", ["created_at"])

    tags = sa.table(
        "review_tags",
        sa.column("tag_type", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        tags,
        [
            {
                "tag_type": tag_type,
                "name": name,
                "description": None,
                "sort_order": sort_order,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for tag_type, name, sort_order in TAG_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_table("review_attachments")
    op.drop_table("review_tags")
    op.drop_table("review_notes")
