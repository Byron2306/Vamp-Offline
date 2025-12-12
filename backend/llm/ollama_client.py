from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "45"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "320"))


def query_ollama(prompt: str, *, model: Optional[str] = None, format: Optional[str] = None,
                 timeout: Optional[float] = None, num_predict: Optional[int] = None) -> str:
    """Send a prompt to an Ollama instance and return the raw response text.

    Parameters allow overrides but default to environment-configured settings.
    """
    payload: Dict[str, Any] = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(os.getenv("VAMP_LLM_TEMPERATURE", "0.25")),
            "num_predict": num_predict if num_predict is not None else OLLAMA_NUM_PREDICT,
        },
    }
    if format:
        payload["format"] = format

    url = f"{OLLAMA_HOST}/api/generate"
    response = requests.post(url, json=payload, timeout=timeout or OLLAMA_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return (data.get("response") or "").strip()


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("Empty Ollama response")

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if 0 <= start < end:
        candidate = cleaned[start : end + 1]
        return json.loads(candidate)

    raise ValueError("No JSON object found in Ollama response")
