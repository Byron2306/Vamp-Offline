"""Automatic KPI generation from outputs when PA data lacks KPIs.

Rules (Batch 5)
---------------
* Only invoked when PA data does not contain KPIs.
* For each output line we detect an action verb plus any quantities/timeframes
  and synthesise a KPI structure that the downstream PA pipeline can consume.
* The KPI object shape is constrained and should not be changed here; wording
  refinements are allowed but structure must remain stable.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence

# Tokens that hint at particular evidence artifacts
_EVIDENCE_KEYWORDS = {
    "report": "Report",
    "publication": "Publication",
    "article": "Publication",
    "paper": "Publication",
    "workshop": "Workshop materials",
    "training": "Training attendance record",
    "course": "Training attendance record",
    "presentation": "Presentation slide deck",
    "slides": "Presentation slide deck",
    "survey": "Survey results",
    "assessment": "Assessment records",
    "evaluation": "Evaluation summary",
    "meeting": "Meeting minutes",
    "minutes": "Meeting minutes",
    "policy": "Policy / guideline document",
    "guideline": "Policy / guideline document",
    "curriculum": "Curriculum / module outline",
}


def _split_outputs(outputs: object) -> List[str]:
    """Normalise mixed output formats into a list of non-empty strings."""

    if outputs is None:
        return []
    if isinstance(outputs, str):
        parts = re.split(r"[\n;•]|\s*\u2022\s*", outputs)
        return [p.strip(" -\t") for p in parts if p and p.strip(" -\t")]
    if isinstance(outputs, Iterable):
        texts: List[str] = []
        for item in outputs:
            if item is None:
                continue
            txt = str(item).strip()
            if txt:
                texts.append(txt)
        return texts
    return [str(outputs).strip()]


def _detect_action_verb(text: str) -> str:
    """Pick the leading action verb (best-effort heuristic)."""

    tokens = re.findall(r"[A-Za-z']+", text)
    if not tokens:
        return "Deliver"
    return tokens[0].capitalize()


def _detect_quantity_timeframe(text: str) -> str:
    """Extract quantities or deadlines from the text where possible."""

    quantity_patterns = [
        r"\b\d+(?:\.\d+)?\s*(?:reports?|articles?|papers?|workshops?|sessions?|courses?|classes?|modules?)\b",
        r"\b\d+(?:\.\d+)?\s*(?:per|each)?\s*(?:week|month|quarter|semester|year)\b",
        r"\bby\s+(?:end\s+of\s+)?(?:q[1-4]|quarter\s*\d|december|november|october|september|august|july|june|may|april|march|february|january)\b",
    ]
    for pattern in quantity_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return "Completed as scheduled"


def _detect_evidence_types(text: str) -> List[str]:
    evidence: List[str] = []
    lowered = text.lower()
    for keyword, label in _EVIDENCE_KEYWORDS.items():
        if keyword in lowered and label not in evidence:
            evidence.append(label)
    if not evidence:
        evidence.append("General evidence")
    return evidence


def generate_kpis_from_outputs(outputs: Sequence[object] | object) -> List[dict]:
    """Generate KPI dicts from a set of outputs.

    The returned structure matches the contract builder expectations and should
    only be used when PA data has no explicit KPI list.
    """

    kpis: List[dict] = []
    for output in _split_outputs(outputs):
        action = _detect_action_verb(output)
        quantity = _detect_quantity_timeframe(output)
        evidence_types = _detect_evidence_types(output)

        description = output.strip().rstrip(".")
        if not description:
            continue

        kpi_text = description
        if not description.lower().startswith(action.lower()):
            kpi_text = f"{action} {description}"

        kpis.append(
            {
                "kpi": kpi_text,
                "measure": "Verified evidence uploaded",
                "target": quantity,
                "due": "Q1–Q4",
                "evidence_types": evidence_types,
            }
        )
    return kpis
