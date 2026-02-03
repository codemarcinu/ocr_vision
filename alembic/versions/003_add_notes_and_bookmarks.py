"""Add notes and bookmarks tables

Revision ID: 003_notes_and_bookmarks
Revises: 002_transcription_tables
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


# revision identifiers, used by Alembic.
revision: str = '003_notes_and_bookmarks'
down_revision: Union[str, None] = '002_transcription_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create notes table
    op.create_table(
        'notes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('tags', ARRAY(sa.Text()), nullable=True),
        sa.Column('source_refs', JSONB(), server_default='[]'),
        sa.Column('is_archived', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Create bookmarks table
    op.create_table(
        'bookmarks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('url', sa.String(2000), nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', ARRAY(sa.Text()), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('priority', sa.Integer(), server_default='0'),
        sa.Column('source', sa.String(20), server_default='telegram'),
        sa.Column(
            'article_id',
            sa.Integer(),
            sa.ForeignKey('articles.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'transcription_job_id',
            UUID(as_uuid=True),
            sa.ForeignKey('transcription_jobs.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
    )

    # Create indexes
    op.create_index('ix_notes_created_at', 'notes', ['created_at'])
    op.create_index('ix_notes_category', 'notes', ['category'])
    op.create_index('ix_notes_is_archived', 'notes', ['is_archived'])
    op.create_index('ix_bookmarks_status', 'bookmarks', ['status'])
    op.create_index('ix_bookmarks_url', 'bookmarks', ['url'])
    op.create_index('ix_bookmarks_created_at', 'bookmarks', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_bookmarks_created_at', table_name='bookmarks')
    op.drop_index('ix_bookmarks_url', table_name='bookmarks')
    op.drop_index('ix_bookmarks_status', table_name='bookmarks')
    op.drop_index('ix_notes_is_archived', table_name='notes')
    op.drop_index('ix_notes_category', table_name='notes')
    op.drop_index('ix_notes_created_at', table_name='notes')
    op.drop_table('bookmarks')
    op.drop_table('notes')
