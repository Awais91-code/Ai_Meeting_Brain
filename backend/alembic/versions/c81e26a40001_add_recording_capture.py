"""Persist recording inputs and deduplicate provider deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "c81e26a40001"
down_revision = "9f2c7a1b3d4e"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("meetings") as batch:
        batch.add_column(sa.Column("source_id", sa.String(255), nullable=True))
        batch.add_column(sa.Column("meeting_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("recording_path", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_meetings_source_id", ["source_id"])


def downgrade():
    with op.batch_alter_table("meetings") as batch:
        batch.drop_constraint("uq_meetings_source_id", type_="unique")
        for column in ("recording_path", "meeting_url", "source_id"):
            batch.drop_column(column)
