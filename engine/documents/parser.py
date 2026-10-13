from hashlib import sha256
from pathlib import Path

import pymupdf
import pdfplumber
from engine.ipc.contracts import AlmaError, ErrorCode

MAX_BYTES = 32 * 1024 * 1024
MAX_PAGES = 200

# Keep native library diagnostics off the JSONL transport too.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


def parse_pdf(path: Path, enable_ocr=False):
    if path.stat().st_size > MAX_BYTES:
        raise AlmaError(ErrorCode.PDF_PARSE_FAILED, "pdf_size")
    digest = sha256(path.read_bytes()).hexdigest()
    pages = []
    try:
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass or not 0 < len(pdf) <= MAX_PAGES:
                raise AlmaError(ErrorCode.PDF_PARSE_FAILED, "pdf_limits")
            for number, page in enumerate(pdf, 1):
                text = page.get_text("text", sort=True)
                blocks = page.get_text("blocks", sort=True)
                method = "NATIVE"
                # Group words by PDF block/line, preserving column adjacency and coordinates.
                groups = {}
                for word in page.get_text('words',sort=True):
                    groups.setdefault((word[5],word[6]),[]).append(word)
                rows=[]
                for words in groups.values():
                    rows.append({'text':' '.join(w[4] for w in words),
                        'bbox':[min(w[0] for w in words),min(w[1] for w in words),max(w[2] for w in words),max(w[3] for w in words)]})
                # Different table cells can be separate PDF blocks on the same visual row.
                aligned=[]
                for row in sorted(rows,key=lambda r:(round(r['bbox'][1],1),r['bbox'][0])):
                    if aligned and abs(aligned[-1]['bbox'][1]-row['bbox'][1])<2:
                        previous=aligned[-1]
                        previous['text']+=' | '+row['text']
                        previous['bbox'][2]=max(previous['bbox'][2],row['bbox'][2])
                        previous['bbox'][3]=max(previous['bbox'][3],row['bbox'][3])
                    else: aligned.append(row)
                if not usable(text):
                    with pdfplumber.open(path) as fallback:
                        text = fallback.pages[number - 1].extract_text() or ""
                    method = "PDFPLUMBER"
                if not usable(text):
                    text = ocr_page(page) if enable_ocr else ""
                    method = "OCR" if text else "UNREADABLE"
                pages.append({"page": number, "text": text[:200_000], "method": method,
                              "rows": aligned if method=='NATIVE' else [],
                              "blocks": [{"bbox": list(b[:4]), "text": b[4]} for b in blocks if b[6] == 0]})
        return {"sha256": digest, "pages": pages}
    except AlmaError:
        raise
    except Exception:
        raise AlmaError(ErrorCode.PDF_PARSE_FAILED, "parsing") from None


def usable(text):
    return sum(c.isalnum() for c in text) >= 12 and '\ufffd' not in text


def ocr_page(page):
    """OCR is perception only. Confidence stays OCR_LOW until calibrated."""
    try:
        import cv2
        import numpy as np
        import pytesseract
        if page.rect.width * page.rect.height > 2_000_000:
            raise ValueError("Page limit")
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        img = cv2.fastNlMeansDenoising(img, h=10)
        img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        coords = cv2.findNonZero(255 - img)
        if coords is None:
            return ""
        angle = cv2.minAreaRect(coords)[-1]
        if angle > 45:
            angle -= 90
        if abs(angle) <= 10:
            matrix = cv2.getRotationMatrix2D((pix.width / 2, pix.height / 2), angle, 1)
            img = cv2.warpAffine(img, matrix, (pix.width, pix.height), borderValue=255)
        return pytesseract.image_to_string(img, lang="por", timeout=30)
    except Exception:
        raise AlmaError(ErrorCode.OCR_FAILED, "ocr") from None
