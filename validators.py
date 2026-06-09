"""
validators.py
-------------
Step 3 of the pipeline: deterministic, rule-based validation of the
structured fields the LLM extracted.

Keeping validation OUTSIDE the LLM is a deliberate production decision:
rules are cheap, auditable and never hallucinate. The validation result
also feeds the risk assessment.
"""

import re
from datetime import datetime

REQUIRED_FIELDS = ["vendor", "invoice_number", "invoice_date", "amount"]

DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
    "%d.%m.%Y", "%B %d, %Y", "%d %B %Y", "%b %d, %Y",
]


def validate(fields: dict) -> dict:
    """
    Returns:
        {
          "is_valid": bool,
          "missing_fields": [...],
          "issues": [...],          # human-readable problems found
        }
    """
    missing = [
        f for f in REQUIRED_FIELDS
        if not str(fields.get(f, "")).strip()
        or str(fields.get(f, "")).strip().lower() in ("null", "none", "n/a", "unknown")
    ]
    issues: list[str] = []

    # --- amount must parse to a positive number ---------------------------
    amount_raw = str(fields.get("amount", ""))
    amount_clean = re.sub(r"[^\d.,-]", "", amount_raw).replace(",", "")
    try:
        amount_value = float(amount_clean) if amount_clean else None
        if amount_value is not None and amount_value <= 0:
            issues.append(f"Amount is not positive: {amount_raw}")
    except ValueError:
        amount_value = None
        if "amount" not in missing:
            issues.append(f"Amount could not be parsed as a number: {amount_raw}")

    # --- date must parse and not be in the far future ----------------------
    date_raw = str(fields.get("invoice_date", "")).strip()
    parsed_date = _parse_date(date_raw)
    if date_raw and "invoice_date" not in missing:
        if parsed_date is None:
            issues.append(f"Invoice date not in a recognised format: {date_raw}")
        elif parsed_date.year > datetime.now().year + 1:
            issues.append(f"Invoice date is suspiciously far in the future: {date_raw}")

    # --- invoice number sanity check ---------------------------------------
    inv_no = str(fields.get("invoice_number", "")).strip()
    if inv_no and len(inv_no) > 40:
        issues.append("Invoice number is unusually long — possible extraction error")

    return {
        "is_valid": not missing and not issues,
        "missing_fields": missing,
        "issues": issues,
    }


def _parse_date(raw: str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None
