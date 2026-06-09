"""
pipeline.py
-----------
The AUTOMATION FLOW (orchestration logic). Each uploaded document moves
through a fixed sequence of stages:

    Upload Document
        |
        v
    1. extract_text()      (extractors.py  — OCR / parsing)
        |
        v
    2. extract_fields()    (LLM — structured information)
        |
        v
    3. validate()          (validators.py  — rule-based checks)
        |
        v
    4. summarize + risk    (LLM — summary & risk explanation)
        |
        v
    5. save_invoice()      (storage.py — SQLite + audit log)
        |
        v
    Dashboard / Chat assistant

Every stage logs to the audit trail, and the function reports progress
through an optional callback so the UI can show a live status.
"""

import json

import storage
from extractors import extract_text
from gemini_client import call_gemini, parse_json_response
from validators import validate

EXTRACTION_PROMPT = """You are an information extraction system for invoices and business documents.

From the document text below, extract these fields and return ONLY a JSON object
(no markdown, no commentary) with exactly these keys:

{
  "vendor": "company or person issuing the invoice, empty string if not found",
  "invoice_number": "invoice/reference number, empty string if not found",
  "invoice_date": "date of the invoice as written, empty string if not found",
  "amount": "total amount due including currency symbol, empty string if not found",
  "currency": "ISO currency code if identifiable, else empty string",
  "line_items": ["short description of each line item, max 10"]
}

Document text:
---
{DOCUMENT}
---"""

RISK_PROMPT = """You are a finance risk analyst. Analyse this invoice data and validation result.

Extracted fields:
{FIELDS}

Rule-based validation result:
{VALIDATION}

Document text (may be truncated):
---
{DOCUMENT}
---

Consider: missing fields, unparseable values, unusual amounts, vague descriptions,
round-number amounts, pressure/urgency language, mismatched details — anything a
human reviewer would flag.

Return ONLY a JSON object with exactly these keys:
{
  "summary": "2-3 sentence plain-English summary of the document",
  "risk_level": "LOW or MEDIUM or HIGH",
  "risk_reasons": ["short bullet reasons for the chosen risk level"]
}"""


def process_document(file_bytes: bytes, filename: str, progress=None) -> dict:
    """
    Run the full automation pipeline on one uploaded file.
    `progress` is an optional callback: progress(step_number, message).
    Returns the final record (also persisted to SQLite).
    """
    def report(step, msg):
        if progress:
            progress(step, msg)

    storage.init_db()
    storage.log_event("upload", filename)

    # ---- Step 1: text extraction ------------------------------------------
    report(1, "Extracting text (OCR / parsing)...")
    raw_text = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("No text could be extracted from this document.")
    storage.log_event("text_extracted", f"{filename}: {len(raw_text)} chars")

    # ---- Step 2: structured extraction with the LLM ------------------------
    report(2, "Extracting structured fields with Gemini...")
    prompt = EXTRACTION_PROMPT.replace("{DOCUMENT}", raw_text[:15000])
    fields = parse_json_response(call_gemini(prompt, expect_json=True))
    storage.log_event("fields_extracted", json.dumps(fields)[:500])

    # ---- Step 3: rule-based validation -------------------------------------
    report(3, "Validating extracted fields...")
    validation = validate(fields)
    storage.log_event("validated", json.dumps(validation))

    # ---- Step 4: AI summary + risk assessment ------------------------------
    report(4, "Generating AI summary and risk assessment...")
    risk_prompt = (
        RISK_PROMPT
        .replace("{FIELDS}", json.dumps(fields, indent=2))
        .replace("{VALIDATION}", json.dumps(validation, indent=2))
        .replace("{DOCUMENT}", raw_text[:8000])
    )
    risk = parse_json_response(call_gemini(risk_prompt, expect_json=True))

    # ---- Step 5: store the result ------------------------------------------
    report(5, "Storing result...")
    record = {
        "filename": filename,
        "vendor": fields.get("vendor", ""),
        "invoice_number": fields.get("invoice_number", ""),
        "invoice_date": fields.get("invoice_date", ""),
        "amount": fields.get("amount", ""),
        "summary": risk.get("summary", ""),
        "risk_level": risk.get("risk_level", "MEDIUM"),
        "risk_reasons": risk.get("risk_reasons", []),
        "validation": validation,
        "raw_text": raw_text,
    }
    record["id"] = storage.save_invoice(record)
    storage.log_event("stored", f"invoice id={record['id']}")

    # The exact output contract required by the task spec:
    record["output"] = {
        "vendor": record["vendor"],
        "invoice_number": record["invoice_number"],
        "invoice_date": record["invoice_date"],
        "amount": record["amount"],
        "summary": record["summary"],
        "risk_level": record["risk_level"],
    }
    return record


def answer_question(question: str, record: dict) -> str:
    """
    AI Assistant: answer user questions grounded ONLY in the processed
    document data (fields, validation, risk, raw text).
    """
    context = {
        "vendor": record.get("vendor"),
        "invoice_number": record.get("invoice_number"),
        "invoice_date": record.get("invoice_date"),
        "amount": record.get("amount"),
        "summary": record.get("summary"),
        "risk_level": record.get("risk_level"),
        "risk_reasons": record.get("risk_reasons"),
        "validation": record.get("validation"),
    }
    prompt = f"""You are an invoice assistant. Answer the user's question using ONLY
the processed document data below. If the answer is not in the data, say so —
do not invent information. Keep answers short and factual.

Processed data:
{json.dumps(context, indent=2)}

Original document text (truncated):
---
{str(record.get("raw_text", ""))[:6000]}
---

User question: {question}"""
    storage.log_event("chat_question", question[:200])
    return call_gemini(prompt)
