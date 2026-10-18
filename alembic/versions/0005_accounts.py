"""Local accounts and account verification messages."""

import sqlalchemy as sa

from alembic import op

revision = "0005_accounts"
down_revision = "0004_email_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("verification_hash", sa.String(64), nullable=True),
        sa.Column("verification_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_attempts", sa.Integer(), nullable=False),
        sa.Column("verification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.alter_column("email_outbox", "case_id", existing_type=sa.String(40), nullable=True)
    op.add_column("email_outbox", sa.Column("verification_code", sa.String(6), nullable=True))


def downgrade():
    # Account verification messages must be removed before restoring non-null case IDs.
    op.execute("DELETE FROM email_outbox WHERE case_id IS NULL")
    op.drop_column("email_outbox", "verification_code")
    op.alter_column("email_outbox", "case_id", existing_type=sa.String(40), nullable=False)
    op.drop_table("accounts")
