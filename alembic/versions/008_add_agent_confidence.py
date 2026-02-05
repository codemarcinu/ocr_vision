"""Add confidence column to agent_call_logs.

Revision ID: 008_agent_confidence
Revises: 007_agent_call_logs
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008_agent_confidence'
down_revision: Union[str, None] = '007_agent_call_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add confidence column (LLM self-reported confidence score 0.0-1.0)
    op.add_column(
        'agent_call_logs',
        sa.Column('confidence', sa.Float(), nullable=True)
    )

    # Index for querying by confidence (useful for analyzing low-confidence calls)
    op.create_index(
        'ix_agent_call_logs_confidence', 'agent_call_logs', ['confidence']
    )


def downgrade() -> None:
    op.drop_index('ix_agent_call_logs_confidence', table_name='agent_call_logs')
    op.drop_column('agent_call_logs', 'confidence')
