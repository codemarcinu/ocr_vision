"""Repository for document embeddings (RAG)."""

import logging
from typing import List, Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentEmbedding
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class EmbeddingRepository(BaseRepository[DocumentEmbedding]):
    """Repository for managing document embeddings."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, DocumentEmbedding)

    async def search_by_vector(
        self,
        embedding: list[float],
        limit: int = 5,
        content_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Search for similar documents using cosine distance.

        Returns list of dicts with: id, content_type, content_id, chunk_index,
        text_chunk, metadata, distance, score.
        """
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        where_clause = ""
        if content_types:
            types_str = ",".join(f"'{t}'" for t in content_types)
            where_clause = f"WHERE content_type IN ({types_str})"

        query = text(f"""
            SELECT
                id,
                content_type,
                content_id,
                chunk_index,
                text_chunk,
                metadata,
                embedding <=> :query_embedding AS distance
            FROM document_embeddings
            {where_clause}
            ORDER BY embedding <=> :query_embedding
            LIMIT :limit
        """)

        result = await self.session.execute(
            query,
            {"query_embedding": embedding_str, "limit": limit},
        )

        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "content_type": row.content_type,
                "content_id": row.content_id,
                "chunk_index": row.chunk_index,
                "text_chunk": row.text_chunk,
                "metadata": row.metadata or {},
                "distance": float(row.distance),
                "score": round(1.0 - float(row.distance), 4),
            }
            for row in rows
        ]

    async def search_by_keyword(
        self,
        query: str,
        limit: int = 5,
        content_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Fallback keyword search using pg_trgm similarity."""
        where_clause = ""
        if content_types:
            types_str = ",".join(f"'{t}'" for t in content_types)
            where_clause = f"AND content_type IN ({types_str})"

        sql = text(f"""
            SELECT
                id,
                content_type,
                content_id,
                chunk_index,
                text_chunk,
                metadata,
                similarity(text_chunk, :query) AS sim_score
            FROM document_embeddings
            WHERE text_chunk ILIKE :pattern {where_clause}
            ORDER BY sim_score DESC
            LIMIT :limit
        """)

        result = await self.session.execute(
            sql,
            {"query": query, "pattern": f"%{query}%", "limit": limit},
        )

        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "content_type": row.content_type,
                "content_id": row.content_id,
                "chunk_index": row.chunk_index,
                "text_chunk": row.text_chunk,
                "metadata": row.metadata or {},
                "distance": 1.0 - float(row.sim_score),
                "score": round(float(row.sim_score), 4),
            }
            for row in rows
        ]

    async def get_by_content(
        self,
        content_type: str,
        content_id: str,
    ) -> List[DocumentEmbedding]:
        """Get all embeddings for a specific content item."""
        stmt = (
            select(DocumentEmbedding)
            .where(DocumentEmbedding.content_type == content_type)
            .where(DocumentEmbedding.content_id == content_id)
            .order_by(DocumentEmbedding.chunk_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_content(
        self,
        content_type: str,
        content_id: str,
    ) -> int:
        """Delete all embeddings for a specific content item."""
        stmt = (
            delete(DocumentEmbedding)
            .where(DocumentEmbedding.content_type == content_type)
            .where(DocumentEmbedding.content_id == content_id)
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def get_stats(self) -> dict:
        """Get embedding statistics by content type."""
        stmt = (
            select(
                DocumentEmbedding.content_type,
                func.count(DocumentEmbedding.id).label("chunk_count"),
                func.count(func.distinct(DocumentEmbedding.content_id)).label("document_count"),
            )
            .group_by(DocumentEmbedding.content_type)
        )
        result = await self.session.execute(stmt)
        rows = result.fetchall()

        by_type = {}
        total_chunks = 0
        total_documents = 0

        for row in rows:
            by_type[row.content_type] = {
                "chunks": row.chunk_count,
                "documents": row.document_count,
            }
            total_chunks += row.chunk_count
            total_documents += row.document_count

        return {
            "total_chunks": total_chunks,
            "total_documents": total_documents,
            "by_type": by_type,
        }
