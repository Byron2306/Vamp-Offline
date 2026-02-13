⁹""""""




























































































































































































































query_llm = query_groq# Alias for backward compatibility with ollama_client    return "AI_FAILED"  # type: ignore[return-value]        pass    except Exception:            return final_parsed        if final_parsed is not None:        final_parsed = _attempt_parse(repaired_candidate)        repaired_candidate = _balanced_brace_slice(repaired_response) or repaired_response        repaired_response = (repaired_response or "").strip()        repaired_response = query_groq_json(repair_prompt, timeout=GROQ_TIMEOUT)        )            f"Malformed JSON:\n{candidate or cleaned}"            "Return valid JSON only. Fix trailing commas, missing quotes, and remove commentary.\n"        repair_prompt = (    try:    # Try to repair with another LLM call        return parsed    if parsed is not None:    parsed = _attempt_parse(candidate) if candidate else None    candidate = _balanced_brace_slice(cleaned)    # Try to extract balanced braces        return direct    if direct is not None:    direct = _attempt_parse(cleaned)    # Try direct parse                return None            except Exception:                return json.loads(repaired)            try:            repaired = _repair_json_string(candidate)        except Exception:            return json.loads(candidate)        try:    def _attempt_parse(candidate: str) -> Optional[Dict[str, Any]]:        return "AI_FAILED"  # type: ignore[return-value]    if not cleaned:    cleaned = (raw_text or "").strip()    """Best-effort extraction of a JSON object from an LLM response."""def extract_json_object(raw_text: str) -> Dict[str, Any]:    return repaired    repaired = re.sub(r"'", '"', repaired)    repaired = re.sub(r",\s*(\}|\])", r"\1", repaired)    repaired = text.strip()    """Attempt to repair common JSON issues."""def _repair_json_string(text: str) -> str:    return ""                return text[start : idx + 1]            if depth == 0 and start != -1:            depth -= 1        elif ch == "}" and depth > 0:            depth += 1                start = idx            if depth == 0:        if ch == "{":    for idx, ch in enumerate(text):    start = -1    depth = 0    """Extract the first balanced JSON object from text."""def _balanced_brace_slice(text: str) -> str:    return query_groq(json_prompt, model=model, timeout=timeout)    json_prompt = f"{prompt}\n\nIMPORTANT: Respond with valid JSON only. No markdown, no code blocks, just raw JSON."    """    Query Groq with JSON mode enabled (instructs model to return valid JSON).    """                    timeout: Optional[float] = None) -> str:def query_groq_json(prompt: str, *, model: Optional[str] = None,    raise RuntimeError("Unknown Groq error")        raise last_error    if last_error:            raise last_error or RuntimeError("Unknown Groq error")            continue            time.sleep(GROQ_BACKOFFS[backoff_idx])            backoff_idx = min(attempt, len(GROQ_BACKOFFS) - 1)        if attempt < attempts - 1:                        last_error = exc        except Exception as exc:                        last_error = e                    raise RuntimeError("Invalid GROQ_API_KEY. Check your API key at https://console.groq.com")                elif status == 401:                # Invalid API key                    continue                    time.sleep(retry_after)                    print(f"Rate limited. Waiting {retry_after}s...")                    retry_after = int(e.response.headers.get("Retry-After", 5))                if status == 429:                # Rate limit handling                status = e.response.status_code            if e.response is not None:        except requests.exceptions.HTTPError as e:                        return ""                return (choices[0].get("message", {}).get("content", "") or "").strip()            if choices:            choices = data.get("choices", [])            # Extract the response content                        data = response.json()            response.raise_for_status()            )                timeout=timeout or GROQ_TIMEOUT                headers=headers,                json=payload,                GROQ_API_URL,            response = requests.post(        try:    for attempt in range(attempts):        attempts = max(0, GROQ_RETRIES) + 1    last_error: Optional[Exception] = None        }        "Content-Type": "application/json"        "Authorization": f"Bearer {api_key}",    headers = {        }        "max_tokens": max_tokens if max_tokens is not None else GROQ_MAX_TOKENS,        "temperature": float(os.getenv("VAMP_LLM_TEMPERATURE", "0.25")),        "messages": messages,        "model": model or GROQ_MODEL,    payload = {        })        "content": prompt        "role": "user",    messages.append({    # Add user message            })            "content": system_prompt            "role": "system",        messages.append({    if system_prompt:    # Add system prompt if provided        messages = []            )            "Get a free API key at https://console.groq.com"            "GROQ_API_KEY environment variable is required. "        raise RuntimeError(    if not api_key:    api_key = GROQ_API_KEY            )            "The 'requests' dependency is required for Groq calls; install it to continue."        raise RuntimeError(    if requests is None:    """        The LLM response as a string    Returns:                system_prompt: Optional system prompt for context        max_tokens: Override the default max tokens        timeout: Override the default timeout        model: Override the default model        prompt: The user's prompt/question    Parameters:        Send a prompt to Groq's API and return the response text.    """               system_prompt: Optional[str] = None) -> str:               timeout: Optional[float] = None, max_tokens: Optional[int] = None,def query_groq(prompt: str, *, model: Optional[str] = None, # - gemma2-9b-it (Google's model)# - mixtral-8x7b-32768 (good for longer context)# - llama3-70b-8192 (high quality)# - llama3-8b-8192 (fast)# - llama-3.1-8b-instant (faster, good quality)# - llama-3.3-70b-versatile (best quality, recommended)# Available free Groq models (as of 2024):GROQ_BACKOFFS = [2, 6]GROQ_RETRIES = int(os.getenv("GROQ_RETRIES", "2"))GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "60"))GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Free tier modelGROQ_API_KEY = os.getenv("GROQ_API_KEY", "")GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"# Groq configuration    _REQUESTS_IMPORT_ERROR = exc    requests = Noneexcept Exception as exc:    import requeststry:from typing import Any, Dict, Optionalimport timeimport reimport osimport jsonfrom __future__ import annotations"""Free cloud-based LLM inference using Groq's APIGroq API Client for VAMPGroq LLM Client - Free cloud-based AI inference
https://console.groq.com - Sign up for a free API key
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional

try:
    import requests
except Exception as exc:
    requests = None
    _REQUESTS_IMPORT_ERROR = exc


# Groq Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Free and fast
GROQ_TIMEOUT = max(60.0, float(os.getenv("GROQ_TIMEOUT", "120")))
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
GROQ_RETRIES = int(os.getenv("GROQ_RETRIES", "2"))
GROQ_BACKOFFS = [2, 6]

# Available free Groq models:
# - llama-3.3-70b-versatile (recommended - best quality)
# - llama-3.1-8b-instant (faster)
# - mixtral-8x7b-32768 (good for longer context)
# - gemma2-9b-it (Google's model)


def is_groq_configured() -> bool:
    """Check if Groq API key is configured."""
    return bool(GROQ_API_KEY)


def query_groq(prompt: str, *, model: Optional[str] = None, format: Optional[str] = None,
               timeout: Optional[float] = None, max_tokens: Optional[int] = None,
               system_prompt: Optional[str] = None) -> str:
    """Send a prompt to Groq API and return the response text.

    Parameters allow overrides but default to environment-configured settings.
    """
    if requests is None:
        raise RuntimeError(
            "The 'requests' dependency is required for Groq calls; install it to continue."
        )
    
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free API key at https://console.groq.com"
        )
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload: Dict[str, Any] = {
        "model": model or GROQ_MODEL,
        "messages": messages,
        "temperature": float(os.getenv("VAMP_LLM_TEMPERATURE", "0.25")),
        "max_tokens": max_tokens if max_tokens is not None else GROQ_MAX_TOKENS,
    }
    
    # Handle JSON format request
    if format == "json":
        payload["response_format"] = {"type": "json_object"}
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    last_error: Optional[Exception] = None
    attempts = max(0, GROQ_RETRIES) + 1
    for attempt in range(attempts):
        try:
            response = requests.post(
                GROQ_API_URL,
                json=payload,
                headers=headers,
                timeout=timeout or GROQ_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                backoff_idx = min(attempt, len(GROQ_BACKOFFS) - 1)
                time.sleep(GROQ_BACKOFFS[backoff_idx])
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Unknown Groq error")


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
        repaired_response = query_groq(repair_prompt, format="json", timeout=GROQ_TIMEOUT)
        repaired_response = (repaired_response or "").strip()
        repaired_candidate = _balanced_brace_slice(repaired_response) or repaired_response
        repaired = _attempt_parse(repaired_candidate)
        if repaired is not None:
            return repaired
    except Exception:
        return "AI_FAILED"  # type: ignore[return-value]

    return "AI_FAILED"  # type: ignore[return-value]


# Alias for compatibility with ollama_client imports
query_llm = query_groq
