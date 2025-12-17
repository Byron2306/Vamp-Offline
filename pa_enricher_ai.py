from __future__ import annotations

"""DEPRECATED: AI PA enrichment is disabled.

Per NWU compliance requirements for this build:
- KPI text and Outcomes are populated deterministically from controlled vocabularies.
- The LLM must NOT generate or modify KPIs/Outcomes.
- The LLM is used only for evidence assessment against the FINAL PA.

This shim remains only to avoid import breakage in older UI code.
"""

from typing import Any, Dict, Sequence

from backend.staff_profile import StaffProfile
from backend.contracts.pa_enricher_library import enrich_pa_from_libraries


def enrich_pa_with_ai(profile: StaffProfile, skeleton_rows: Sequence[Sequence[Any]] | None) -> Dict[str, Any]:
    # Delegate to deterministic library enrichment (no LLM involved).
    return enrich_pa_from_libraries(profile, skeleton_rows)
