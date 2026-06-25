"""add lego_element_prices for multi-region PAB pricing

Revision ID: b2c3d4e5
Revises: a1b2c3d4
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5"
down_revision: Union[str, None] = "a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lego_element_prices",
        sa.Column("element_id", sa.BigInteger(), nullable=False),
        sa.Column("locale", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("price_formatted", sa.String(20), nullable=True),
        sa.Column("currency_code", sa.String(10), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["element_id"],
            ["lego_elements.element_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("element_id", "locale"),
    )
    op.create_index(
        "ix_lego_element_prices_locale",
        "lego_element_prices",
        ["locale"],
    )


def downgrade() -> None:
    op.drop_index("ix_lego_element_prices_locale", table_name="lego_element_prices")
    op.drop_table("lego_element_prices")
