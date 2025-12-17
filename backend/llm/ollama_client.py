from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional

try:
    import requests
except Exception as exc:  # pragma: no cover - handled at runtime
    requests = None
    _REQUESTS_IMPORT_ERROR = exc


def _get_ollama_host():
    """Determine the best Ollama host URL for the current environment."""
    # If explicitly set, use that
    if "OLLAMA_HOST" in os.environ:
        return os.getenv("OLLAMA_HOST").rstrip("/")
    
    # Try multiple potential hosts for dev containers
    potential_hosts = [
        "http://host.docker.internal:11434",  # Docker Desktop
        "http://172.17.0.1:11434",           # Docker default bridge
        "http://10.0.0.1:11434",             # Codespaces gateway
        "http://127.0.0.1:11434",            # Local fallback
    ]
    
    if requests:
        for host in potential_hosts:
            try:
                resp = requests.get(f"{host}/api/tags", timeout=2)
                if resp.status_code == 200:
                    return host
            except:
                continue
    
    # Default fallback
    return "http://host.docker.internal:11434"


OLLAMA_HOST = _get_ollama_host()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = max(180.0, float(os.getenv("OLLAMA_TIMEOUT", "240")))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "320"))
OLLAMA_RETRIES = int(os.getenv("OLLAMA_RETRIES", "2"))
OLLAMA_BACKOFFS = [2, 6]


def query_ollama(prompt: str, *, model: Optional[str] = None, format: Optional[str] = None,
                 timeout: Optional[float] = None, num_predict: Optional[int] = None) -> str:
    """Send a prompt to an Ollama instance and return the raw response text.

    Parameters allow overrides but default to environment-configured settings.
    """
    if requests is None:
        raise RuntimeError(
            "The 'requests' dependency is required for Ollama calls; install it to continue."
        )
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

    last_error: Optional[Exception] = None
    attempts = max(0, OLLAMA_RETRIES) + 1
    for attempt in range(attempts):
        try:
            response = requests.post(url, json=payload, timeout=timeout or OLLAMA_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            return (data.get("response") or "").strip()
        except Exception as exc:  # requests.RequestException | json.JSONDecodeError
            last_error = exc
            if attempt < attempts - 1:
                backoff_idx = min(attempt, len(OLLAMA_BACKOFFS) - 1)
                time.sleep(OLLAMA_BACKOFFS[backoff_idx])
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Unknown Ollama error")


def _balanced_brace_slice(text: str) -> str:
    depth = 0
    start = -1
    for idx, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                return text[start : idx + 1]
    return ""


def _repair_json_string(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r",\s*(\}|\])", r"\1", repaired)
    repaired = re.sub(r"'", '"', repaired)
    return repaired


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return "AI_FAILED"  # type: ignore[return-value]

    def _attempt_parse(candidate: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(candidate)
        except Exception:
            repaired = _repair_json_string(candidate)
            try:
                return json.loads(repaired)
            except Exception:
                return None

    direct = _attempt_parse(cleaned)
    if direct is not None:
        return direct

    candidate = _balanced_brace_slice(cleaned)
    parsed = _attempt_parse(candidate) if candidate else None
    if parsed is not None:
        return parsed

    try:
        repair_prompt = (
            "Return valid JSON only. Fix trailing commas, missing quotes, and remove commentary.\n"
            f"Malformed JSON:\n{candidate or cleaned}"
        )
        repaired_response = query_ollama(repair_prompt, format="json", timeout=OLLAMA_TIMEOUT)
        repaired_response = (repaired_response or "").strip()
        repaired_candidate = _balanced_brace_slice(repaired_response) or repaired_response
        repaired = _attempt_parse(repaired_candidate)
        if repaired is not None:
            return repaired
    except Exception:
        return "AI_FAILED"  # type: ignore[return-value]

    return "AI_FAILED"  # type: ignore[return-value]
