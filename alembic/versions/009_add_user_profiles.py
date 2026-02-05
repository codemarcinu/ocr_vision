"""Add user_profiles table for personalization.

Revision ID: 009_user_profiles
Revises: 008_agent_confidence
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '009_user_profiles'
down_revision: Union[str, None] = '008_agent_confidence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User profiles for personalization
    op.create_table(
        'user_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column('telegram_user_id', sa.BigInteger(), unique=True, nullable=True),
        # Preferences
        sa.Column('default_city', sa.String(100), server_default="'Kraków'"),
        sa.Column('timezone', sa.String(50), server_default="'Europe/Warsaw'"),
        sa.Column('preferred_language', sa.String(10), server_default="'pl'"),
        sa.Column('favorite_stores', postgresql.ARRAY(sa.Text()), nullable=True),
        # Statistics for personalization
        sa.Column('most_used_tools', postgresql.JSONB(), server_default='{}'),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.current_timestamp(),
                  onupdate=sa.func.current_timestamp()),
    )

    # Index for Telegram user lookup
    op.create_index(
        'ix_user_profiles_telegram_id', 'user_profiles', ['telegram_user_id'],
        unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_user_profiles_telegram_id', table_name='user_profiles')
    op.drop_table('user_profiles')
