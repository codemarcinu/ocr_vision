#!/usr/bin/env python3
"""
Quick Receipt OCR - Prosty skrypt do szybkiego OCR pojedynczego paragonu
Użycie: python quick_ocr.py paragon.jpg
"""

import sys
import json
import ollama

PROMPT = """Przeanalizuj ten paragon i wyodrębnij dane w formacie JSON:
{
    "sklep": "nazwa",
    "data": "YYYY-MM-DD", 
    "produkty": [{"nazwa": "...", "cena": 0.00}],
    "suma": 0.00
}
Zwróć TYLKO JSON, bez dodatkowego tekstu."""

def ocr_receipt(image_path: str) -> dict:
    """OCR pojedynczego paragonu."""
    response = ollama.chat(
        model='qwen3-vl:8b',
        messages=[{
            'role': 'user',
            'content': PROMPT,
            'images': [image_path]
        }],
        options={'temperature': 0.1}
    )
    
    text = response['message']['content']
    
    # Wyczyść markdown
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    
    return json.loads(text.strip())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python quick_ocr.py <ścieżka_do_obrazu>")
        sys.exit(1)
    
    result = ocr_receipt(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
