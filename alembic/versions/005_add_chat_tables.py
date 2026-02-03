"""Add chat tables for multi-turn conversations.

Revision ID: 005_chat_tables
Revises: 004_rag_embeddings
Create Date: 2026-02-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_chat_tables'
down_revision: Union[str, None] = '004_rag_embeddings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Chat sessions
    op.create_table(
        'chat_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='web'),
        sa.Column('telegram_chat_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )
    op.create_index('ix_chat_sessions_telegram', 'chat_sessions', ['telegram_chat_id'])
    op.create_index('ix_chat_sessions_active', 'chat_sessions', ['is_active', 'created_at'])

    # Chat messages
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sources', postgresql.JSONB(), server_default='[]'),
        sa.Column('search_type', sa.String(10), nullable=True),
        sa.Column('search_query', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('processing_time_sec', sa.Numeric(6, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )
    op.create_index('ix_chat_messages_session', 'chat_messages', ['session_id'])
    op.create_index(
        'ix_chat_messages_session_time', 'chat_messages',
        ['session_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_table('chat_messages')
    op.drop_table('chat_sessions')
