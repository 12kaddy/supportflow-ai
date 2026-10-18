"""Reviewer decisions, simulated refunds, and audit events."""

import sqlalchemy as sa

from alembic import op

revision = "0003_resolutions"
down_revision = "0002_dispute_cases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_reviews",
        sa.Column("case_id", sa.String(40), sa.ForeignKey("dispute_cases.id"), primary_key=True),
        sa.Column("reviewer_id", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "simulated_refunds",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "order_id", sa.String(40), sa.ForeignKey("orders.id"), nullable=False, unique=True
        ),
        sa.Column(
            "case_id", sa.String(40), sa.ForeignKey("dispute_cases.id"), nullable=False, unique=True
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "case_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(40), sa.ForeignKey("dispute_cases.id"), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])
    # Preserve the original snapshot for cases created before audit support existed.
    cases = sa.table(
        "dispute_cases",
        sa.column("id"),
        sa.column("customer_id"),
        sa.column("investigation", sa.JSON()),
        sa.column("created_at"),
    )
    events = sa.table(
        "case_events",
        sa.column("case_id"),
        sa.column("actor"),
        sa.column("kind"),
        sa.column("details", sa.JSON()),
        sa.column("created_at"),
    )
    op.execute(
        events.insert().from_select(
            ["case_id", "actor", "kind", "details", "created_at"],
            sa.select(
                cases.c.id,
                cases.c.customer_id,
                sa.literal("investigation_imported"),
                cases.c.investigation,
                cases.c.created_at,
            ),
        )
    )


def downgrade():
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
    op.drop_table("simulated_refunds")
    op.drop_table("case_reviews")
