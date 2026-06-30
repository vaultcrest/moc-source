"""add scraper_runs table

Revision ID: f6a7b8c9
Revises: e5f6a7b8
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9"
down_revision: Union[str, None] = "e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scraper_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locales_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prices_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraper_runs_finished_at", "scraper_runs", ["finished_at"])


def downgrade() -> None:
    op.drop_index("ix_scraper_runs_finished_at", table_name="scraper_runs")
    op.drop_table("scraper_runs")
