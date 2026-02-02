"""Add RSS feed and article tables

Revision ID: 001_rss_tables
Revises:
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_rss_tables'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create rss_feeds table
    op.create_table(
        'rss_feeds',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('feed_url', sa.String(500), unique=True, nullable=False),
        sa.Column('feed_type', sa.String(20), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true()),
        sa.Column('last_fetched', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('fetch_interval_hours', sa.Integer(), server_default='4'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Create articles table
    op.create_table(
        'articles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feed_id', sa.Integer(), sa.ForeignKey('rss_feeds.id', ondelete='CASCADE'), nullable=True),
        sa.Column('external_id', sa.String(500), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('author', sa.String(200), nullable=True),
        sa.Column('published_date', sa.DateTime(), nullable=True),
        sa.Column('fetched_date', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('is_summarized', sa.Boolean(), server_default=sa.false()),
        sa.Column('is_read', sa.Boolean(), server_default=sa.false()),
    )

    # Create article_summaries table
    op.create_table(
        'article_summaries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('article_id', sa.Integer(), sa.ForeignKey('articles.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('processing_time_sec', sa.Numeric(6, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # Create indexes
    op.create_index('ix_rss_feeds_is_active', 'rss_feeds', ['is_active'])
    op.create_index('ix_articles_feed_id', 'articles', ['feed_id'])
    op.create_index('ix_articles_url', 'articles', ['url'])
    op.create_index('ix_articles_fetched_date', 'articles', ['fetched_date'])
    op.create_index('ix_articles_is_summarized', 'articles', ['is_summarized'])


def downgrade() -> None:
    op.drop_index('ix_articles_is_summarized', table_name='articles')
    op.drop_index('ix_articles_fetched_date', table_name='articles')
    op.drop_index('ix_articles_url', table_name='articles')
    op.drop_index('ix_articles_feed_id', table_name='articles')
    op.drop_index('ix_rss_feeds_is_active', table_name='rss_feeds')
    op.drop_table('article_summaries')
    op.drop_table('articles')
    op.drop_table('rss_feeds')
