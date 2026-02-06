"""Add confidence_score column to receipts table.

Revision ID: 011_receipt_confidence_score
Revises: 010_push_subscriptions
Create Date: 2026-02-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '011_receipt_confidence_score'
down_revision: Union[str, None] = '010_push_subscriptions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('receipts', sa.Column('confidence_score', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('receipts', 'confidence_score')
