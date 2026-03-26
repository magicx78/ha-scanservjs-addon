"""
Dokumenten-Chunker: PDF, JPG, PNG, TIFF, TXT → Text-Chunks mit Metadaten.

Unterstützte Formate:
  - PDF: Erst pdfminer (Text-Layer), dann Tesseract-OCR als Fallback
  - JPG/PNG/TIFF: Tesseract-OCR direkt
  - TXT: Direktes Lesen

Chunk-Größe: 800 Zeichen, Overlap: 150 Zeichen.
"""

import hashlib
import os
from pathlib import Path

import pytesseract
from PIL import Image


CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".txt"}


def _split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Teilt langen Text in überlappende Chunks."""
    if not text or not text.strip():
        return []
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap

    return chunks


def _extract_text_pdf(path: Path, ocr_lang: str) -> list[tuple[int, str]]:
    """Extrahiert Text aus PDF. Gibt Liste von (Seite, Text) zurück.

    Versucht zuerst pdfminer (Text-Layer), dann Tesseract-OCR als Fallback.
    """
    pages: list[tuple[int, str]] = []

    # Versuch 1: pdfminer (kein OCR nötig wenn Text-Layer vorhanden)
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer

        page_num = 0
        for page_layout in extract_pages(str(path)):
            page_num += 1
            page_text = ""
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    page_text += element.get_text()
            if page_text.strip():
                pages.append((page_num, page_text))
    except Exception:
        pages = []

    # Fallback: Tesseract-OCR via pdf2image
    if not pages:
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(str(path), dpi=200)
            for i, img in enumerate(images, start=1):
                text = pytesseract.image_to_string(img, lang=ocr_lang)
                if text.strip():
                    pages.append((i, text))
        except Exception:
            pass

    return pages


def _extract_text_image(path: Path, ocr_lang: str) -> str:
    """Extrahiert Text aus einem Bild via Tesseract-OCR."""
    try:
        img = Image.open(path)
        return pytesseract.image_to_string(img, lang=ocr_lang)
    except Exception:
        return ""


def _extract_text_txt(path: Path) -> str:
    """Liest Textdatei."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def calculate_md5(path: Path) -> str:
    """Berechnet MD5-Hash einer Datei für Duplikat-Erkennung."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class DocumentChunker:
    def __init__(self, ocr_lang: str = "deu+eng"):
        self.ocr_lang = ocr_lang

    def chunk_file(self, path: Path) -> list[dict]:
        """Zerlegt eine Datei in Text-Chunks mit Metadaten.

        Gibt Liste von Dicts zurück:
        {
            "text": str,
            "page": int,
            "chunk_index": int,
            "filename": str,
            "source": str,    # absoluter Pfad
            "md5": str,
        }
        """
        path = Path(path)
        suffix = path.suffix.lower()
        filename = path.name
        md5 = calculate_md5(path)
        chunks = []

        if suffix == ".pdf":
            pages = _extract_text_pdf(path, self.ocr_lang)
            for page_num, page_text in pages:
                text_chunks = _split_text(page_text)
                for idx, chunk_text in enumerate(text_chunks):
                    chunks.append({
                        "text": chunk_text,
                        "page": page_num,
                        "chunk_index": idx,
                        "filename": filename,
                        "source": str(path),
                        "md5": md5,
                    })

        elif suffix in {".jpg", ".jpeg", ".png", ".tiff", ".tif"}:
            text = _extract_text_image(path, self.ocr_lang)
            text_chunks = _split_text(text)
            for idx, chunk_text in enumerate(text_chunks):
                chunks.append({
                    "text": chunk_text,
                    "page": 1,
                    "chunk_index": idx,
                    "filename": filename,
                    "source": str(path),
                    "md5": md5,
                })

        elif suffix == ".txt":
            text = _extract_text_txt(path)
            text_chunks = _split_text(text)
            for idx, chunk_text in enumerate(text_chunks):
                chunks.append({
                    "text": chunk_text,
                    "page": 1,
                    "chunk_index": idx,
                    "filename": filename,
                    "source": str(path),
                    "md5": md5,
                })

        return chunks

    @staticmethod
    def is_supported(path: Path) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS
