"""
app.py
------
Invoice AI — Streamlit front-end.

Three views:
  1. Process Document  -> upload, run the pipeline, see live progress + results
  2. Dashboard         -> all processed invoices + audit log
  3. AI Assistant      -> chat grounded in the processed document data

Run locally:   streamlit run app.py
"""

import json

import pandas as pd
import streamlit as st

import storage
from gemini_client import GeminiError
from pipeline import answer_question, process_document

st.set_page_config(page_title="Invoice AI", page_icon="🧾", layout="wide")
storage.init_db()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "current_record" not in st.session_state:
    st.session_state.current_record = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

RISK_COLORS = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}

st.title("🧾 Invoice AI — Document Automation Pipeline")
st.caption(
    "Upload an invoice (PDF / image / text) → automatic extraction, validation, "
    "AI summary, risk detection — then ask the assistant questions about it."
)

tab_process, tab_dashboard, tab_chat = st.tabs(
    ["① Process Document", "② Dashboard", "③ AI Assistant"]
)

# ===========================================================================
# Tab 1 — Upload & process
# ===========================================================================
with tab_process:
    uploaded = st.file_uploader(
        "Upload a document",
        type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md", "csv"],
        help="PDF, invoice image, or plain-text document",
    )

    if uploaded and st.button("▶ Run automation pipeline", type="primary"):
        status = st.status("Running pipeline...", expanded=True)
        step_names = {
            1: "Step 1/5 — Text extraction (OCR / parsing)",
            2: "Step 2/5 — Structured field extraction (LLM)",
            3: "Step 3/5 — Rule-based validation",
            4: "Step 4/5 — AI summary & risk assessment (LLM)",
            5: "Step 5/5 — Storing result",
        }

        def progress(step, msg):
            status.write(f"**{step_names[step]}** — {msg}")

        try:
            record = process_document(uploaded.getvalue(), uploaded.name, progress)
            st.session_state.current_record = record
            st.session_state.chat_history = []
            status.update(label="Pipeline complete ✅", state="complete")
        except GeminiError as e:
            status.update(label="LLM call failed", state="error")
            st.error(f"Gemini API error: {e}")
        except Exception as e:
            status.update(label="Pipeline failed", state="error")
            st.error(f"Processing error: {e}")

    # ---- Results -----------------------------------------------------------
    record = st.session_state.current_record
    if record:
        st.divider()
        st.subheader("Extraction result")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vendor", record["vendor"] or "—")
        c2.metric("Invoice #", record["invoice_number"] or "—")
        c3.metric("Date", record["invoice_date"] or "—")
        c4.metric("Amount", record["amount"] or "—")

        risk = record["risk_level"]
        st.markdown(f"### Risk level: {RISK_COLORS.get(risk, '⚪')} **{risk}**")
        for reason in record.get("risk_reasons", []):
            st.markdown(f"- {reason}")

        st.markdown("**AI summary**")
        st.info(record["summary"] or "No summary generated.")

        validation = record.get("validation", {})
        if validation.get("missing_fields") or validation.get("issues"):
            st.markdown("**Validation findings**")
            for f in validation.get("missing_fields", []):
                st.warning(f"Missing field: `{f}`")
            for issue in validation.get("issues", []):
                st.warning(issue)
        else:
            st.success("All required fields present and valid.")

        with st.expander("JSON output (task spec format)"):
            st.code(json.dumps(record["output"], indent=2), language="json")
        with st.expander("Raw extracted text"):
            st.text(record["raw_text"][:5000])

# ===========================================================================
# Tab 2 — Dashboard
# ===========================================================================
with tab_dashboard:
    invoices = storage.list_invoices()
    if not invoices:
        st.info("No documents processed yet. Upload one in the first tab.")
    else:
        st.subheader(f"Processed documents ({len(invoices)})")
        df = pd.DataFrame(invoices)[
            ["id", "created_at", "filename", "vendor",
             "invoice_number", "invoice_date", "amount", "risk_level"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Simple risk distribution metric row
        counts = df["risk_level"].value_counts()
        m1, m2, m3 = st.columns(3)
        m1.metric("🟢 Low risk", int(counts.get("LOW", 0)))
        m2.metric("🟡 Medium risk", int(counts.get("MEDIUM", 0)))
        m3.metric("🔴 High risk", int(counts.get("HIGH", 0)))

    with st.expander("Audit log (last 100 events)"):
        log = storage.get_audit_log()
        if log:
            st.dataframe(
                pd.DataFrame(log)[["created_at", "event", "detail"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.write("Audit log is empty.")

# ===========================================================================
# Tab 3 — AI Assistant (chat)
# ===========================================================================
with tab_chat:
    record = st.session_state.current_record
    if not record:
        st.info("Process a document first — then ask questions about it here.")
    else:
        st.caption(
            f"Answering questions about **{record['filename']}** "
            f"(invoice {record['invoice_number'] or 'n/a'})"
        )
        st.markdown(
            "Try: *What is the invoice amount?* · *What risks were detected?* · "
            "*Summarize this invoice.* · *What fields are missing?*"
        )

        for role, msg in st.session_state.chat_history:
            with st.chat_message(role):
                st.markdown(msg)

        question = st.chat_input("Ask about the processed document...")
        if question:
            st.session_state.chat_history.append(("user", question))
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                try:
                    with st.spinner("Thinking..."):
                        answer = answer_question(question, record)
                except GeminiError as e:
                    answer = f"Sorry, the LLM call failed: {e}"
                st.markdown(answer)
            st.session_state.chat_history.append(("assistant", answer))
