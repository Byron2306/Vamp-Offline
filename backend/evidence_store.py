from __future__ import annotations

# Simple re-export shim so that:
#   from backend.evidence_store import append_evidence_row
# works with your existing backend/evidence/evidence_store.py.

from .evidence.evidence_store import (  # type: ignore
    append_evidence_row,
    evidence_csv_path,
    EVIDENCE_COLUMNS,
)
