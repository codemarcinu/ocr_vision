"""SQLAlchemy ORM models for Second Brain."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Category(Base):
    """Product category."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    products: Mapped[List["Product"]] = relationship(back_populates="category")
    receipt_items: Mapped[List["ReceiptItem"]] = relationship(back_populates="category")
    pantry_items: Mapped[List["PantryItem"]] = relationship(back_populates="category")


class Store(Base):
    """Store (sklep)."""
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    aliases: Mapped[List["StoreAlias"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    shortcuts: Mapped[List["ProductShortcut"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    receipts: Mapped[List["Receipt"]] = relationship(back_populates="store")
    pantry_items: Mapped[List["PantryItem"]] = relationship(back_populates="store")
    price_history: Mapped[List["PriceHistory"]] = relationship(back_populates="store")
    unmatched_products: Mapped[List["UnmatchedProduct"]] = relationship(
        back_populates="store"
    )
    review_corrections: Mapped[List["ReviewCorrection"]] = relationship(
        back_populates="store"
    )


class StoreAlias(Base):
    """Store alias for OCR matching."""
    __tablename__ = "store_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # Relationships
    store: Mapped["Store"] = relationship(back_populates="aliases")


class Product(Base):
    """Normalized product from dictionary."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    typical_price_pln: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    category: Mapped[Optional["Category"]] = relationship(back_populates="products")
    variants: Mapped[List["ProductVariant"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    receipt_items: Mapped[List["ReceiptItem"]] = relationship(back_populates="product")
    pantry_items: Mapped[List["PantryItem"]] = relationship(back_populates="product")
    price_history: Mapped[List["PriceHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    learned_from: Mapped[List["UnmatchedProduct"]] = relationship(
        back_populates="learned_product"
    )


class ProductVariant(Base):
    """Raw product name variant (as seen in OCR)."""
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    raw_name: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="variants")


class ProductShortcut(Base):
    """Store-specific product abbreviation."""
    __tablename__ = "product_shortcuts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    shortcut: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    store: Mapped["Store"] = relationship(back_populates="shortcuts")


class Receipt(Base):
    """Receipt (paragon)."""
    __tablename__ = "receipts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True
    )
    store_raw: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    total_ocr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    total_calculated: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    total_final: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    store: Mapped[Optional["Store"]] = relationship(back_populates="receipts")
    items: Mapped[List["ReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )
    price_history: Mapped[List["PriceHistory"]] = relationship(back_populates="receipt")
    corrections: Mapped[List["ReviewCorrection"]] = relationship(
        back_populates="receipt"
    )


class ReceiptItem(Base):
    """Item from a receipt."""
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    name_raw: Mapped[str] = mapped_column(String(300), nullable=False)
    name_normalized: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    price_final: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_original: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    discount_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    discount_details: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    warning: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    match_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    item_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Relationships
    receipt: Mapped["Receipt"] = relationship(back_populates="items")
    product: Mapped[Optional["Product"]] = relationship(back_populates="receipt_items")
    category: Mapped[Optional["Category"]] = relationship(back_populates="receipt_items")
    pantry_items: Mapped[List["PantryItem"]] = relationship(back_populates="receipt_item")


class PantryItem(Base):
    """Item in pantry (spiżarnia)."""
    __tablename__ = "pantry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("receipt_items.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True
    )
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1.0"))
    is_consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    receipt_item: Mapped[Optional["ReceiptItem"]] = relationship(
        back_populates="pantry_items"
    )
    product: Mapped[Optional["Product"]] = relationship(back_populates="pantry_items")
    category: Mapped[Optional["Category"]] = relationship(back_populates="pantry_items")
    store: Mapped[Optional["Store"]] = relationship(back_populates="pantry_items")


class PriceHistory(Base):
    """Price history for analytics."""
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    receipt_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True
    )
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="price_history")
    store: Mapped[Optional["Store"]] = relationship(back_populates="price_history")
    receipt: Mapped[Optional["Receipt"]] = relationship(back_populates="price_history")


class UnmatchedProduct(Base):
    """Product that couldn't be matched (for learning)."""
    __tablename__ = "unmatched_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_name: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_name_normalized: Mapped[Optional[str]] = mapped_column(
        String(300), unique=True, nullable=True
    )
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True
    )
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    is_learned: Mapped[bool] = mapped_column(Boolean, default=False)
    learned_product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    store: Mapped[Optional["Store"]] = relationship(back_populates="unmatched_products")
    learned_product: Mapped[Optional["Product"]] = relationship(
        back_populates="learned_from"
    )


class ReviewCorrection(Base):
    """Correction made during human review."""
    __tablename__ = "review_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True
    )
    original_total: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    corrected_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    correction_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'approved', 'calculated', 'manual', 'rejected'
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True
    )
    product_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    receipt: Mapped[Optional["Receipt"]] = relationship(back_populates="corrections")
    store: Mapped[Optional["Store"]] = relationship(back_populates="review_corrections")


# =============================================================================
# RSS/Web Summarizer Models
# =============================================================================


class RssFeed(Base):
    """RSS/Atom feed subscription."""
    __tablename__ = "rss_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    feed_url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    feed_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # 'rss', 'atom', 'webpage'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    fetch_interval_hours: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    articles: Mapped[List["Article"]] = relationship(
        back_populates="feed", cascade="all, delete-orphan"
    )


class Article(Base):
    """Article fetched from RSS feed or scraped URL."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rss_feeds.id", ondelete="CASCADE"), nullable=True
    )
    external_id: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )  # guid from feed
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    published_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fetched_date: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    is_summarized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    feed: Mapped[Optional["RssFeed"]] = relationship(back_populates="articles")
    summary: Mapped[Optional["ArticleSummary"]] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )


class ArticleSummary(Base):
    """LLM-generated summary of an article."""
    __tablename__ = "article_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    processing_time_sec: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    article: Mapped["Article"] = relationship(back_populates="summary")


# =============================================================================
# Transcription Agent Models
# =============================================================================


class TranscriptionJob(Base):
    """Transcription job (audio/video to text)."""
    __tablename__ = "transcription_jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Source information
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'youtube', 'url', 'file'
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Job metadata
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Processing settings
    whisper_model: Mapped[str] = mapped_column(
        String(50), nullable=False, default="medium"
    )  # 'tiny', 'base', 'small', 'medium', 'large-v3'
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )  # 'pending', 'downloading', 'transcribing', 'extracting', 'completed', 'failed'
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Temporary file paths (for cleanup)
    temp_audio_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    temp_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    transcription: Mapped[Optional["Transcription"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    note: Mapped[Optional["TranscriptionNote"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


class Transcription(Base):
    """Transcription content with segments."""
    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Full transcription text
    full_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Segments with timestamps (stored as JSONB array)
    # Each segment: {"start": 0.0, "end": 2.5, "text": "Hello world"}
    segments: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Processing metadata
    detected_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_time_sec: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    job: Mapped["TranscriptionJob"] = relationship(back_populates="transcription")


class TranscriptionNote(Base):
    """Extracted knowledge and generated Obsidian note."""
    __tablename__ = "transcription_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Extracted knowledge
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_topics: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    key_points: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # bullet points
    entities: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )  # people, companies, etc.
    action_items: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # tasks mentioned
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)

    # Generated note path
    obsidian_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Processing metadata
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    processing_time_sec: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    job: Mapped["TranscriptionJob"] = relationship(back_populates="note")


# =============================================================================
# Personal Notes
# =============================================================================

class Note(Base):
    """Personal note."""

    __tablename__ = "notes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    source_refs: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # [{type: "receipt", id: "..."}, ...]
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


# =============================================================================
# Bookmarks / Read Later
# =============================================================================

class Bookmark(Base):
    """URL bookmark / read later."""

    __tablename__ = "bookmarks"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, read, archived
    priority: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(
        String(20), default="telegram"
    )  # telegram, api
    article_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("articles.id"), nullable=True
    )
    transcription_job_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("transcription_jobs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
