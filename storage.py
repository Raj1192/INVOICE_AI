"""
storage.py
----------
Step 5 of the pipeline: persist results.

Uses SQLite — zero-configuration, ships with Python, and is perfectly
adequate for a demo. The same interface could be backed by Postgres in
production without changing the rest of the code.

Also implements simple AUDIT LOGGING (bonus requirement): every pipeline
event is appended to an audit_log table with a timestamp.
"""

import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "invoices.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                filename      TEXT,
                vendor        TEXT,
                invoice_number TEXT,
                invoice_date  TEXT,
                amount        TEXT,
                summary       TEXT,
                risk_level    TEXT,
                risk_reasons  TEXT,
                validation    TEXT,
                raw_text      TEXT,
                created_at    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event      TEXT,
                detail     TEXT,
                created_at TEXT
            )
        """)


def log_event(event: str, detail: str = "") -> None:
    """Append one line to the audit log."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (event, detail, created_at) VALUES (?, ?, ?)",
            (event, detail, datetime.now(timezone.utc).isoformat()),
        )


def save_invoice(record: dict) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO invoices
               (filename, vendor, invoice_number, invoice_date, amount,
                summary, risk_level, risk_reasons, validation, raw_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("filename", ""),
                record.get("vendor", ""),
                record.get("invoice_number", ""),
                record.get("invoice_date", ""),
                record.get("amount", ""),
                record.get("summary", ""),
                record.get("risk_level", ""),
                json.dumps(record.get("risk_reasons", [])),
                json.dumps(record.get("validation", {})),
                record.get("raw_text", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def list_invoices() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_audit_log(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
