"""System oceny pewności (confidence) ekstrakcji paragonów.

Confidence score bazuje na kilku metrykach:
1. Zgodność sum (suma produktów vs suma z paragonu)
2. Kompletność danych (czy jest data, sklep, suma)
3. Jakość produktów (czy nazwy wyglądają sensownie)
4. Spójność rabatów (czy rabaty mają sens)

Score końcowy: 0.0 - 1.0
- >= 0.8: Wysoka pewność, auto-zapis
- 0.5 - 0.8: Średnia pewność, warto przejrzeć
- < 0.5: Niska pewność, wymaga review
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.models import Receipt, Product

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceReport:
    """Raport pewności ekstrakcji."""

    # Wynik końcowy (0.0 - 1.0)
    score: float

    # Szczegółowe oceny
    total_match_score: float = 0.0      # Zgodność sum
    completeness_score: float = 0.0     # Kompletność metadanych
    product_quality_score: float = 0.0  # Jakość nazw produktów
    discount_consistency_score: float = 0.0  # Spójność rabatów

    # Flagi
    needs_review: bool = False
    auto_save_ok: bool = False

    # Szczegóły problemów
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "total_match_score": round(self.total_match_score, 3),
            "completeness_score": round(self.completeness_score, 3),
            "product_quality_score": round(self.product_quality_score, 3),
            "discount_consistency_score": round(self.discount_consistency_score, 3),
            "needs_review": self.needs_review,
            "auto_save_ok": self.auto_save_ok,
            "issues": self.issues,
            "warnings": self.warnings,
        }


def calculate_confidence(receipt: Receipt) -> ConfidenceReport:
    """Oblicz confidence score dla paragonu.

    Args:
        receipt: Wyekstrahowany paragon

    Returns:
        ConfidenceReport z oceną i szczegółami
    """
    issues = []
    warnings = []

    # 1. Zgodność sum (waga: 40%)
    total_match_score = _score_total_match(receipt, issues, warnings)

    # 2. Kompletność danych (waga: 20%)
    completeness_score = _score_completeness(receipt, issues, warnings)

    # 3. Jakość produktów (waga: 30%)
    product_quality_score = _score_product_quality(receipt, issues, warnings)

    # 4. Spójność rabatów (waga: 10%)
    discount_consistency_score = _score_discount_consistency(receipt, issues, warnings)

    # Wynik końcowy (ważony)
    final_score = (
        total_match_score * 0.40 +
        completeness_score * 0.20 +
        product_quality_score * 0.30 +
        discount_consistency_score * 0.10
    )

    # Decyzje
    needs_review = final_score < 0.7 or len(issues) > 0
    auto_save_ok = final_score >= 0.8 and len(issues) == 0

    report = ConfidenceReport(
        score=final_score,
        total_match_score=total_match_score,
        completeness_score=completeness_score,
        product_quality_score=product_quality_score,
        discount_consistency_score=discount_consistency_score,
        needs_review=needs_review,
        auto_save_ok=auto_save_ok,
        issues=issues,
        warnings=warnings,
    )

    logger.info(f"Confidence score: {final_score:.2f} (review: {needs_review})")
    if issues:
        logger.warning(f"Issues: {issues}")

    return report


def _score_total_match(
    receipt: Receipt,
    issues: List[str],
    warnings: List[str]
) -> float:
    """Ocena zgodności sumy produktów z sumą z paragonu."""

    if not receipt.products:
        issues.append("Brak produktów")
        return 0.0

    calculated = sum(p.cena for p in receipt.products)
    declared = receipt.suma

    if not declared:
        warnings.append("Brak sumy na paragonie")
        return 0.7  # Nie możemy zweryfikować, ale produkty są

    if calculated == 0:
        issues.append("Suma produktów = 0")
        return 0.0

    # Różnica absolutna i procentowa
    diff_abs = abs(declared - calculated)
    diff_pct = (diff_abs / declared) * 100 if declared > 0 else 100

    # Scoring
    if diff_abs <= 0.10:  # Dokładne dopasowanie (błąd zaokrągleń)
        return 1.0
    elif diff_abs <= 1.0:  # < 1 zł różnicy
        return 0.95
    elif diff_abs <= 3.0:  # < 3 zł różnicy
        warnings.append(f"Drobna różnica sum: {diff_abs:.2f} zł")
        return 0.85
    elif diff_abs <= 5.0:  # < 5 zł różnicy
        warnings.append(f"Różnica sum: {diff_abs:.2f} zł ({diff_pct:.1f}%)")
        return 0.7
    elif diff_pct <= 10:  # < 10% różnicy
        issues.append(f"Znaczna różnica sum: {diff_abs:.2f} zł ({diff_pct:.1f}%)")
        return 0.5
    else:  # > 10% różnicy
        issues.append(f"Duża różnica sum: {diff_abs:.2f} zł ({diff_pct:.1f}%)")
        return 0.2


def _score_completeness(
    receipt: Receipt,
    issues: List[str],
    warnings: List[str]
) -> float:
    """Ocena kompletności metadanych."""

    score = 0.0
    max_score = 4.0

    # Sklep (1 pkt)
    if receipt.sklep and len(receipt.sklep) > 2:
        score += 1.0
    else:
        warnings.append("Brak nazwy sklepu")

    # Data (1 pkt)
    if receipt.data:
        # Sprawdź czy format jest OK (YYYY-MM-DD)
        if re.match(r'\d{4}-\d{2}-\d{2}', receipt.data):
            score += 1.0
        else:
            score += 0.5
            warnings.append(f"Nietypowy format daty: {receipt.data}")
    else:
        warnings.append("Brak daty")

    # Suma (1 pkt)
    if receipt.suma and receipt.suma > 0:
        score += 1.0
    else:
        warnings.append("Brak sumy")

    # Produkty (1 pkt)
    if receipt.products and len(receipt.products) >= 1:
        score += 1.0
    else:
        issues.append("Brak produktów")

    return score / max_score


def _score_product_quality(
    receipt: Receipt,
    issues: List[str],
    warnings: List[str]
) -> float:
    """Ocena jakości wyekstrahowanych produktów."""

    if not receipt.products:
        return 0.0

    total_score = 0.0
    product_count = len(receipt.products)

    # Wzorce podejrzanych nazw
    suspicious_patterns = [
        r'^product\d*$',
        r'^item\d*$',
        r'^produkt\d*$',
        r'^\d+$',           # Same cyfry
        r'^[A-Z]{1,3}$',    # Same wielkie litery (VAT codes)
        r'^PTU',
        r'^VAT',
    ]

    good_products = 0
    suspicious_products = []

    for product in receipt.products:
        name = product.nazwa.strip().lower()
        price = product.cena

        product_score = 1.0

        # Sprawdź długość nazwy
        if len(name) < 3:
            product_score *= 0.5
        elif len(name) > 50:
            product_score *= 0.8  # Za długa nazwa

        # Sprawdź podejrzane wzorce
        is_suspicious = False
        for pattern in suspicious_patterns:
            if re.match(pattern, name, re.IGNORECASE):
                is_suspicious = True
                break

        if is_suspicious:
            product_score *= 0.3
            suspicious_products.append(product.nazwa)

        # Sprawdź cenę
        if price <= 0:
            product_score *= 0.2
        elif price > 500:
            product_score *= 0.7
            warnings.append(f"Wysoka cena: {product.nazwa} = {price} zł")

        # Sprawdź czy ma kategorię
        if product.kategoria:
            product_score *= 1.1  # Bonus za kategorię
            product_score = min(product_score, 1.0)

        if product_score >= 0.8:
            good_products += 1

        total_score += product_score

    # Raportuj podejrzane produkty
    if suspicious_products:
        warnings.append(f"Podejrzane nazwy: {suspicious_products[:3]}")

    # Średnia ocena produktów
    avg_score = total_score / product_count if product_count > 0 else 0

    # Bonus za liczbę produktów (paragony mają zazwyczaj 3-30 produktów)
    if 3 <= product_count <= 30:
        avg_score *= 1.0
    elif product_count < 3:
        warnings.append(f"Mało produktów: {product_count}")
        avg_score *= 0.9
    else:
        warnings.append(f"Dużo produktów: {product_count}")
        avg_score *= 0.95

    return min(avg_score, 1.0)


def _score_discount_consistency(
    receipt: Receipt,
    issues: List[str],
    warnings: List[str]
) -> float:
    """Ocena spójności rabatów."""

    if not receipt.products:
        return 1.0  # Brak produktów = brak rabatów do sprawdzenia

    products_with_discount = [p for p in receipt.products if p.rabat and p.rabat > 0]

    if not products_with_discount:
        return 1.0  # Brak rabatów = OK

    total_score = 0.0
    count = len(products_with_discount)

    for product in products_with_discount:
        score = 1.0

        # Rabat powinien być mniejszy niż cena oryginalna
        if product.cena_oryginalna:
            if product.rabat > product.cena_oryginalna:
                issues.append(f"Rabat > cena oryginalna: {product.nazwa}")
                score *= 0.3
            elif product.rabat > product.cena_oryginalna * 0.8:
                warnings.append(f"Bardzo duży rabat (>80%): {product.nazwa}")
                score *= 0.7

        # Rabat powinien być sensowny (< 50 zł dla większości produktów)
        if product.rabat > 50:
            warnings.append(f"Duży rabat: {product.nazwa} = -{product.rabat} zł")
            score *= 0.8

        # Cena końcowa powinna być dodatnia
        if product.cena <= 0:
            issues.append(f"Cena końcowa <= 0 po rabacie: {product.nazwa}")
            score *= 0.2

        total_score += score

    return total_score / count if count > 0 else 1.0


def should_auto_save(receipt: Receipt, threshold: float = 0.8) -> bool:
    """Szybka decyzja czy paragon może być automatycznie zapisany.

    Args:
        receipt: Paragon do oceny
        threshold: Minimalny confidence score (domyślnie 0.8)

    Returns:
        True jeśli paragon jest wystarczająco pewny do auto-zapisu
    """
    report = calculate_confidence(receipt)
    return report.auto_save_ok and report.score >= threshold


def get_review_priority(receipt: Receipt) -> str:
    """Określ priorytet review na podstawie confidence.

    Returns:
        "high", "medium", lub "low"
    """
    report = calculate_confidence(receipt)

    if report.score < 0.5 or len(report.issues) >= 2:
        return "high"
    elif report.score < 0.7 or len(report.issues) >= 1:
        return "medium"
    else:
        return "low"
