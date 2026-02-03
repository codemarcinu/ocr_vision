"""Change chat_sessions.telegram_chat_id from INTEGER to BIGINT.

Telegram chat IDs can exceed int32 range (max 2,147,483,647).

Revision ID: 006_chat_telegram_bigint
Revises: 005_chat_tables
Create Date: 2026-02-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_chat_telegram_bigint'
down_revision: Union[str, None] = '005_chat_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'chat_sessions',
        'telegram_chat_id',
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'chat_sessions',
        'telegram_chat_id',
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
