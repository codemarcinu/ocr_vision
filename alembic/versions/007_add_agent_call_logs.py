"""Add agent call logs table for tool-calling analytics.

Revision ID: 007_agent_call_logs
Revises: 006_chat_telegram_bigint
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '007_agent_call_logs'
down_revision: Union[str, None] = '006_chat_telegram_bigint'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agent call logs
    op.create_table(
        'agent_call_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        # Input
        sa.Column('user_input', sa.Text(), nullable=False),
        sa.Column('sanitized_input', sa.Text(), nullable=True),
        # LLM
        sa.Column('model_used', sa.String(100), nullable=False),
        sa.Column('raw_response', sa.Text(), nullable=True),
        # Parsed result
        sa.Column('parsed_tool', sa.String(50), nullable=True),
        sa.Column('parsed_arguments', postgresql.JSONB(), nullable=True),
        # Validation
        sa.Column('validation_success', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('validation_error', sa.Text(), nullable=True),
        # Execution
        sa.Column('execution_success', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('execution_error', sa.Text(), nullable=True),
        # Metadata
        sa.Column('retry_count', sa.Integer(), server_default=sa.text('0')),
        sa.Column('total_time_ms', sa.Integer(), server_default=sa.text('0')),
        sa.Column('injection_risk', sa.String(10), server_default="'none'"),
        # Source
        sa.Column('source', sa.String(20), server_default="'api'"),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
        # Timestamp
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Indexes for common queries
    op.create_index(
        'ix_agent_call_logs_created', 'agent_call_logs', ['created_at']
    )
    op.create_index(
        'ix_agent_call_logs_tool', 'agent_call_logs', ['parsed_tool']
    )
    op.create_index(
        'ix_agent_call_logs_success', 'agent_call_logs',
        ['execution_success', 'created_at']
    )
    op.create_index(
        'ix_agent_call_logs_injection', 'agent_call_logs',
        ['injection_risk', 'created_at']
    )
    op.create_index(
        'ix_agent_call_logs_source', 'agent_call_logs', ['source']
    )


def downgrade() -> None:
    op.drop_table('agent_call_logs')
