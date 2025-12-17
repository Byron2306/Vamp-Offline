from __future__ import annotations

import requests
from typing import Dict, Any, List
from datetime import datetime

# Ollama configuration
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
OLLAMA_TIMEOUT = 60


# ─────────────────────────────────────────────
# System prompt (institutional, grounded)
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
You are VAMP — the Virtual Academic Management Partner for North-West University (NWU).

Your role:
- Guide academic staff through Task Agreements, KPAs, evidence, and Performance Agreements
- Be concise, supportive, and professional
- Never hallucinate policy or KPAs
- If uncertain, ask for clarification rather than inventing answers

Tone:
- Calm
- Authoritative
- Encouraging
- Subtly gothic, but institutionally appropriate
"""


def build_prompt(question: str, context: Dict[str, Any]) -> str:
    ctx_lines: List[str] = []

    if context.get("staff_id"):
        ctx_lines.append(f"Staff ID: {context['staff_id']}")
    if context.get("cycle_year"):
        ctx_lines.append(f"Cycle year: {context['cycle_year']}")
    if context.get("stage"):
        ctx_lines.append(f"Current stage: {context['stage']}")
    if context.get("scan_month"):
        ctx_lines.append(f"Current month bucket: {context['scan_month']}")
    if context.get("month"):
        ctx_lines.append(f"Month being analyzed: {context['month']}")
    if context.get("tasks"):
        ctx_lines.append(f"Tasks for this period: {context['tasks']}")
    if context.get("evidence_count"):
        ctx_lines.append(f"Evidence items uploaded: {context['evidence_count']}")
    if context.get("required"):
        ctx_lines.append(f"Minimum required evidence: {context['required']}")

    ctx_block = "\n".join(ctx_lines) if ctx_lines else "No additional context."

    return f"""
{SYSTEM_PROMPT}

Context:
{ctx_block}

User question or task:
{question}

When analyzing monthly expectations:
- Be specific about which KPAs need attention
- Suggest concrete evidence types (e.g., "Upload assessment rubrics for KPA1")
- Celebrate progress when expectations are met
- Provide realistic timelines for catching up if behind

Respond clearly and helpfully.
"""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def ask_vamp(question: str, context: Dict[str, Any]) -> Dict[str, Any]:
    prompt = build_prompt(question, context)

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        r = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        r.raise_for_status()

        data = r.json()
        answer = data.get("response", "").strip()

        if not answer:
            answer = "I have reflected on this, but require more information."

        return {
            "answer": answer,
            "model": OLLAMA_MODEL,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except requests.exceptions.Timeout:
        return {
            "answer": (
                "My thoughts are slow to coalesce. "
                "Please allow a moment, or ensure Ollama is running."
            ),
            "error": "timeout"
        }

    except Exception as e:
        return {
            "answer": (
                "I cannot reach my cognitive core at present. "
                "Ensure the local AI service is available."
            ),
            "error": str(e)
        }
