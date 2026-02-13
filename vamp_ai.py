from __future__ import annotations

import os
import re
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

# LLM Provider Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" or "ollama"

# Groq configuration (free cloud API)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "60"))

# Ollama configuration (local fallback)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

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
You are Eagi — the AI Assistant for North-West University (NWU) academic staff.

Your role:
- Help with Task Agreements, KPAs, evidence, and Performance Agreements when asked
- Be conversational, friendly, and professional
- Only provide information relevant to the user's question
- For greetings, respond naturally without dumping system information
- Restrict responses to NWU academic matters
- When asked about specific tasks or recommendations, provide detailed, specific answers with concrete examples
- If uncertain, ask for clarification rather than inventing answers

Tone:
- Friendly and approachable
- Helpful and supportive
- Concise but informative when needed

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
try:
    from backend.llm.ollama_client import query_ollama as central_query_ollama
    LLM_WRAPPER_AVAILABLE = True
except Exception:
    central_query_ollama = None
    LLM_WRAPPER_AVAILABLE = False


def _call_groq(prompt: str, system_prompt: str) -> str:
    """Call the centralized LLM wrapper (prefers Groq when configured)."""
    full_prompt = f"{system_prompt}\n\n{prompt}"
    if LLM_WRAPPER_AVAILABLE and central_query_ollama:
        try:
            return central_query_ollama(full_prompt)
        except Exception as e:
            raise
    # Fallback to direct Groq call if wrapper not available
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.25,
        "max_tokens": 1024
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(
        GROQ_API_URL,
        json=payload,
        headers=headers,
        timeout=GROQ_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "").strip()
    return ""


def _call_ollama(prompt: str) -> str:
    """Call the centralized LLM wrapper (falls back to local Ollama if wrapper unavailable)."""
    if LLM_WRAPPER_AVAILABLE and central_query_ollama:
        try:
            return central_query_ollama(prompt)
        except Exception:
            pass
    # Fallback to direct Ollama endpoint
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=OLLAMA_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


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
    # Build context block
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
    
    user_prompt = f"""Context:
{ctx_block}

User question or task:
{question}
Respond naturally and helpfully. Only provide information relevant to the question. For greetings or general questions, keep responses brief and friendly."""

    try:
        # Use Groq if configured, otherwise fall back to Ollama
        if LLM_PROVIDER.lower() == "groq" and GROQ_API_KEY:
            answer = _call_groq(user_prompt, SYSTEM_PROMPT)
            model_used = GROQ_MODEL
        else:
            full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
            answer = _call_ollama(full_prompt)
            model_used = OLLAMA_MODEL

        if not answer:
            answer = "I have reflected on this, but require more information."
        
        # Sanitize answer for speech (removes asterisks, markdown, etc.)
        clean_answer = sanitize_for_speech(answer) if ELEVENLABS_AVAILABLE else answer
        
        result = {
            "answer": clean_answer,
            "model": model_used,
            "provider": "groq" if (LLM_PROVIDER.lower() == "groq" and GROQ_API_KEY) else "ollama",
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
                "Please allow a moment and try again."
            ),
            "error": "timeout",
            "has_voice": False
        }

    except Exception as e:
        return {
            "answer": (
                "I cannot reach my cognitive core at present. "
                "Check your API key or ensure the AI service is available."
            ),
            "error": str(e),
            "has_voice": False
        }
