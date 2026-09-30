"""add is_active, action_items, processing_error, notifications, participant unique constraint

Revision ID: 9f2c7a1b3d4e
Revises: 6bbb4c0a2d92
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f2c7a1b3d4e'
down_revision: Union[str, Sequence[str], None] = '6bbb4c0a2d92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # --- users: disable/enable accounts (Phase 12) ---
    op.add_column(
        'users',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # --- meetings: structured action items + failure reason (Phase 8/9) ---
    op.add_column(
        'meetings',
        sa.Column('action_items', sa.Text(), nullable=True),
    )
    op.add_column(
        'meetings',
        sa.Column('processing_error', sa.Text(), nullable=True),
    )
    op.create_index(
        op.f('ix_meetings_status'), 'meetings', ['status'], unique=False
    )

    # --- meeting_participants: enforce "no duplicate assignment" at the
    #     DB level too, not only in application code (Phase 16).
    #     batch_alter_table works on both SQLite (table rebuild) and
    #     PostgreSQL (plain ALTER TABLE) without maintaining two code
    #     paths. ---
    with op.batch_alter_table('meeting_participants') as batch_op:
        batch_op.create_unique_constraint(
            'uq_meeting_participant',
            ['meeting_id', 'user_id'],
        )

    # --- notifications table (Phase 14) ---
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('meeting_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column(
            'is_read',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['meeting_id'], ['meetings.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_notifications_id'), 'notifications', ['id'], unique=False
    )
    op.create_index(
        op.f('ix_notifications_user_id'),
        'notifications',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_notifications_meeting_id'),
        'notifications',
        ['meeting_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(op.f('ix_notifications_meeting_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_table('notifications')

    with op.batch_alter_table('meeting_participants') as batch_op:
        batch_op.drop_constraint('uq_meeting_participant', type_='unique')

    op.drop_index(op.f('ix_meetings_status'), table_name='meetings')
    op.drop_column('meetings', 'processing_error')
    op.drop_column('meetings', 'action_items')

    op.drop_column('users', 'is_active')
