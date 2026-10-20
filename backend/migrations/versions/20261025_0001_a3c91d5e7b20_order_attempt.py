"""order attempt

Revision ID: a3c91d5e7b20
Revises: fe70cbab674f
Create Date: 2026-10-20 18:05:41.337120

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c91d5e7b20"
down_revision: str | None = "fe70cbab674f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bounties",
        sa.Column("order_attempt", sa.Integer(), server_default="0", nullable=False),
        schema="bounty",
    )
    # Rows created before this column already spent the legacy id `order-<id>`
    # (attempt 1); without this the next fund() would replay it.
    op.execute(
        "UPDATE bounty.bounties SET order_attempt = 1 WHERE order_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("bounties", "order_attempt", schema="bounty")
