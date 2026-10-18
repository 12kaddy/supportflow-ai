"""Customer email preferences and transactional outbox."""

import sqlalchemy as sa

from alembic import op

revision = "0004_email_notifications"
down_revision = "0003_resolutions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_subscriptions",
        sa.Column("case_id", sa.String(40), sa.ForeignKey("dispute_cases.id"), primary_key=True),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("delivery_mode", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("case_id", sa.String(40), sa.ForeignKey("dispute_cases.id"), nullable=False),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("delivery_mode", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_type", sa.String(100), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("case_id", "kind", name="uq_email_case_kind"),
    )
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])


def downgrade():
    op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_table("email_subscriptions")
