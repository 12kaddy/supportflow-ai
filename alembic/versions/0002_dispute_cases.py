"""Persist delivery evidence and dispute investigation snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0002_dispute_cases"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_evidence",
        sa.Column("order_id", sa.String(40), sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column("tracking_events", sa.JSON(), nullable=False),
        sa.Column("proof_status", sa.String(30), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
    )
    op.create_table(
        "dispute_cases",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("order_id", sa.String(40), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("investigation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dispute_cases_customer_id", "dispute_cases", ["customer_id"])


def downgrade():
    op.drop_index("ix_dispute_cases_customer_id", table_name="dispute_cases")
    op.drop_table("dispute_cases")
    op.drop_table("delivery_evidence")
