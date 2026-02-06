"""Add push_subscriptions table for Web Push notifications.

Revision ID: 010_push_subscriptions
Revises: 009_user_profiles
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '010_push_subscriptions'
down_revision: Union[str, None] = '009_user_profiles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Push subscriptions for Web Push API (PWA notifications)
    op.create_table(
        'push_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column('endpoint', sa.String(500), unique=True, nullable=False),
        sa.Column('auth_key', sa.String(100), nullable=False),
        sa.Column('p256dh_key', sa.String(100), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('user_agent', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
    )

    # Index for endpoint lookup (unique constraint already creates index)
    op.create_index(
        'ix_push_subscriptions_is_active', 'push_subscriptions', ['is_active']
    )


def downgrade() -> None:
    op.drop_index('ix_push_subscriptions_is_active', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
