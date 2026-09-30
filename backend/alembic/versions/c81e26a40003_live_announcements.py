"""Live invitations without creating empty meeting records."""
from alembic import op
import sqlalchemy as sa

revision = "c81e26a40003"
down_revision = "c81e26a40002"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("notifications") as batch:
        batch.alter_column("meeting_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("live_session_id", sa.String(36), nullable=True))
        batch.create_index("ix_notifications_live_session_id", ["live_session_id"])
        batch.create_unique_constraint("uq_notification_live_user", ["user_id", "live_session_id"])


def downgrade():
    op.execute("DELETE FROM notifications WHERE meeting_id IS NULL")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("uq_notification_live_user", type_="unique")
        batch.drop_index("ix_notifications_live_session_id")
        batch.drop_column("live_session_id")
        batch.alter_column("meeting_id", existing_type=sa.Integer(), nullable=False)
