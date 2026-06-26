"""include instrument symbol in market file uniqueness

Revision ID: 20260625_0006
Revises: 20260624_0005
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260625_0006"
down_revision: Union[str, Sequence[str], None] = "20260624_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_market_data_file_version", "market_data_files", type_="unique")
    op.create_unique_constraint(
        "uq_market_data_file_version",
        "market_data_files",
        [
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
            "start_time",
            "end_time",
            "data_version",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_market_data_file_version", "market_data_files", type_="unique")
    op.create_unique_constraint(
        "uq_market_data_file_version",
        "market_data_files",
        [
            "provider",
            "data_type",
            "contract_code",
            "period",
            "start_time",
            "end_time",
            "data_version",
        ],
    )

