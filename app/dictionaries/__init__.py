"""Dictionary loaders for normalization."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_DICTIONARIES_PATH = Path(__file__).parent
_stores_dict: Optional[dict] = None
_products_index: Optional[dict] = None
_shortcuts_dict: Optional[dict] = None

# Fuzzy matching threshold (0.0-1.0, higher = stricter)
FUZZY_THRESHOLD = 0.75


@dataclass
class NormalizedProduct:
    """Result of product normalization."""
    raw_name: str
    normalized_name: Optional[str]
    category: Optional[str]
    category_id: Optional[str]
    confidence: float
    method: str  # exact_match, partial_match, fuzzy_match, keyword, no_match


# ============================================================
# Fuzzy matching (Levenshtein distance)
# ============================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein distance between two strings.
    Uses dynamic programming for O(m*n) time complexity.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Insertions, deletions, substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def string_similarity(s1: str, s2: str) -> float:
    """
    Calculate similarity ratio between two strings (0.0-1.0).
    Uses Levenshtein distance normalized by max length.
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1.0 - (distance / max_len)


def remove_polish_diacritics(text: str) -> str:
    """Remove Polish diacritical marks for fuzzy comparison."""
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
    }
    for pl, ascii in replacements.items():
        text = text.replace(pl, ascii)
    return text


def fuzzy_match(query: str, candidates: dict, threshold: float = FUZZY_THRESHOLD) -> Optional[Tuple[str, dict, float]]:
    """
    Find best fuzzy match for query in candidates dictionary.

    Args:
        query: String to match
        candidates: Dict of {key: info} to search in
        threshold: Minimum similarity (0.0-1.0)

    Returns:
        Tuple of (matched_key, info, similarity) or None
    """
    query_clean = remove_polish_diacritics(query.lower().strip())
    query_words = set(query_clean.split())

    best_match = None
    best_score = threshold

    for key, info in candidates.items():
        key_clean = remove_polish_diacritics(key.lower())

        # Full string similarity
        similarity = string_similarity(query_clean, key_clean)

        # Also check word overlap for multi-word products
        key_words = set(key_clean.split())
        common_words = query_words & key_words
        if common_words:
            word_bonus = len(common_words) / max(len(query_words), len(key_words)) * 0.2
            similarity = min(1.0, similarity + word_bonus)

        if similarity > best_score:
            best_score = similarity
            best_match = (key, info, similarity)

    return best_match


def load_stores_dict() -> dict:
    """Load and cache stores dictionary."""
    global _stores_dict
    if _stores_dict is None:
        path = _DICTIONARIES_PATH / "stores.json"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _stores_dict = data.get("stores", {})
                logger.info(f"Loaded {len(_stores_dict)} stores from dictionary")
        except FileNotFoundError:
            logger.warning(f"Stores dictionary not found: {path}")
            _stores_dict = {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse stores dictionary: {e}")
            _stores_dict = {}
    return _stores_dict


def load_shortcuts_dict() -> dict:
    """Load and cache product shortcuts dictionary."""
    global _shortcuts_dict
    if _shortcuts_dict is None:
        path = _DICTIONARIES_PATH / "product_shortcuts.json"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Remove metadata, keep only store mappings
                _shortcuts_dict = {
                    k: v for k, v in data.items()
                    if k != "metadata" and isinstance(v, dict)
                }
                total_shortcuts = sum(len(v) for v in _shortcuts_dict.values())
                logger.info(f"Loaded {total_shortcuts} shortcuts for {len(_shortcuts_dict)} stores")
        except FileNotFoundError:
            logger.warning(f"Shortcuts dictionary not found: {path}")
            _shortcuts_dict = {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse shortcuts dictionary: {e}")
            _shortcuts_dict = {}
    return _shortcuts_dict


def clear_shortcuts_cache() -> None:
    """Clear the shortcuts dictionary cache."""
    global _shortcuts_dict
    _shortcuts_dict = None


def shortcut_match(raw_name: str, store: Optional[str] = None) -> Optional[Tuple[str, float]]:
    """
    Match product name against store-specific shortcuts.

    Args:
        raw_name: Raw product name from receipt
        store: Store name (e.g., "biedronka", "Biedronka")

    Returns:
        Tuple of (full_name, confidence) or None if no match
    """
    if not store:
        return None

    shortcuts = load_shortcuts_dict()
    store_lower = store.lower()

    if store_lower not in shortcuts:
        return None

    store_shortcuts = shortcuts[store_lower]

    # Clean the raw name for matching
    clean_name = re.sub(r'\s+', '', raw_name.lower().strip())
    clean_name_no_diacritics = remove_polish_diacritics(clean_name)

    # Try exact match first
    if clean_name in store_shortcuts:
        return (store_shortcuts[clean_name], 0.95)

    # Try without diacritics
    if clean_name_no_diacritics in store_shortcuts:
        return (store_shortcuts[clean_name_no_diacritics], 0.94)

    # Try partial match (shortcut is contained in name or vice versa)
    for shortcut, full_name in store_shortcuts.items():
        shortcut_no_diacritics = remove_polish_diacritics(shortcut)

        # Check if shortcut is contained in the cleaned name
        if shortcut in clean_name or shortcut_no_diacritics in clean_name_no_diacritics:
            return (full_name, 0.92)

        # Check if cleaned name is contained in shortcut (for very short OCR captures)
        if len(clean_name) >= 4 and clean_name in shortcut:
            return (full_name, 0.88)

    return None


def normalize_store_name(text: str) -> Optional[str]:
    """
    Normalize store name using dictionary.

    Args:
        text: Raw text that may contain store name

    Returns:
        Normalized store name or None if not found
    """
    stores = load_stores_dict()
    text_lower = text.lower()

    for normalized_name, aliases in stores.items():
        for alias in aliases:
            if alias in text_lower:
                return normalized_name

    return None


# ============================================================
# Product normalization
# ============================================================

def load_products_index() -> dict:
    """Load and build products search index."""
    global _products_index
    if _products_index is not None:
        return _products_index

    path = _DICTIONARIES_PATH / "products.json"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Products dictionary not found: {path}")
        _products_index = {}
        return _products_index
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse products dictionary: {e}")
        _products_index = {}
        return _products_index

    # Build search index: raw_name.lower() -> product info
    _products_index = {}
    for category_key, category_data in data.items():
        if category_key == "metadata" or not isinstance(category_data, dict):
            continue
        if "products" not in category_data:
            continue

        category_id = category_data.get("category_id", "")
        for product in category_data["products"]:
            normalized = product.get("normalized_name", "")
            for raw_name in product.get("raw_names", []):
                key = raw_name.lower().strip()
                _products_index[key] = {
                    "normalized": normalized,
                    "category": category_key,
                    "category_id": category_id,
                }

    logger.info(f"Built products index with {len(_products_index)} entries")
    return _products_index


# Keyword -> (category, normalized_name, category_id)
# Include variants without Polish diacritics (OCR often strips them)
_KEYWORD_MAP = {
    # Nabiał
    "mleko": ("nabiał", "mleko", "NAB"),
    "jogurt": ("nabiał", "jogurt", "NAB"),
    "ser ": ("nabiał", "ser", "NAB"),  # space to avoid "sernik"
    "serek": ("nabiał", "serek", "NAB"),
    "skyr": ("nabiał", "skyr", "NAB"),
    "masło": ("nabiał", "masło", "NAB"),
    "maslo": ("nabiał", "masło", "NAB"),
    "śmietana": ("nabiał", "śmietana", "NAB"),
    "smietana": ("nabiał", "śmietana", "NAB"),
    "twaróg": ("nabiał", "twaróg", "NAB"),
    "twarog": ("nabiał", "twaróg", "NAB"),
    "jaj": ("nabiał", "jaja", "NAB"),
    # Piekarnia
    "chleb": ("piekarnia", "chleb", "PIE"),
    "bułk": ("piekarnia", "bułki", "PIE"),
    "bulk": ("piekarnia", "bułki", "PIE"),
    # Mięso
    "mięso": ("mięso", "mięso", "MIE"),
    "mieso": ("mięso", "mięso", "MIE"),
    "mielon": ("mięso", "mięso mielone", "MIE"),
    "schab": ("mięso", "schab", "MIE"),
    "kurczak": ("mięso", "kurczak filet", "MIE"),
    "filet": ("mięso", "kurczak filet", "MIE"),
    # Wędliny
    "szynk": ("wędliny", "szynka", "WED"),
    "kiełbas": ("wędliny", "kiełbasa", "WED"),
    "kielbas": ("wędliny", "kiełbasa", "WED"),
    "boczek": ("wędliny", "boczek", "WED"),
    "salami": ("wędliny", "salami", "WED"),
    "pasztet": ("wędliny", "pasztet", "WED"),
    "parówk": ("wędliny", "parówki", "WED"),
    "parowk": ("wędliny", "parówki", "WED"),
    # Ryby
    "łosoś": ("ryby", "łosoś", "RYB"),
    "losos": ("ryby", "łosoś", "RYB"),
    "dorsz": ("ryby", "dorsz", "RYB"),
    "śledź": ("ryby", "śledź", "RYB"),
    "sledz": ("ryby", "śledź", "RYB"),
    "tuńczyk": ("ryby", "tuńczyk", "RYB"),
    "tunczyk": ("ryby", "tuńczyk", "RYB"),
    # Warzywa
    "pomidor": ("warzywa", "pomidory", "WAR"),
    "ziemniak": ("warzywa", "ziemniaki", "WAR"),
    "kartofl": ("warzywa", "ziemniaki", "WAR"),
    "ogórek": ("warzywa", "ogórki", "WAR"),
    "ogorek": ("warzywa", "ogórki", "WAR"),
    "kapust": ("warzywa", "kapusta", "WAR"),
    "papryk": ("warzywa", "papryka", "WAR"),
    "cebul": ("warzywa", "cebula", "WAR"),
    "marchew": ("warzywa", "marchew", "WAR"),
    # Owoce
    "banan": ("owoce", "banany", "OWO"),
    "jabłk": ("owoce", "jabłka", "OWO"),
    "jablk": ("owoce", "jabłka", "OWO"),
    "pomarańcz": ("owoce", "pomarańcze", "OWO"),
    "pomarancz": ("owoce", "pomarańcze", "OWO"),
    "winogrona": ("owoce", "winogrona", "OWO"),
    "cytryn": ("owoce", "cytryny", "OWO"),
    # Napoje
    "sok": ("napoje", "sok", "NAP"),
    "woda": ("napoje", "woda", "NAP"),
    "napój": ("napoje", "napój", "NAP"),
    "napoj": ("napoje", "napój", "NAP"),
    # Alkohol
    "piwo": ("alkohol", "piwo", "ALK"),
    "wino": ("alkohol", "wino", "ALK"),
    "wódka": ("alkohol", "wódka", "ALK"),
    "wodka": ("alkohol", "wódka", "ALK"),
    # Napoje gorące
    "kawa": ("napoje_gorące", "kawa", "NGO"),
    "herbat": ("napoje_gorące", "herbata", "NGO"),
    # Produkty sypkie
    "makaron": ("makarony", "makaron", "MAK"),
    "ryż": ("makarony", "ryż", "MAK"),
    "ryz": ("makarony", "ryż", "MAK"),
    "kasza": ("makarony", "kasza", "MAK"),
    "mąka": ("makarony", "mąka", "MAK"),
    "maka": ("makarony", "mąka", "MAK"),
    # Słodycze
    "czekolad": ("słodycze", "czekolada", "SŁO"),
    "ciastk": ("słodycze", "ciasteczka", "SŁO"),
    "cukierk": ("słodycze", "cukierki", "SŁO"),
    "żelk": ("słodycze", "żelki", "SŁO"),
    "zelk": ("słodycze", "żelki", "SŁO"),
    # Chemia
    "proszek": ("chemia", "proszek do prania", "CHE"),
    "płyn": ("chemia", "płyn", "CHE"),
    "plyn": ("chemia", "płyn", "CHE"),
    "szampon": ("kosmetyki", "szampon", "KOS"),
    "mydło": ("kosmetyki", "mydło", "KOS"),
    "mydlo": ("kosmetyki", "mydło", "KOS"),
    "papier toalet": ("chemia", "papier toaletowy", "CHE"),
    "dezodorant": ("kosmetyki", "dezodorant", "KOS"),
    "pasta do zęb": ("kosmetyki", "pasta do zębów", "KOS"),
    # Przekąski
    "chips": ("przekąski", "chipsy", "PRZ"),
    "chipsy": ("przekąski", "chipsy", "PRZ"),
    "paluszk": ("przekąski", "paluszki", "PRZ"),
    "orzeszk": ("przekąski", "orzeszki", "PRZ"),
    "orzech": ("przekąski", "orzeszki", "PRZ"),
    "nachos": ("przekąski", "nachos", "PRZ"),
    "popcorn": ("przekąski", "popcorn", "PRZ"),
    # Dla zwierząt
    "karma": ("dla_zwierząt", "karma", "ZWI"),
    "whiskas": ("dla_zwierząt", "karma dla kota", "ZWI"),
    "pedigree": ("dla_zwierząt", "karma dla psa", "ZWI"),
    "żwirek": ("dla_zwierząt", "żwirek dla kota", "ZWI"),
    # Dla dzieci
    "pieluch": ("dla_dzieci", "pieluchy", "DZI"),
    "pampers": ("dla_dzieci", "pieluchy", "DZI"),
    # Mrożonki
    "frytki": ("mrożonki", "frytki", "MRO"),
    "pizza": ("mrożonki", "pizza mrożona", "MRO"),
    "pierogi": ("mrożonki", "pierogi mrożone", "MRO"),
    "nuggets": ("mrożonki", "nuggetsy", "MRO"),
    "nuggetsy": ("mrożonki", "nuggetsy", "MRO"),
    # Dania gotowe
    "zupa instant": ("dania_gotowe", "zupa instant", "DAN"),
    "zupka": ("dania_gotowe", "zupa instant", "DAN"),
    "bigos": ("dania_gotowe", "bigos", "DAN"),
    "hummus": ("dania_gotowe", "hummus", "DAN"),
}


def normalize_product(raw_name: str, use_fuzzy: bool = True, store: Optional[str] = None) -> NormalizedProduct:
    """
    Normalize product name using dictionary.

    Args:
        raw_name: Raw product name from receipt
        use_fuzzy: Enable fuzzy matching (Levenshtein distance)
        store: Store name for store-specific shortcut matching

    Returns:
        NormalizedProduct with normalized name, category, confidence
    """
    index = load_products_index()
    clean_name = re.sub(r'\s+', ' ', raw_name.lower().strip())

    # 1. Exact match
    if clean_name in index:
        info = index[clean_name]
        return NormalizedProduct(
            raw_name=raw_name,
            normalized_name=info["normalized"],
            category=info["category"],
            category_id=info["category_id"],
            confidence=0.99,
            method="exact_match"
        )

    # 2. Partial match (70% words overlap)
    words = clean_name.split()
    for key, info in index.items():
        key_words = key.split()
        matching = sum(1 for w in words if w in key_words)
        if matching / max(len(words), 1) >= 0.7:
            return NormalizedProduct(
                raw_name=raw_name,
                normalized_name=info["normalized"],
                category=info["category"],
                category_id=info["category_id"],
                confidence=0.7 + 0.2 * (matching / max(len(words), 1)),
                method="partial_match"
            )

    # 2.5. Store-specific shortcut match (before fuzzy match)
    if store:
        shortcut_result = shortcut_match(raw_name, store)
        if shortcut_result:
            full_name, confidence = shortcut_result
            # Try to find the expanded name in the index for category info
            full_name_lower = full_name.lower()
            if full_name_lower in index:
                info = index[full_name_lower]
                return NormalizedProduct(
                    raw_name=raw_name,
                    normalized_name=info["normalized"],
                    category=info["category"],
                    category_id=info["category_id"],
                    confidence=confidence,
                    method="shortcut_match"
                )
            else:
                # Shortcut matched but full name not in index - use keyword fallback for category
                for keyword, (category, normalized, cat_id) in _KEYWORD_MAP.items():
                    if keyword in full_name_lower:
                        return NormalizedProduct(
                            raw_name=raw_name,
                            normalized_name=full_name,
                            category=category,
                            category_id=cat_id,
                            confidence=confidence,
                            method="shortcut_match"
                        )
                # No category found, return with shortcut name
                return NormalizedProduct(
                    raw_name=raw_name,
                    normalized_name=full_name,
                    category=None,
                    category_id=None,
                    confidence=confidence,
                    method="shortcut_match"
                )

    # 3. Fuzzy match (Levenshtein distance)
    if use_fuzzy:
        fuzzy_result = fuzzy_match(clean_name, index, FUZZY_THRESHOLD)
        if fuzzy_result:
            matched_key, info, similarity = fuzzy_result
            return NormalizedProduct(
                raw_name=raw_name,
                normalized_name=info["normalized"],
                category=info["category"],
                category_id=info["category_id"],
                confidence=similarity * 0.9,  # Scale to max 0.9 for fuzzy
                method="fuzzy_match"
            )

    # 4. Keyword extraction
    for keyword, (category, normalized, cat_id) in _KEYWORD_MAP.items():
        if keyword in clean_name:
            return NormalizedProduct(
                raw_name=raw_name,
                normalized_name=normalized,
                category=category,
                category_id=cat_id,
                confidence=0.6,
                method="keyword"
            )

    # 5. No match
    return NormalizedProduct(
        raw_name=raw_name,
        normalized_name=None,
        category=None,
        category_id=None,
        confidence=0.0,
        method="no_match"
    )
