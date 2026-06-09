"""
extractors.py
-------------
Step 1 of the pipeline: get raw text out of whatever the user uploads.

Supported inputs:
  * PDF        -> pdfplumber (digital PDFs); falls back to Gemini Vision
                  for scanned PDFs that contain no text layer
  * Image      -> Gemini Vision acts as the OCR engine (no tesseract
                  system dependency needed, which keeps cloud deploys simple)
  * Text file  -> read directly
"""

import io

import pdfplumber

from gemini_client import call_gemini

OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text visible in this document "
    "image exactly as written, preserving numbers, dates and line items. "
    "Return only the transcribed text, no commentary."
)


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Route the uploaded file to the right extractor based on extension."""
    name = filename.lower()

    if name.endswith(".pdf"):
        return _extract_pdf(file_bytes)

    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        mime = "image/png" if name.endswith(".png") else "image/jpeg"
        if name.endswith(".webp"):
            mime = "image/webp"
        return call_gemini(OCR_PROMPT, image_bytes=file_bytes, image_mime=mime)

    if name.endswith((".txt", ".md", ".csv")):
        return file_bytes.decode("utf-8", errors="replace")

    raise ValueError(f"Unsupported file type: {filename}")


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF; OCR each page with Gemini if it has no text layer."""
    text_pages: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_pages.append(page_text)
            else:
                # Scanned page: render to image and OCR with Gemini Vision
                img = page.to_image(resolution=200).original
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                text_pages.append(
                    call_gemini(OCR_PROMPT, image_bytes=buf.getvalue())
                )
    return "\n\n".join(text_pages).strip()
