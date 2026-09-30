"""Keep the evidence shown with an answer across page reloads."""
from alembic import op
import sqlalchemy as sa
revision = "c81e26a40002"
down_revision = "c81e26a40001"
branch_labels = depends_on = None

def upgrade():
    op.add_column("chat_messages", sa.Column("sources_json", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("chat_messages", "sources_json")
