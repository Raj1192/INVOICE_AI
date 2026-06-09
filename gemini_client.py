"""
gemini_client.py
----------------
Thin client for the Google Gemini REST API.

This module demonstrates the "API Integration" requirement explicitly:
  1. Authentication   -> API key sent as a query parameter / header
  2. API call         -> POST to the generateContent endpoint via `requests`
  3. Error handling   -> timeouts, HTTP errors, rate limits, retries
  4. Response parsing -> safe extraction of the text / JSON payload
"""

import base64
import json
import os
import re
import time

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3


class GeminiError(Exception):
    """Raised when the Gemini API call fails after all retries."""


def _get_api_key() -> str:
    """
    Authentication step.
    The key is read from an environment variable (or Streamlit secrets,
    which Streamlit exposes as env vars) — never hard-coded.
    """
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        # Fallback: Streamlit secrets (works on Streamlit Cloud)
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
    if not key:
        raise GeminiError(
            "GEMINI_API_KEY is not set. Add it to your environment "
            "or to .streamlit/secrets.toml"
        )
    return key


def call_gemini(prompt: str,
                image_bytes: bytes | None = None,
                image_mime: str = "image/png",
                expect_json: bool = False) -> str:
    """
    Make one call to Gemini and return the model's text output.

    Parameters
    ----------
    prompt      : the instruction / question for the model
    image_bytes : optional raw image bytes (used for OCR of invoice images)
    expect_json : if True, ask Gemini to return strict JSON

    Includes retry logic with exponential backoff for transient errors
    (HTTP 429 rate limits and 5xx server errors).
    """
    api_key = _get_api_key()
    url = f"{BASE_URL}/{GEMINI_MODEL}:generateContent"

    # Build the request body (multimodal if an image is attached)
    parts: list[dict] = [{"text": prompt}]
    if image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": image_mime,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        })

    body: dict = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.2},
    }
    if expect_json:
        body["generationConfig"]["response_mime_type"] = "application/json"

    last_error: str = "unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                params={"key": api_key},          # <-- authentication
                json=body,
                timeout=TIMEOUT_SECONDS,
            )

            # --- Error handling -------------------------------------------
            if response.status_code == 200:
                return _extract_text(response.json())

            if response.status_code in (429, 500, 502, 503):
                # Transient: wait and retry (exponential backoff)
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                time.sleep(2 ** attempt)
                continue

            # Permanent client error (bad key, bad request, ...)
            raise GeminiError(
                f"Gemini API error {response.status_code}: {response.text[:300]}"
            )

        except requests.exceptions.Timeout:
            last_error = "request timed out"
            time.sleep(2 ** attempt)
        except requests.exceptions.ConnectionError as exc:
            last_error = f"connection error: {exc}"
            time.sleep(2 ** attempt)

    raise GeminiError(f"Gemini call failed after {MAX_RETRIES} retries ({last_error})")


def _extract_text(payload: dict) -> str:
    """
    Response processing step.
    Safely navigate the Gemini response structure and return the text.
    """
    try:
        candidates = payload["candidates"]
        parts = candidates[0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        # Model may have been blocked by safety filters or returned nothing
        block = payload.get("promptFeedback", {}).get("blockReason")
        if block:
            raise GeminiError(f"Request blocked by Gemini safety filter: {block}")
        raise GeminiError(f"Unexpected Gemini response shape: {json.dumps(payload)[:300]}")


def parse_json_response(raw: str) -> dict:
    """
    Robustly parse JSON from an LLM response.
    Strips markdown fences and finds the first JSON object if the model
    added extra prose around it.
    """
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise GeminiError(f"Model did not return valid JSON: {raw[:300]}")
