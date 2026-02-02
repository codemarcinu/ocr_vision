"""Add transcription agent tables

Revision ID: 002_transcription_tables
Revises: 001_rss_tables
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


# revision identifiers, used by Alembic.
revision: str = '002_transcription_tables'
down_revision: Union[str, None] = '001_rss_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create transcription_jobs table
    op.create_table(
        'transcription_jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        # Source information
        sa.Column('source_type', sa.String(20), nullable=False),  # 'youtube', 'url', 'file'
        sa.Column('source_url', sa.String(1000), nullable=True),
        sa.Column('source_filename', sa.String(500), nullable=True),
        # Job metadata
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('channel_name', sa.String(200), nullable=True),
        sa.Column('thumbnail_url', sa.String(500), nullable=True),
        # Processing settings
        sa.Column('whisper_model', sa.String(50), nullable=False, server_default='medium'),
        sa.Column('language', sa.String(10), nullable=True),
        # Status tracking
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('progress_percent', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        # Temporary file paths (for cleanup)
        sa.Column('temp_audio_path', sa.String(500), nullable=True),
        sa.Column('temp_video_path', sa.String(500), nullable=True),
    )

    # Create transcriptions table
    op.create_table(
        'transcriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'job_id',
            UUID(as_uuid=True),
            sa.ForeignKey('transcription_jobs.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        # Content
        sa.Column('full_text', sa.Text(), nullable=False),
        sa.Column('segments', JSONB(), server_default='[]'),
        # Processing metadata
        sa.Column('detected_language', sa.String(10), nullable=True),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('processing_time_sec', sa.Numeric(8, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Create transcription_notes table
    op.create_table(
        'transcription_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'job_id',
            UUID(as_uuid=True),
            sa.ForeignKey('transcription_jobs.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        # Extracted knowledge
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('key_topics', ARRAY(sa.Text()), nullable=True),
        sa.Column('key_points', JSONB(), server_default='[]'),
        sa.Column('entities', ARRAY(sa.Text()), nullable=True),
        sa.Column('action_items', JSONB(), server_default='[]'),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('tags', ARRAY(sa.Text()), nullable=True),
        # Generated note path
        sa.Column('obsidian_file_path', sa.String(500), nullable=True),
        # Processing metadata
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('processing_time_sec', sa.Numeric(6, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Create indexes
    op.create_index('ix_transcription_jobs_status', 'transcription_jobs', ['status'])
    op.create_index('ix_transcription_jobs_source_url', 'transcription_jobs', ['source_url'])
    op.create_index('ix_transcription_jobs_created_at', 'transcription_jobs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_transcription_jobs_created_at', table_name='transcription_jobs')
    op.drop_index('ix_transcription_jobs_source_url', table_name='transcription_jobs')
    op.drop_index('ix_transcription_jobs_status', table_name='transcription_jobs')
    op.drop_table('transcription_notes')
    op.drop_table('transcriptions')
    op.drop_table('transcription_jobs')
