"""Add RAG document embeddings table

Revision ID: 004_rag_embeddings
Revises: 003_notes_and_bookmarks
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '004_rag_embeddings'
down_revision: Union[str, None] = '003_notes_and_bookmarks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_embeddings table
    op.create_table(
        'document_embeddings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('content_type', sa.String(20), nullable=False),
        sa.Column('content_id', sa.String(36), nullable=False),
        sa.Column('chunk_index', sa.Integer(), server_default='0'),
        sa.Column('text_chunk', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(768), nullable=False),
        sa.Column('metadata', sa.dialects.postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )

    # B-tree index for content lookup and deletion
    op.create_index(
        'ix_embeddings_content',
        'document_embeddings',
        ['content_type', 'content_id'],
    )

    # B-tree index for filtered searches by type
    op.create_index(
        'ix_embeddings_type',
        'document_embeddings',
        ['content_type'],
    )

    # HNSW vector index for cosine similarity search
    # HNSW does not require training data (unlike IVFFlat)
    op.execute("""
        CREATE INDEX ix_embeddings_vector
        ON document_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # GIN trigram index for keyword fallback search
    op.execute("""
        CREATE INDEX ix_embeddings_text_trgm
        ON document_embeddings
        USING gin (text_chunk gin_trgm_ops)
    """)


def downgrade() -> None:
    op.drop_table('document_embeddings')
