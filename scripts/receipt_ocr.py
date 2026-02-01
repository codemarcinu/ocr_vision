#!/usr/bin/env python3
"""
Receipt OCR Pipeline - Batch processing receipts with Qwen3-VL via Ollama
Author: Claude for Marcin
Requires: pip install ollama pdf2image pillow --break-system-packages
"""

import os
import json
import csv
import base64
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Opcjonalne importy
try:
    from pdf2image import convert_from_path
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning("pdf2image nie zainstalowane. PDF nie będą obsługiwane.")
    logger.warning("Zainstaluj: pip install pdf2image --break-system-packages")

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.error("Biblioteka ollama nie zainstalowana!")
    logger.error("Zainstaluj: pip install ollama --break-system-packages")


# ============================================================================
# KONFIGURACJA
# ============================================================================

CONFIG = {
    "model": "qwen2.5vl:7b",           # Model do OCR (najlepszy dla paragonów)
    "output_dir": "./output",          # Katalog wyjściowy
    "temp_dir": "./temp",              # Katalog tymczasowy dla PDF
    "pdf_dpi": 300,                    # DPI dla konwersji PDF
    "csv_filename": "paragony.csv",    # Nazwa pliku CSV
    "json_filename": "paragony.json",  # Nazwa pliku JSON
    "supported_formats": [".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"],
}

# Prompty do ekstrakcji danych z paragonu
RECEIPT_PROMPT_EN = """Analyze this receipt image and extract ALL information.

IMPORTANT: Extract EVERY product line item, even if partially visible.

Return ONLY valid JSON in this exact format:

{
    "sklep": "store/company name",
    "adres": "store address if visible",
    "nip": "tax ID if visible",
    "data": "YYYY-MM-DD",
    "godzina": "HH:MM",
    "produkty": [
        {
            "nazwa": "product name",
            "ilosc": 1,
            "cena_jednostkowa": 0.00,
            "cena_razem": 0.00
        }
    ],
    "suma": 0.00,
    "platnosc": "cash/card/other",
    "numer_paragonu": "receipt number if visible",
    "uwagi": "additional notes"
}

Rules:
- "produkty" array MUST contain ALL products from the receipt
- Use null for unreadable or missing fields
- Prices as numbers (not strings), e.g. 12.99 not "12,99 zł"
- Return ONLY JSON, no explanation"""

RECEIPT_PROMPT_PL = """Przeanalizuj dokładnie ten paragon/fakturę i wyodrębnij WSZYSTKIE informacje.

WAŻNE: Wyodrębnij KAŻDY produkt z paragonu, nawet jeśli częściowo widoczny.

Zwróć TYLKO prawidłowy JSON w tym formacie:

{
    "sklep": "nazwa sklepu/firmy",
    "adres": "adres sklepu jeśli widoczny",
    "nip": "NIP sklepu jeśli widoczny",
    "data": "YYYY-MM-DD",
    "godzina": "HH:MM",
    "produkty": [
        {
            "nazwa": "nazwa produktu",
            "ilosc": 1,
            "cena_jednostkowa": 0.00,
            "cena_razem": 0.00
        }
    ],
    "suma": 0.00,
    "platnosc": "gotówka/karta/inne",
    "numer_paragonu": "numer jeśli widoczny",
    "uwagi": "dodatkowe informacje"
}

Zasady:
- Tablica "produkty" MUSI zawierać WSZYSTKIE produkty z paragonu
- Jeśli pole nieczytelne lub nie występuje, użyj null
- Ceny jako liczby (nie stringi), np. 12.99 nie "12,99 zł"
- Zwróć TYLKO JSON, bez wyjaśnień"""

# Domyślny prompt (angielski - często lepsze wyniki z VLM)
RECEIPT_PROMPT = RECEIPT_PROMPT_EN


# ============================================================================
# FUNKCJE POMOCNICZE
# ============================================================================

def ensure_dirs():
    """Tworzy wymagane katalogi."""
    Path(CONFIG["output_dir"]).mkdir(parents=True, exist_ok=True)
    Path(CONFIG["temp_dir"]).mkdir(parents=True, exist_ok=True)


def image_to_base64(image_path: str) -> str:
    """Konwertuje obraz do base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def pdf_to_images(pdf_path: str) -> list[str]:
    """Konwertuje PDF na obrazy PNG."""
    if not PDF_SUPPORT:
        raise ImportError("pdf2image nie jest zainstalowane")
    
    images = convert_from_path(pdf_path, dpi=CONFIG["pdf_dpi"])
    output_paths = []
    
    pdf_name = Path(pdf_path).stem
    for i, image in enumerate(images):
        output_path = Path(CONFIG["temp_dir"]) / f"{pdf_name}_page_{i+1}.png"
        image.save(str(output_path), "PNG")
        output_paths.append(str(output_path))
        logger.info(f"  Strona {i+1}/{len(images)} zapisana: {output_path}")
    
    return output_paths


def clean_json_response(response: str) -> str:
    """Czyści odpowiedź modelu z markdown i innych artefaktów."""
    import re

    response = response.strip()

    # Usuń thinking tags jeśli model je zwrócił w tekście
    if "<think>" in response:
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)

    # Usuń bloki kodu markdown
    if "```json" in response:
        match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if match:
            return match.group(1).strip()
    elif "```" in response:
        match = re.search(r'```\s*(.*?)\s*```', response, re.DOTALL)
        if match:
            return match.group(1).strip()

    # Spróbuj wyekstrahować JSON z tekstu (dla odpowiedzi z thinking)
    # Szukaj pierwszego { i ostatniego }
    first_brace = response.find('{')
    last_brace = response.rfind('}')

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return response[first_brace:last_brace + 1]

    return response.strip()


def parse_receipt_json(json_str: str, filename: str) -> dict:
    """Parsuje JSON z odpowiedzi modelu."""
    try:
        cleaned = clean_json_response(json_str)
        data = json.loads(cleaned)
        data["_plik_zrodlowy"] = filename
        data["_czas_przetwarzania"] = datetime.now().isoformat()
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Błąd parsowania JSON dla {filename}: {e}")
        logger.debug(f"Surowa odpowiedź: {json_str[:500]}...")
        return {
            "_plik_zrodlowy": filename,
            "_czas_przetwarzania": datetime.now().isoformat(),
            "_blad": f"Nie udało się sparsować JSON: {str(e)}",
            "_surowa_odpowiedz": json_str[:1000]
        }


# ============================================================================
# GŁÓWNA LOGIKA OCR
# ============================================================================

def get_model_response_text(response) -> str:
    """Wyciąga tekst odpowiedzi z modelu (obsługuje content i thinking)."""
    msg = response.message

    # Najpierw sprawdź content
    if msg.content and msg.content.strip():
        return msg.content

    # Qwen3-VL może umieszczać odpowiedź w polu thinking
    if hasattr(msg, 'thinking') and msg.thinking:
        logger.debug("Odpowiedź znaleziona w polu 'thinking'")
        return msg.thinking

    return ""


def process_image(image_path: str) -> dict:
    """Przetwarza pojedynczy obraz przez Qwen3-VL."""
    if not OLLAMA_AVAILABLE:
        raise ImportError("Biblioteka ollama nie jest dostępna")

    logger.info(f"Przetwarzanie: {image_path}")

    prompt = RECEIPT_PROMPT_PL if CONFIG.get("use_polish") else RECEIPT_PROMPT_EN

    try:
        response = ollama.chat(
            model=CONFIG["model"],
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_path]
            }],
            options={
                'temperature': 0.1,   # Niska dla OCR
                'top_p': 0.8,         # Oficjalne ustawienie Qwen3-VL
                'top_k': 20,          # Oficjalne ustawienie Qwen3-VL
                'num_predict': 4096,  # Max tokenów odpowiedzi
                'num_ctx': 4096,      # Wymagane dla obrazów (offload na CPU OK)
                'think': False,       # Wyłączenie thinking mode
            }
        )

        response_text = get_model_response_text(response)

        if not response_text:
            logger.warning(f"  Model zwrócił pustą odpowiedź dla {image_path}")
            return {
                "_plik_zrodlowy": Path(image_path).name,
                "_czas_przetwarzania": datetime.now().isoformat(),
                "_blad": "Model zwrócił pustą odpowiedź"
            }

        result = parse_receipt_json(response_text, Path(image_path).name)

        logger.info(f"  ✓ Sukces: {result.get('sklep', 'nieznany sklep')}")
        return result

    except Exception as e:
        logger.error(f"  ✗ Błąd przetwarzania {image_path}: {e}")
        return {
            "_plik_zrodlowy": Path(image_path).name,
            "_czas_przetwarzania": datetime.now().isoformat(),
            "_blad": str(e)
        }


def process_file(file_path: str) -> list[dict]:
    """Przetwarza plik (obraz lub PDF)."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    
    if suffix not in CONFIG["supported_formats"]:
        logger.warning(f"Nieobsługiwany format: {suffix}")
        return []
    
    results = []
    
    if suffix == ".pdf":
        if not PDF_SUPPORT:
            logger.error(f"Pominięto PDF {file_path} - brak pdf2image")
            return []
        
        logger.info(f"Konwersja PDF: {file_path}")
        image_paths = pdf_to_images(file_path)
        
        for img_path in image_paths:
            result = process_image(img_path)
            result["_pdf_zrodlowy"] = path.name
            results.append(result)
    else:
        results.append(process_image(file_path))
    
    return results


def batch_process(input_paths: list[str]) -> list[dict]:
    """Przetwarza wiele plików."""
    all_results = []
    
    for path in input_paths:
        path_obj = Path(path)
        
        if path_obj.is_dir():
            # Przetwórz wszystkie pliki w katalogu
            for file in path_obj.iterdir():
                if file.suffix.lower() in CONFIG["supported_formats"]:
                    all_results.extend(process_file(str(file)))
        elif path_obj.is_file():
            all_results.extend(process_file(str(path_obj)))
        else:
            logger.warning(f"Nie znaleziono: {path}")
    
    return all_results


# ============================================================================
# EKSPORT WYNIKÓW
# ============================================================================

def flatten_receipt(receipt: dict) -> dict:
    """Spłaszcza zagnieżdżony słownik do formatu CSV."""
    flat = {
        "plik": receipt.get("_plik_zrodlowy", ""),
        "sklep": receipt.get("sklep", ""),
        "adres": receipt.get("adres", ""),
        "nip": receipt.get("nip", ""),
        "data": receipt.get("data", ""),
        "godzina": receipt.get("godzina", ""),
        "suma": receipt.get("suma", ""),
        "platnosc": receipt.get("platnosc", ""),
        "numer_paragonu": receipt.get("numer_paragonu", ""),
        "uwagi": receipt.get("uwagi", ""),
        "blad": receipt.get("_blad", ""),
    }
    
    # Dodaj produkty jako string
    produkty = receipt.get("produkty", [])
    if produkty:
        produkty_str = "; ".join([
            f"{p.get('nazwa', '?')} x{p.get('ilosc', 1)} = {p.get('cena_razem', '?')} zł"
            for p in produkty if isinstance(p, dict)
        ])
        flat["produkty"] = produkty_str
        flat["liczba_produktow"] = len(produkty)
    else:
        flat["produkty"] = ""
        flat["liczba_produktow"] = 0
    
    return flat


def export_to_csv(results: list[dict], output_path: str):
    """Eksportuje wyniki do CSV."""
    if not results:
        logger.warning("Brak wyników do eksportu CSV")
        return
    
    flat_results = [flatten_receipt(r) for r in results]
    
    fieldnames = [
        "plik", "sklep", "adres", "nip", "data", "godzina",
        "suma", "platnosc", "numer_paragonu", "liczba_produktow",
        "produkty", "uwagi", "blad"
    ]
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_results)
    
    logger.info(f"Zapisano CSV: {output_path}")


def export_to_json(results: list[dict], output_path: str):
    """Eksportuje pełne wyniki do JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Zapisano JSON: {output_path}")


def export_products_csv(results: list[dict], output_path: str):
    """Eksportuje szczegółową listę produktów do CSV."""
    rows = []
    
    for receipt in results:
        base_info = {
            "plik": receipt.get("_plik_zrodlowy", ""),
            "sklep": receipt.get("sklep", ""),
            "data": receipt.get("data", ""),
        }
        
        produkty = receipt.get("produkty", [])
        if produkty:
            for p in produkty:
                if isinstance(p, dict):
                    row = {**base_info}
                    row["produkt"] = p.get("nazwa", "")
                    row["ilosc"] = p.get("ilosc", 1)
                    row["cena_jednostkowa"] = p.get("cena_jednostkowa", "")
                    row["cena_razem"] = p.get("cena_razem", "")
                    rows.append(row)
    
    if not rows:
        logger.warning("Brak produktów do eksportu")
        return
    
    fieldnames = ["plik", "sklep", "data", "produkt", "ilosc", 
                  "cena_jednostkowa", "cena_razem"]
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    logger.info(f"Zapisano produkty CSV: {output_path}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OCR paragonów z Qwen3-VL przez Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady użycia:
  python receipt_ocr.py paragon.jpg
  python receipt_ocr.py paragon.pdf
  python receipt_ocr.py ./paragony/
  python receipt_ocr.py *.jpg *.png
  python receipt_ocr.py ./paragony/ -o ./wyniki/
  python receipt_ocr.py paragon.jpg --polish    # Polski prompt
        """
    )
    
    parser.add_argument(
        "input",
        nargs="+",
        help="Pliki lub katalogi do przetworzenia"
    )
    
    parser.add_argument(
        "-o", "--output",
        default=CONFIG["output_dir"],
        help=f"Katalog wyjściowy (domyślnie: {CONFIG['output_dir']})"
    )
    
    parser.add_argument(
        "-m", "--model",
        default=CONFIG["model"],
        help=f"Model Ollama (domyślnie: {CONFIG['model']})"
    )
    
    parser.add_argument(
        "--dpi",
        type=int,
        default=CONFIG["pdf_dpi"],
        help=f"DPI dla konwersji PDF (domyślnie: {CONFIG['pdf_dpi']})"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Więcej informacji debugowania"
    )

    parser.add_argument(
        "-pl", "--polish",
        action="store_true",
        help="Użyj polskiego promptu (domyślnie: angielski)"
    )

    args = parser.parse_args()
    
    # Aktualizacja konfiguracji
    CONFIG["output_dir"] = args.output
    CONFIG["model"] = args.model
    CONFIG["pdf_dpi"] = args.dpi
    CONFIG["use_polish"] = args.polish

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Sprawdzenie wymagań
    if not OLLAMA_AVAILABLE:
        logger.error("Wymagana biblioteka 'ollama' nie jest zainstalowana!")
        return 1
    
    # Tworzenie katalogów
    ensure_dirs()
    
    # Przetwarzanie
    logger.info(f"Model: {CONFIG['model']}")
    logger.info(f"Prompt: {'polski' if CONFIG['use_polish'] else 'angielski'}")
    logger.info(f"Pliki wejściowe: {args.input}")
    logger.info("-" * 50)
    
    results = batch_process(args.input)
    
    if not results:
        logger.warning("Brak wyników do zapisania")
        return 1
    
    # Eksport
    output_dir = Path(CONFIG["output_dir"])
    
    csv_path = output_dir / CONFIG["csv_filename"]
    json_path = output_dir / CONFIG["json_filename"]
    products_path = output_dir / "produkty.csv"
    
    export_to_csv(results, str(csv_path))
    export_to_json(results, str(json_path))
    export_products_csv(results, str(products_path))
    
    # Podsumowanie
    logger.info("-" * 50)
    logger.info(f"Przetworzono: {len(results)} paragonów")
    
    sukces = sum(1 for r in results if "_blad" not in r)
    bledy = len(results) - sukces
    logger.info(f"Sukces: {sukces}, Błędy: {bledy}")
    
    suma_total = sum(
        r.get("suma", 0) or 0 
        for r in results 
        if isinstance(r.get("suma"), (int, float))
    )
    logger.info(f"Suma wszystkich paragonów: {suma_total:.2f} zł")
    
    return 0


if __name__ == "__main__":
    exit(main())
