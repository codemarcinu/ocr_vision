"""Preprocessing obrazów paragonów dla lepszego OCR.

Preprocessing jest OPCJONALNY - modele vision (DeepSeek-OCR, qwen2.5vl) są trenowane
na surowych obrazach i często radzą sobie lepiej bez preprocessingu.

Używaj preprocessingu gdy:
- Obraz jest bardzo ciemny/jasny
- Paragon jest zmięty lub zagnieciony
- Tło jest nierównomierne (cienie)
- Używasz PaddleOCR (klasyczny OCR, nie vision)

NIE używaj preprocessingu gdy:
- Obraz jest dobrej jakości
- Używasz modelu vision (DeepSeek-OCR, qwen2.5vl)
"""

import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Próbuj importować OpenCV, ale nie wymagaj
try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    logger.warning("OpenCV niedostępny - preprocessing obrazów wyłączony")


def is_preprocessing_available() -> bool:
    """Sprawdź czy preprocessing jest dostępny (OpenCV zainstalowany)."""
    return OPENCV_AVAILABLE


def analyze_image_quality(image_path: Path) -> dict:
    """Analizuj jakość obrazu i zwróć metryki.

    Returns:
        dict z metrykami:
        - brightness: średnia jasność (0-255)
        - contrast: odchylenie standardowe jasności
        - sharpness: miara ostrości (wyższa = ostrzejszy)
        - needs_preprocessing: bool - czy preprocessing jest zalecany
    """
    if not OPENCV_AVAILABLE:
        return {"needs_preprocessing": False, "reason": "OpenCV niedostępny"}

    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return {"needs_preprocessing": False, "reason": "Nie można wczytać obrazu"}

        # Konwersja do skali szarości
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Jasność (średnia)
        brightness = float(np.mean(gray))

        # Kontrast (odchylenie standardowe)
        contrast = float(np.std(gray))

        # Ostrość (Laplacian variance)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(laplacian.var())

        # Decyzja czy preprocessing jest potrzebny
        needs_preprocessing = False
        reasons = []

        if brightness < 80:
            needs_preprocessing = True
            reasons.append(f"za ciemny ({brightness:.0f})")
        elif brightness > 200:
            needs_preprocessing = True
            reasons.append(f"za jasny ({brightness:.0f})")

        if contrast < 40:
            needs_preprocessing = True
            reasons.append(f"niski kontrast ({contrast:.0f})")

        if sharpness < 100:
            needs_preprocessing = True
            reasons.append(f"nieostry ({sharpness:.0f})")

        return {
            "brightness": brightness,
            "contrast": contrast,
            "sharpness": sharpness,
            "needs_preprocessing": needs_preprocessing,
            "reasons": reasons,
        }

    except Exception as e:
        logger.error(f"Błąd analizy obrazu: {e}")
        return {"needs_preprocessing": False, "reason": str(e)}


def preprocess_receipt(
    image_path: Path,
    output_path: Optional[Path] = None,
    force: bool = False,
) -> Tuple[Path, dict]:
    """Preprocessing obrazu paragonu dla lepszego OCR.

    Args:
        image_path: Ścieżka do obrazu wejściowego
        output_path: Ścieżka do obrazu wyjściowego (domyślnie: obok oryginału z sufiksem _preprocessed)
        force: Wymuś preprocessing nawet jeśli obraz jest dobrej jakości

    Returns:
        Tuple (ścieżka do przetworzonego obrazu, metryki)
    """
    if not OPENCV_AVAILABLE:
        logger.warning("OpenCV niedostępny - zwracam oryginalny obraz")
        return image_path, {"preprocessed": False, "reason": "OpenCV niedostępny"}

    # Analizuj jakość
    quality = analyze_image_quality(image_path)

    if not force and not quality.get("needs_preprocessing", False):
        logger.info(f"Obraz dobrej jakości - pomijam preprocessing")
        return image_path, {"preprocessed": False, **quality}

    logger.info(f"Preprocessing obrazu: {quality.get('reasons', [])}")

    try:
        # Wczytaj obraz
        img = cv2.imread(str(image_path))
        if img is None:
            return image_path, {"preprocessed": False, "reason": "Nie można wczytać"}

        # Konwersja do skali szarości
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. Odszumianie (bilateral filter - zachowuje krawędzie)
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        # 2. Korekcja jasności i kontrastu (CLAHE - adaptacyjne)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 3. Binaryzacja adaptacyjna (dla paragonów z cieniami)
        # Używamy większego bloku dla paragonów (tekst jest gęsty)
        binary = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            15,  # rozmiar bloku
            8,   # stała odejmowana od średniej
        )

        # 4. Morfologia - usuń drobne szumy
        kernel = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # Zapisz wynik
        if output_path is None:
            output_path = image_path.parent / f"{image_path.stem}_preprocessed{image_path.suffix}"

        cv2.imwrite(str(output_path), cleaned)

        logger.info(f"Preprocessing zakończony: {output_path}")

        return output_path, {
            "preprocessed": True,
            "original_path": str(image_path),
            "output_path": str(output_path),
            **quality,
        }

    except Exception as e:
        logger.error(f"Błąd preprocessingu: {e}")
        return image_path, {"preprocessed": False, "reason": str(e)}


def preprocess_for_paddle(image_path: Path) -> Path:
    """Preprocessing specjalnie dla PaddleOCR.

    PaddleOCR (klasyczny OCR) korzysta z preprocessingu bardziej niż modele vision.
    Ta funkcja ZAWSZE przetwarza obraz.
    """
    if not OPENCV_AVAILABLE:
        return image_path

    output_path = image_path.parent / f"{image_path.stem}_paddle{image_path.suffix}"
    processed, _ = preprocess_receipt(image_path, output_path, force=True)
    return processed


def auto_rotate_receipt(image_path: Path) -> Tuple[Path, float]:
    """Automatycznie obróć paragon do orientacji pionowej.

    Paragony są zazwyczaj pionowe (wysokość > szerokość).
    Jeśli obraz jest poziomy, obróć go o 90 stopni.

    Returns:
        Tuple (ścieżka do obrazu, kąt obrotu w stopniach)
    """
    if not OPENCV_AVAILABLE:
        return image_path, 0.0

    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return image_path, 0.0

        height, width = img.shape[:2]

        # Paragon powinien być pionowy
        if width > height * 1.2:  # znacząco szerszy niż wysoki
            # Obróć o 90 stopni w prawo
            rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

            output_path = image_path.parent / f"{image_path.stem}_rotated{image_path.suffix}"
            cv2.imwrite(str(output_path), rotated)

            logger.info(f"Obrócono paragon o 90°: {output_path}")
            return output_path, 90.0

        return image_path, 0.0

    except Exception as e:
        logger.error(f"Błąd auto-rotacji: {e}")
        return image_path, 0.0
