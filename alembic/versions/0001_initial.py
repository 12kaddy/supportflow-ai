"""Initial orders and refunds tables."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("days_since_delivery", sa.Integer(), nullable=True),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "order_id", sa.String(40), sa.ForeignKey("orders.id"), nullable=False, unique=True
        ),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("refunds")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_table("orders")
