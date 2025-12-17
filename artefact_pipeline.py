from __future__ import annotations

"""Artefact processing pipeline (UI-agnostic).

This module was extracted from the Tkinter UI (offline_app_gui_llm_csv.py) so that
both the desktop UI and any future HTML/API front-end can reuse the exact same
processing logic.

It intentionally accepts plain Python types and returns plain dicts.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Pipeline functions (already UI-agnostic)
from backend.vamp_master import extract_text_for
from frontend.offline_app.contextual_scorer import contextual_score
from backend.nwu_brain_scorer import brain_score_evidence


def _default_ctx(kpa_hint: str) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "primary_kpa_code": kpa_hint or "",
        "primary_kpa_name": "",
        "tier_label": "Developmental",
        "rating": None,
        "rating_label": "Unrated",
        "impact_summary": "",
        "raw_llm_json": {},
        "values_hits": [],
    }
    return ctx


def _normalize_ctx(ctx: Optional[Dict[str, Any]], kpa_hint: str) -> Dict[str, Any]:
    base = _default_ctx(kpa_hint)
    merged = base.copy()
    if ctx:
        merged.update(ctx)
    merged.setdefault("primary_kpa_code", kpa_hint or "")
    merged.setdefault("primary_kpa_name", "")
    merged.setdefault("tier_label", "Developmental")
    merged.setdefault("rating", None)
    merged.setdefault("rating_label", "Unrated")
    merged.setdefault("impact_summary", "")
    merged.setdefault("raw_llm_json", {})
    merged.setdefault("values_hits", [])
    return merged


def _guess_evidence_type(path: Path) -> str:
    s = path.suffix.lower()
    if s == ".pdf":
        return "pdf"
    if s in {".doc", ".docx"}:
        return "word"
    if s in {".ppt", ".pptx"}:
        return "powerpoint"
    if s in {".xlsx", ".xls", ".xlsm"}:
        return "excel"
    if s in {".msg", ".eml"}:
        return "email"
    return s.lstrip(".") or "other"


def process_artefact(
    *,
    path: Path,
    month_bucket: str,
    run_id: str,
    profile: Any,
    contract_context: str,
    kpa_hint: str,
    use_ollama: bool,
    prefer_llm_rating: bool,
    log: Optional[Any] = None,
    extract_fn=extract_text_for,
    contextual_fn=contextual_score,
    brain_fn=brain_score_evidence,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Process a single artefact into a table/CSV row + ctx + impact string.

    Returns:
      (row, ctx, impact_summary)

    Notes:
      - `profile` is accepted as Any to avoid coupling; brain_score_evidence can
        handle StaffProfile-like objects.
      - `contract_context` should be a compact string summary of the staff's
        expectations/contract; used by contextual scoring and brain scoring.
    """

    # --- 1) Extract text (deep read) ---
    extract_status = "ok"
    extract_error = ""
    extracted_text = ""

    try:
        extraction = extract_fn(path)
        if isinstance(extraction, dict):
            # defensive: some older versions returned dict-like
            extract_status = str(extraction.get("status", "ok"))
            extract_error = str(extraction.get("error", "") or "")
            extracted_text = str(extraction.get("text", "") or "")
        else:
            extract_status = getattr(extraction, "status", "ok")
            extract_error = getattr(extraction, "error", "") or ""
            extracted_text = getattr(extraction, "text", "") or ""
    except Exception as ex:
        extract_status = "error"
        extract_error = str(ex)
        extracted_text = ""

    # --- 2) Decide if needs review / status ---
    review_reason = ""
    status = "OK"
    if extract_status != "ok":
        status = "Needs Review"
        if extract_status == "image_no_ocr":
            review_reason = f"Batch1 image OCR: {extract_error or 'no text extracted'}"
        else:
            review_reason = f"Batch1 extraction: {extract_error or 'no text extracted'}"

    # --- 3) Contextual scoring (optional, only when extraction succeeded) ---
    ctx: Dict[str, Any] = _default_ctx(kpa_hint)
    scoring_available = False
    scoring_error = False

    if extract_status == "ok":
        if use_ollama and contextual_fn is not None:
            scoring_available = True
            try:
                ctx = contextual_fn(
                    extracted_text,
                    contract_context=contract_context,
                    kpa_hint=kpa_hint,
                    prefer_llm_rating=prefer_llm_rating,
                ) or _default_ctx(kpa_hint)
            except Exception as ex:
                scoring_error = True
                if log:
                    try:
                        log(f"⚠️ contextual_score failed for {path.name}: {ex}")
                    except Exception:
                        pass
                ctx = _default_ctx(kpa_hint)
        else:
            # no LLM: still return baseline ctx
            ctx = _default_ctx(kpa_hint)

        ctx = _normalize_ctx(ctx, kpa_hint)

    # --- 4) Brain scoring (deterministic NWU brain) ---
    impact = ""
    confidence_pct = ""
    if extract_status == "ok":
        try:
            # brain_score_evidence can use both extracted_text and ctx
            out = brain_fn(
                evidence_text=extracted_text,
                contract_context=contract_context,
                profile=profile,
                ctx=ctx,
                kpa_hint=kpa_hint,
            )
            if isinstance(out, dict):
                # expected keys
                impact = str(out.get("impact_summary") or out.get("impact") or "")
                confidence = out.get("confidence")
                if confidence is not None:
                    try:
                        confidence_pct = f"{float(confidence) * 100:.0f}%"
                    except Exception:
                        confidence_pct = str(confidence)
                # merge any fields back into ctx (e.g., kpa matches, values hits, etc.)
                ctx.update(out)
                ctx = _normalize_ctx(ctx, kpa_hint)
        except Exception as ex:
            scoring_error = True
            status = "Needs Review"
            review_reason = review_reason or f"Brain scoring error: {ex}"
            if log:
                try:
                    log(f"⚠️ brain_score_evidence failed for {path.name}: {ex}")
                except Exception:
                    pass

    if scoring_available and scoring_error:
        status = "Needs Review"
        if not review_reason:
            review_reason = "Scoring failed"

    # --- 5) Build row dict (UI/CSV friendly) ---
    evidence_type = _guess_evidence_type(path)

    row: Dict[str, Any] = {
        "run_id": run_id,
        "filename": path.name,
        "file_path": str(path),
        "file": str(path),
        "month": month_bucket,
        "kpa_code": str(ctx.get("primary_kpa_code") or kpa_hint or "").strip(),
        "kpa_name": str(ctx.get("primary_kpa_name") or "").strip(),
        "kpa_codes": "; ".join([str(x) for x in (ctx.get("kpa_codes") or [])]) if isinstance(ctx.get("kpa_codes"), list) else str(ctx.get("kpa_codes") or ""),
        "rating": "" if ctx.get("rating") is None else ctx.get("rating"),
        "rating_label": str(ctx.get("rating_label") or "").strip() or "Unrated",
        "tier_label": str(ctx.get("tier_label") or "").strip() or "Developmental",
        "status": status,
        "confidence": confidence_pct,
        "impact_summary": impact,
        "status_reason": review_reason,
        "evidence_type": evidence_type,
        "extract_status": extract_status,
        "extract_error": extract_error,
    }

    kpi_matches = ctx.get("kpi_matches")
    if isinstance(kpi_matches, list):
        row["kpi_labels"] = "; ".join(str(k) for k in kpi_matches if str(k).strip())
    else:
        row["kpi_labels"] = ""

    return row, ctx, impact
