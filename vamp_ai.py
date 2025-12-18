from __future__ import annotations

import re
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

# Ollama configuration
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"  # Faster and more capable than 1b
OLLAMA_TIMEOUT = 60

# Import ElevenLabs TTS
try:
    from backend.llm.elevenlabs_tts import text_to_speech, sanitize_for_speech
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False
    text_to_speech = None
    sanitize_for_speech = None


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

IMPORTANT OUTPUT RULES:
- Write in plain text only - NO asterisks (*), underscores (_), or markdown formatting
- NO special symbols or emojis
- Use simple punctuation only (periods, commas, question marks)
- Write naturally as if speaking directly to the user
- Keep responses clear and conversational
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

def ask_vamp(question: str, context: Dict[str, Any], with_voice: bool = False) -> Dict[str, Any]:
    """
    Ask VAMP a question with optional voice response
    
    Args:
        question: User's question
        context: Contextual information
        with_voice: If True, generate audio response using ElevenLabs
        
    Returns:
        Dictionary with answer, optional audio_path, and metadata
    """
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
        
        # Sanitize answer for speech (removes asterisks, markdown, etc.)
        clean_answer = sanitize_for_speech(answer) if ELEVENLABS_AVAILABLE else answer
        
        result = {
            "answer": clean_answer,
            "model": OLLAMA_MODEL,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Generate voice if requested
        if with_voice and ELEVENLABS_AVAILABLE:
            try:
                audio_path = text_to_speech(clean_answer)
                if audio_path:
                    result["audio_path"] = str(audio_path)
                    result["has_voice"] = True
                else:
                    result["has_voice"] = False
            except Exception as voice_error:
                print(f"Voice generation failed: {voice_error}")
                result["has_voice"] = False
        else:
            result["has_voice"] = False

        return result

    except requests.exceptions.Timeout:
        return {
            "answer": (
                "My thoughts are slow to coalesce. "
                "Please allow a moment, or ensure Ollama is running."
            ),
            "error": "timeout",
            "has_voice": False
        }

    except Exception as e:
        return {
            "answer": (
                "I cannot reach my cognitive core at present. "
                "Ensure the local AI service is available."
            ),
            "error": str(e),
            "has_voice": False
        }
