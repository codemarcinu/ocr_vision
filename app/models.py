"""Pydantic models for Second Brain."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DiscountDetail(BaseModel):
    """Details of a single discount applied to a product."""
    typ: str = Field(..., description="Discount type: 'kwotowy' (amount) or 'procentowy' (percentage)")
    wartosc: float = Field(..., description="Discount value (amount in PLN or percentage)")
    opis: Optional[str] = Field(None, description="Discount description (e.g., 'Rabat', 'Promocja')")


class Product(BaseModel):
    """Single product from receipt."""

    nazwa: str = Field(..., description="Product name")
    cena: float = Field(..., description="Product price in PLN (final price after discount)")
    kategoria: Optional[str] = Field(None, description="Product category")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="OCR confidence score")
    warning: Optional[str] = Field(None, description="Warning flag if price suspicious")
    # Normalization fields
    nazwa_oryginalna: Optional[str] = Field(None, description="Original name from receipt before normalization")
    nazwa_znormalizowana: Optional[str] = Field(None, description="Normalized product name from dictionary")
    # Discount fields
    cena_oryginalna: Optional[float] = Field(None, description="Original price before discount")
    rabat: Optional[float] = Field(None, description="Total discount amount (positive value)")
    rabaty_szczegoly: Optional[list[DiscountDetail]] = Field(None, description="Detailed breakdown of discounts")


class Receipt(BaseModel):
    """Parsed receipt data."""

    products: list[Product] = Field(default_factory=list, description="List of products")
    sklep: Optional[str] = Field(None, description="Store name")
    data: Optional[str] = Field(None, description="Receipt date (YYYY-MM-DD)")
    suma: Optional[float] = Field(None, description="Total amount")
    raw_text: Optional[str] = Field(None, description="Raw OCR text for debugging")
    # Review fields for human-in-the-loop
    needs_review: bool = Field(default=False, description="Flag indicating receipt needs human verification")
    review_reasons: list[str] = Field(default_factory=list, description="Reasons why review is needed")
    calculated_total: Optional[float] = Field(None, description="Sum of product prices for validation")


class ProcessingResult(BaseModel):
    """Result of receipt processing."""

    success: bool = Field(..., description="Whether processing succeeded")
    receipt: Optional[Receipt] = Field(None, description="Parsed receipt data")
    source_file: str = Field(..., description="Original filename")
    output_file: Optional[str] = Field(None, description="Generated markdown file path")
    error: Optional[str] = Field(None, description="Error message if failed")
    processed_at: datetime = Field(default_factory=datetime.now, description="Processing timestamp")
    needs_review: bool = Field(default=False, description="Flag indicating result needs human verification")
    receipt_id: Optional[str] = Field(None, description="Database receipt ID (UUID)")


class HealthStatus(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Overall status")
    ollama_available: bool = Field(..., description="Whether Ollama is reachable")
    ocr_model_loaded: bool = Field(..., description="Whether OCR model is available")
    classifier_model_loaded: bool = Field(..., description="Whether classifier model is available")
    inbox_path: str = Field(..., description="Inbox directory path")
    vault_path: str = Field(..., description="Vault directory path")


class CategorizedProduct(BaseModel):
    """Product with assigned category."""

    nazwa: str
    cena: float
    kategoria: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    warning: Optional[str] = None
    # Normalization fields
    nazwa_oryginalna: Optional[str] = None
    nazwa_znormalizowana: Optional[str] = None
    # Discount fields
    cena_oryginalna: Optional[float] = None
    rabat: Optional[float] = None
    rabaty_szczegoly: Optional[list[DiscountDetail]] = None
