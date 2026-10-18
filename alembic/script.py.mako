"""${message}"""
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
from alembic import op
import sqlalchemy as sa
${upgrades if upgrades else "def upgrade(): pass"}
${downgrades if downgrades else "def downgrade(): pass"}
