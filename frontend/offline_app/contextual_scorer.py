from __future__ import annotations

"""
contextual_scorer.py

Expectation-aware orchestrator that:
- Uses the deterministic NWU brain scorer (backend.nwu_brain_scorer.brain_score_evidence)
- Pulls yearly expectations from backend.expectation_engine.load_staff_expectations (if available)
- Calls a local Ollama model to produce a *structured* contextual score for ONE evidence item:
    primary_kpa_code / rating / tier_label / impact_summary
- Returns a merged context dict consumed by the Tkinter GUI.

Environment variables
---------------------
OLLAMA_HOST          default: http://127.0.0.1:11434
OLLAMA_MODEL         default: llama3.2:1b
OLLAMA_TIMEOUT       default: 45
OLLAMA_NUM_PREDICT   default: 320
VAMP_LLM_TEMPERATURE default: 0.25

VAMP_MAX_EVIDENCE_CHARS default: 800
VAMP_MAX_CONTRACT_CHARS default: 1500
VAMP_MAX_EXPECT_CHARS   default: 1200
"""

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import requests  # type: ignore
except Exception:
    requests = None

try:
    from backend.expectation_engine import load_staff_expectations  # type: ignore
except Exception:
    load_staff_expectations = None

try:
    from backend.nwu_brain_scorer import brain_score_evidence  # type: ignore
except Exception:
    brain_score_evidence = None


KPA_NAMES: Dict[str, str] = {
    "KPA1": "Teaching and Learning",
    "KPA2": "Occupational Health & Safety",
    "KPA3": "Personal Research and Innovation",
    "KPA4": "Academic leadership and management",
    "KPA5": "Social Responsiveness",
}

MAX_EVIDENCE_CHARS = int(os.getenv("VAMP_MAX_EVIDENCE_CHARS", "800"))
MAX_CONTRACT_CHARS = int(os.getenv("VAMP_MAX_CONTRACT_CHARS", "1500"))
MAX_EXPECT_CHARS = int(os.getenv("VAMP_MAX_EXPECT_CHARS", "1200"))

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "45"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "320"))


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _rating_label(rating: Optional[int]) -> str:
    if rating is None:
        return "Unrated"
    try:
        r = int(rating)
    except Exception:
        return "Unrated"
    if r <= 1:
        return "Not achieved"
    if r == 2:
        return "Partially achieved (weak)"
    if r == 3:
        return "Partially achieved (solid progress)"
    if r == 4:
        return "Fully achieved"
    return "Exceptional"


def _summarise_expectations_for_prompt(staff_id: Optional[str], expectations: Dict[str, Any]) -> str:
    if not expectations:
        if staff_id:
            return f"No explicit Task/Performance Agreement expectations could be loaded for staff {staff_id}."
        return "No explicit Task/Performance Agreement expectations could be loaded."

    lines: list[str] = []
    if staff_id:
        lines.append(f"Expectations for staff {staff_id} (year plan):")

    kpa_summary = expectations.get("kpa_summary", {}) or {}
    if kpa_summary:
        lines.append("KPA allocations and key expectations:")
        for code, data in kpa_summary.items():
            code_str = str(code).strip()
            # Keys sometimes show 'KPA3 - ...' etc
            code_guess = "KPA" + "".join(ch for ch in code_str if ch.isdigit()) if "KPA" not in code_str.upper() else code_str.split()[0].upper()
            code_guess = code_guess if code_guess in KPA_NAMES else code_guess
            name = KPA_NAMES.get(code_guess, code_str)

            w = str(data.get("weight", "") or "").strip()
            h = str(data.get("hours", "") or "").strip()
            key_exps = [str(x).strip() for x in (data.get("key_expectations") or []) if str(x).strip()]

            bits: list[str] = []
            if w:
                bits.append(f"weight={w}%")
            if h:
                bits.append(f"hours={h}")
            detail = ", ".join(bits) if bits else "no numeric allocation captured"

            if key_exps:
                lines.append(f"- {code_guess} ({name}): {detail}. Examples: " + "; ".join(key_exps[:4]))
            else:
                lines.append(f"- {code_guess} ({name}): {detail}. (No specific bullet expectations captured.)")

    kpa2_modules = []
    kpa2_data = kpa_summary.get("KPA2") if kpa_summary else None
    if isinstance(kpa2_data, dict):
        raw_modules = kpa2_data.get("teaching_modules") or []
        kpa2_modules = [str(m).strip() for m in raw_modules if str(m).strip()]

    if kpa2_modules:
        module_line = ", ".join(kpa2_modules[:8])
        extra = len(kpa2_modules) - 8
        if extra > 0:
            module_line += f" (+{extra} more)"
        lines.append(f"Teaching modules (Addendum B): {module_line}")

    # Add light examples across domains if present
    for key, label, n in [
        ("teaching", "Teaching modules/responsibilities", 6),
        ("supervision", "Supervision expectations", 4),
        ("research", "Research expectations", 4),
        ("leadership", "Leadership/committee roles", 6),
        ("social_responsiveness", "Social responsiveness expectations", 4),
        ("ohs", "OHS expectations", 4),
    ]:
        arr = expectations.get(key) or []
        if arr:
            lines.append(f"{label}: " + "; ".join(str(x) for x in arr[:n]))

    text = "\n".join(lines).strip()
    return _truncate(text, MAX_EXPECT_CHARS)


def _build_llm_prompt(
    *,
    evidence_snippet: str,
    contract_context: str,
    expectations_summary: str,
    brain_suggestion: Tuple[str, str] | None,
    kpa_hint_code: Optional[str],
) -> str:
    brain_line = ""
    if brain_suggestion and brain_suggestion[0]:
        brain_line = f'Brain-suggested primary KPA (deterministic): {brain_suggestion[0]} – {brain_suggestion[1]}'

    hint_line = ""
    if kpa_hint_code and kpa_hint_code.strip():
        hint_line = f'User KPA hint for this scan: {kpa_hint_code.strip()}'

    template = f"""
You are helping to score MONTHLY performance evidence for a North-West University (NWU) academic.

You are given:
1) YEAR EXPECTATION SUMMARY (from Task Agreement / Performance Agreement)
2) CONTRACT CONTEXT (KPAs/KPIs/policy guidance)
3) ONE EVIDENCE SNIPPET (text extracted from a single artefact)

{brain_line}
{hint_line}

YEAR EXPECTATION SUMMARY:
{expectations_summary}

CONTRACT CONTEXT:
{_truncate(contract_context, MAX_CONTRACT_CHARS)}

EVIDENCE SNIPPET:
{_truncate(evidence_snippet, MAX_EVIDENCE_CHARS)}

Tasks:
1) Choose ONE primary KPA code that this evidence best supports.
   Allowed codes only: KPA1, KPA2, KPA3, KPA4, KPA5.
   - If the evidence clearly matches the hint, follow the hint.
   - If the evidence clearly matches the brain suggestion, follow it.
   - Only override if there is strong evidence in the snippet.

2) Decide the IMPACT rating for THIS SINGLE item in THIS MONTH, relative to the year plan:
   - rating must be an integer 1–5
   - 1 = Not achieved
   - 2 = Partially achieved (weak evidence against expectations)
   - 3 = Partially achieved (solid progress but not fully meeting expectations yet)
   - 4 = Fully achieved (meets expectations for the period)
   - 5 = Exceptional (clearly exceeds expectations for the period)

3) Choose tier_label:
   - "Transformational" → strategic, high-impact contribution
   - "Developmental"    → meaningful but moderate / work in progress
   - "Compliance"       → routine, administrative, minimal impact

4) Write impact_summary (3–4 sentences, max 120 words):
   - Be concrete (module, output, role, committee, grant, paper, supervision etc) if visible.
   - Explicitly link this evidence to the YEAR EXPECTATIONS (on track / lagging / exceeding).
   - Do NOT describe the document type (avoid “This is an agenda/email”).

Return ONE JSON object only, with EXACTLY these keys:
  "primary_kpa_code", "primary_kpa_name",
  "rating", "rating_label", "tier_label",
  "impact_summary"

KPA name mapping:
  KPA1 → Teaching and Learning
  KPA2 → Occupational Health & Safety
  KPA3 → Personal Research and Innovation
  KPA4 → Academic leadership and management
  KPA5 → Social Responsiveness

Start your reply directly with the JSON object, no prose before or after.
"""
    return textwrap.dedent(template).strip()


def _query_ollama(prompt: str) -> str:
    if requests is None:
        raise RuntimeError("requests not installed – cannot call Ollama")

    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        # Ask Ollama to enforce JSON output when possible.
        "format": "json",
        "options": {
            "temperature": float(os.getenv("VAMP_LLM_TEMPERATURE", "0.25")),
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }
    resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("response") or "").strip()


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Empty LLM response")

    # 1) Direct parse
    try:
        return json.loads(raw_text)
    except Exception:
        pass

    # 2) Try extract the first JSON object
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if 0 <= start < end:
        candidate = raw_text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception as e:
            raise ValueError(f"Failed to parse JSON candidate: {e}") from e

    raise ValueError("Could not find a valid JSON object in response")


def _coerce_kpa(code: Any) -> str:
    c = str(code or "").strip().upper()
    if c in KPA_NAMES:
        return c
    # Accept "KPA3 - ..." style
    if c.startswith("KPA") and len(c) >= 4 and c[3].isdigit():
        guess = c[:4]
        if guess in KPA_NAMES:
            return guess
    return ""


def _coerce_rating(val: Any) -> Optional[int]:
    try:
        r = int(float(val))
    except Exception:
        return None
    if r < 1:
        return 1
    if r > 5:
        return 5
    return r


def contextual_score(
    evidence_text: str,
    contract_context: str = "",
    kpa_hint_code: Optional[str] = None,
    *,
    staff_id: Optional[str] = None,
    source_path: Optional[Path] = None,
    prefer_llm_rating: bool = True,
    prefer_llm_kpa: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point used by the GUI.

    - Calls brain_score_evidence for deterministic NWU scoring (if available).
    - Loads expectations JSON for the staff member (if available).
    - Calls Ollama for a structured contextual score (KPA/rating/tier/summary).
    - Returns a merged context dict.

    prefer_llm_rating: if True, use the LLM rating when valid (even if brain has a rating).
    prefer_llm_kpa:    if True, allow LLM to override brain KPA more readily.
    """
    path = Path(source_path) if source_path is not None else Path("evidence.txt")
    full_text = evidence_text or ""

    # 1) Deterministic brain scoring
    brain_ctx: Dict[str, Any] = {}
    if brain_score_evidence is not None:
        try:
            brain_ctx = brain_score_evidence(
                path=path,
                full_text=full_text,
                kpa_hint_code=kpa_hint_code,
            ) or {}
        except Exception as e:
            brain_ctx = {"rating_label": f"Brain scorer error: {e}"}
    else:
        brain_ctx = {"rating_label": "Brain scorer not available"}

    brain_kpa = str(brain_ctx.get("primary_kpa_code") or "").strip().upper()
    brain_kpa_name = str(brain_ctx.get("primary_kpa_name") or "").strip() or KPA_NAMES.get(brain_kpa, "")
    brain_rating = brain_ctx.get("rating", None)
    brain_tier = str(brain_ctx.get("tier_label") or "").strip()

    # 2) Expectations summary
    expectations_json: Dict[str, Any] = {}
    if staff_id and load_staff_expectations is not None:
        try:
            expectations_json = load_staff_expectations(staff_id) or {}
        except Exception:
            expectations_json = {}
    expectations_summary = _summarise_expectations_for_prompt(staff_id, expectations_json)

    # 3) LLM contextual score
    llm_raw_text = ""
    llm_json: Dict[str, Any] | None = None

    primary_kpa_code = brain_kpa or (kpa_hint_code or "")
    primary_kpa_name = brain_kpa_name or KPA_NAMES.get(primary_kpa_code, "")
    rating = _coerce_rating(brain_rating) if brain_rating is not None else None
    rating_label = str(brain_ctx.get("rating_label") or "").strip() or _rating_label(rating)
    tier_label = brain_tier
    impact_summary = ""

    try:
        prompt = _build_llm_prompt(
            evidence_snippet=full_text,
            contract_context=contract_context,
            expectations_summary=expectations_summary,
            brain_suggestion=(brain_kpa, brain_kpa_name) if brain_kpa else None,
            kpa_hint_code=kpa_hint_code,
        )
        llm_raw_text = _query_ollama(prompt)
        llm_json = _parse_llm_json(llm_raw_text)

        llm_kpa = _coerce_kpa(llm_json.get("primary_kpa_code"))
        llm_rating = _coerce_rating(llm_json.get("rating"))
        llm_tier = str(llm_json.get("tier_label") or "").strip()
        llm_summary = str(llm_json.get("impact_summary") or "").strip()

        # KPA selection
        if llm_kpa:
            if prefer_llm_kpa or (not brain_kpa):
                primary_kpa_code = llm_kpa
            else:
                # Keep brain suggestion unless LLM agrees with hint and brain is empty/mismatched
                hint = _coerce_kpa(kpa_hint_code)
                if hint and llm_kpa == hint:
                    primary_kpa_code = llm_kpa

        primary_kpa_name = KPA_NAMES.get(primary_kpa_code, primary_kpa_name or "")

        # Tier
        if llm_tier:
            tier_label = llm_tier
        elif not tier_label:
            tier_label = "Developmental"

        # Rating
        if llm_rating is not None and prefer_llm_rating:
            rating = llm_rating
            rating_label = str(llm_json.get("rating_label") or "").strip() or _rating_label(rating)
        else:
            if rating is None and llm_rating is not None:
                rating = llm_rating
                rating_label = _rating_label(rating)

        # Summary
        impact_summary = llm_summary or ""

    except Exception as e:
        impact_summary = f"(LLM contextual scoring unavailable – {e})"
        llm_json = None

    # 4) Merge results + provenance
    ctx: Dict[str, Any] = dict(brain_ctx)
    ctx.update(
        {
            "primary_kpa_code": primary_kpa_code,
            "primary_kpa_name": primary_kpa_name,
            "tier_label": tier_label,
            "rating": rating,
            "rating_label": rating_label,
            "impact_summary": impact_summary,
            "contextual_response": impact_summary,  # backward compatibility
            "expectations_summary": expectations_summary,
            "brain_primary_kpa_code": brain_kpa,
            "brain_primary_kpa_name": brain_kpa_name,
            "brain_rating": brain_rating,
            "brain_tier_label": brain_tier,
        }
    )

    if llm_json is None:
        ctx["raw_llm_json"] = {"__raw_text__": llm_raw_text}
    else:
        llm_json = dict(llm_json)
        llm_json["__raw_text__"] = llm_raw_text
        ctx["raw_llm_json"] = llm_json

    return ctx
