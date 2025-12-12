# VAMP NWU Implementation Audit

## 1. Executive Summary
- **What VAMP Offline now does:** Ingests artefacts, extracts text (with OCR fallback), classifies evidence using a fixed taxonomy, runs two LLM prompts for understanding/mapping, then deterministically aggregates KPI/KPA scores and can export a PA Excel without embedding scores.【F:backend/vamp_master.py†L78-L220】【F:backend/batch7_scorer.py†L3-L217】【F:backend/batch8_aggregator.py†L1-L339】【F:backend/batch10_pa_generator.py†L3-L228】
- **NWU TA/PA structural compliance:** TA parsing only captures “GRAND TOTAL: SECTION X” rows and fails on the provided TA workbook due to missing `properties`, so compliance is **partial**. PA parsing matches the `pa-report` sheet with correct column mapping. Contract merging honours TA hours/weights and PA outputs/KPIs with fuzzy name matching, but Addendum modules are only present in an expectations summary, not the merged contract.【F:backend/nwu_formats/ta_parser.py†L84-L139】【F:backend/nwu_formats/pa_reader.py†L105-L152】【F:backend/contracts/contract_builder.py†L1-L159】【419c3f†L1-L5】
- **Safety for performance review:** Deterministic scoring prevents the LLM from deciding final ratings/tiers, but TA parsing failure on real data, reliance on generated KPIs when PA data is absent, and incomplete Addendum propagation pose **medium risk** for institutional use.
- **High-level risk assessment:** **MEDIUM** — deterministic aggregation is present, yet upstream contract ingestion gaps and UI reliance on optional LLM components could lead to mis-scoring or missing evidence context.

## 2. Scope of Review
- **Batches reviewed:** 1–10 (evidence handling, taxonomy, TA/PA parsing and merge, LLM passes, aggregation, UI/UX, PA export).
- **Files/directories inspected:** `backend/nwu_formats`, `backend/contracts`, `backend/batch7_scorer.py`, `backend/batch8_aggregator.py`, `backend/batch10_pa_generator.py`, `backend/knowledge/evidence_taxonomy.json`, `backend/vamp_master.py`, `backend/evidence`, `frontend/offline_app/offline_app_gui_llm_csv.py`, `tests`.
- **Ground truth documents:** `Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx` (TA) and `Performance Agreement 55291597 2025.xlsx` (PA).

## 3. Canonical Contract Spine Verification (Batches 2–4)
### 3.1 Task Agreement Parsing
- **Responsible file:** `backend/nwu_formats/ta_parser.py` with `parse_nwu_ta` scanning rows for labels starting with “GRAND TOTAL: SECTION X”. Hours are taken from column D (index 3) and weights from column E (index 4).【F:backend/nwu_formats/ta_parser.py†L84-L139】 Sheet detection defaults to `Task Agreement Form` if present.【F:backend/nwu_formats/ta_parser.py†L77-L83】
- **Example extracted values:** The expectations parser (separate path) shows KPA hours 1337.62 (Teaching) and 203.0 (Leadership) from the provided TA, implying weights 79.59% and 12.08%.【419c3f†L1-L5】
- **Status:** ⚠️ **Partially correct.** Parsing ignores per-task rows, depends on workbook `properties` (raises `AttributeError` on the supplied TA), and lacks validation of total weights when rows are missing.

### 3.2 Addendum Parsing (Teaching Context)
- **Detection:** `_extract_teaching_modules_from_addendum` searches for sheets containing “AddendumB” and “Section 2”, extracting module codes via regex and returning a de-duplicated list.【F:backend/expectation_engine.py†L121-L147】
- **Storage:** Modules are attached to the expectation summary under `teaching_modules` and echoed into the KPA2 summary if present.【F:backend/expectation_engine.py†L187-L236】
- **Downstream use:** These modules are not written into the merged `PerformanceContract`; they remain contextual only, so scoring and PA export do not consider them.
- **Status:** ⚠️ **Partially correct.** Addendum data is captured for context but not propagated into contract/PA outputs.

### 3.3 Performance Agreement Reading
- **Sheet selection:** Explicitly targets the `pa-report` sheet via relationship resolution.【F:backend/nwu_formats/pa_reader.py†L31-L52】
- **Header mapping:** Row 2 columns A–G are taken as headers; A becomes the KPA key, B–G populate row fields with numeric coercion on D/E.【F:backend/nwu_formats/pa_reader.py†L125-L152】
- **Multi-line handling:** `_clean_text` replaces Excel line breaks; `_split_lines` returns lists for multi-line Outputs/KPIs.【F:backend/nwu_formats/pa_reader.py†L58-L73】
- **Status:** ✅ **Correct** for the provided PA layout.

### 3.4 Contract Merge Logic
- **Source precedence:** Hours/weights always from TA; outputs/KPIs/outcomes from PA using fuzzy KPA name matching. If KPIs are missing but outputs exist, they are auto-generated; PA `Active` flags toggle KPA activity.【F:backend/contracts/contract_builder.py†L1-L159】
- **Missing/conflicting data:** If no PA rows match, TA content is retained and `kpis_missing` is set; total weight is recomputed from TA only.【F:backend/contracts/contract_builder.py†L149-L159】
- **Status:** ⚠️ **Partially correct.** Merge assumes TA parsed successfully; Addendum modules and PA hours are ignored by design, and auto-generated KPIs may diverge from NWU-issued KPIs.

## 4. Evidence Handling & Taxonomy Compliance (Batches 1 & 6)
### 4.1 Artefact Extraction
- **Process:** `vamp_master.extract_text_for` routes by extension (PDF/DOCX/XLSX/PPTX) with OCR fallback for PDFs and warns when no text is extracted. Failed or unscored artefacts are skipped later by aggregation.【F:backend/vamp_master.py†L94-L220】【F:backend/batch8_aggregator.py†L248-L294】
- **Images/spreadsheets:** XLSX text is flattened row-wise; OCR handles scanned PDFs. No dedicated image metadata is kept beyond text content.
- **Status:** ✅ Extraction attempts all artefacts; failures are flagged and excluded from scoring.

### 4.2 Evidence Taxonomy
- **File:** `backend/knowledge/evidence_taxonomy.json` defines categories for Teaching, Research, Leadership, Social Responsiveness, OHS, plus weak evidence with credibility weights and KPI support lists.【F:backend/knowledge/evidence_taxonomy.json†L1-L170】
- **Examples:** Teaching rubric evidence carries weight 0.9 and maps to “Assessment standards” KPIs; Research “journal_article” has weight 1.3 and supports “Publish research outputs”.【F:backend/knowledge/evidence_taxonomy.json†L33-L137】
- **Status:** ✅ Taxonomy exists with credibility weights and KPI cues, though not all KPIs are enumerated.

## 5. LLM-Assisted Scoring Review (Batch 7)
### 5.1 Pass A — Evidence Understanding
- **Prompt boundaries:** PASS_A forbids ratings/KPAs and enforces a JSON schema with claims, modules, and confidence.【F:backend/batch7_scorer.py†L133-L155】
- **Failure modes:** JSON is repaired by trimming outer braces; low-confidence or empty-claim outputs downgrade status to `NEEDS_REVIEW`.【F:backend/batch7_scorer.py†L180-L217】【F:backend/batch7_scorer.py†L277-L307】
- **Status:** ✅ Schema-enforced understanding without scoring.

### 5.2 Pass B — Contract Mapping
- **KPI gating:** Prompt lists available KPIs; unmatched results zero out completion and force Needs Review tier.【F:backend/batch7_scorer.py†L157-L205】【F:backend/batch7_scorer.py†L309-L335】
- **Completion/aggregation:** Uses LLM-estimated completion but clamps and overrides low credibility; confidence aggregated as min of passes.【F:backend/batch7_scorer.py†L309-L343】
- **Status:** ✅ Mapping constrained to provided KPIs with deterministic fallbacks.

### 5.3 Deterministic Overrides
- **Final decision:** Tier and rating derived deterministically from completion; statuses force manual review on low confidence/credibility. LLM recommendations are stored but not decisive.【F:backend/batch7_scorer.py†L197-L343】
- **Status:** ✅ Final ratings/tiers are non-LLM.

## 6. Aggregation & Final Scoring (Batch 8)
### 6.1 Artefact Contribution Score (ACS)
- **Formula:** `completion_estimate * credibility_weight * confidence`, capped to [0,1] and capped at 0.4 for low-credibility evidence.【F:backend/batch8_aggregator.py†L154-L162】

### 6.2 KPI-Level Aggregation
- **KCS/Status:** KPI completion sums ACS per matched KPI then clamps; status thresholds: ≥0.8 Achieved, ≥0.5 Partially Achieved, else Not Achieved.【F:backend/batch8_aggregator.py†L248-L294】
- **Edge cases:** KPIs with no evidence are injected with 0 completion.【F:backend/batch8_aggregator.py†L282-L292】

### 6.3 KPA-Level Aggregation
- **KCR:** Average of KPI scores; missing KPIs force kcr=0. Evidence sufficiency check lowers kcr to ≤0.49 if confidence/credibility minima (0.5/0.7) not met.【F:backend/batch8_aggregator.py†L294-L324】
- **Weighting:** Overall completion is weight-sum of KCRs using TA weights.【F:backend/batch8_aggregator.py†L326-L338】

### 6.4 Final Rating & Tier Assignment
- **Rating bands:** Default five bands (Outstanding ≥0.85 … Does Not Meet ≤0.39).【F:backend/batch8_aggregator.py†L68-L74】【F:backend/batch8_aggregator.py†L180-L187】
- **Tier logic:** Based on rating and minimum KPA scores; low KPA forces Compliance/Needs Improvement tier.【F:backend/batch8_aggregator.py†L189-L201】
- **Justification:** Deterministic sentence summarising each KPA status and overall rating/tier.【F:backend/batch8_aggregator.py†L204-L217】

## 7. UI & UX Compliance (Batch 9)
- **Contract panel:** GUI description notes scrollable top section with staff/expectations and bottom pane showing evidence table + activity log simultaneously.【F:frontend/offline_app/offline_app_gui_llm_csv.py†L8-L21】
- **Visibility:** Table columns include filename, evidence type, KPA codes, KPI labels, status, rating, tier, confidence, impact summary; months/KPA selectors provided.【F:frontend/offline_app/offline_app_gui_llm_csv.py†L152-L198】
- **Activity log:** Maintained in resizable PanedWindow as per header notes; persistence relies on runtime session (no disk log).
- **Error handling:** Backend imports wrapped to fall back gracefully; missing dependencies trigger runtime warnings in the UI docstring but some `RuntimeError` is raised if `staff_profile` missing.【F:frontend/offline_app/offline_app_gui_llm_csv.py†L83-L134】
- **Status:** ⚠️ **Partial.** Layout intent documented, but persistence of activity log to disk is absent and UX depends on optional Ollama/contextual scorer availability.

## 8. PA Excel Generation (Batch 10)
- **Sheet/header:** Writes to `pa-report` with headers `KPA Name, Outputs, KPIs, Weight, Hours, Outcomes, Active` and bold formatting.【F:backend/batch10_pa_generator.py†L30-L228】
- **KPA ordering:** Fixed KPA_ORDER matching NWU sequence; pulls hours/weights from merged contract (TA source).【F:backend/batch10_pa_generator.py†L21-L208】
- **Rendering rules:** Outputs/outcomes joined with newlines; KPIs rendered with bullet + Measure/Target placeholders; active flag Y/N. No scoring data included.【F:backend/batch10_pa_generator.py†L68-L151】【F:backend/batch10_pa_generator.py†L190-L228】
- **Validation:** Ensures six KPA rows and total weight ≈100% before export.【F:backend/batch10_pa_generator.py†L153-L166】
- **Status:** ✅ Matches PA layout; however, depends on upstream contract completeness (e.g., missing Addendum modules/KPIs remain absent).

## 9. Testing & Coverage Assessment
- **Automated tests:** Pytest suite covers Batch7 scoring, Batch8 aggregation, Batch10 PA export, expectation parsing, and artefact processing; all 17 tests pass locally.【9311bb†L1-L10】
- **Coverage gaps:** No tests exercise `parse_nwu_ta`, real TA/PA merge flows, UI behaviour, or error handling when LLM/contextual scorer is unavailable.

## 10. Deviations, Gaps, and Risks
| Issue | File | Severity | Recommendation |
| --- | --- | --- | --- |
| TA parser crashes on provided NWU TA because `Workbook` lacks `properties`; ignores task rows and relies solely on GRAND TOTAL lines. | backend/nwu_formats/ta_parser.py【F:backend/nwu_formats/ta_parser.py†L84-L139】 | HIGH | Add defensive metadata handling, validate sheet layout, and parse task rows to confirm totals; add tests using real TA files. |
| Addendum module codes captured but not merged into contract or PA output, so teaching context is lost for scoring/export. | backend/expectation_engine.py【F:backend/expectation_engine.py†L121-L147】【F:backend/contracts/contract_builder.py†L1-L159】 | MEDIUM | Propagate teaching_modules into merged contract and PA export, or explicitly document exclusion. |
| Automatic KPI generation when PA KPIs absent may diverge from institutional KPIs, risking misalignment. | backend/contracts/contract_builder.py【F:backend/contracts/contract_builder.py†L131-L159】 | MEDIUM | Require explicit PA KPIs or flag missing KPIs for manual completion instead of auto-generation. |
| UI activity log not persisted; reliance on optional Ollama/contextual scorer without clear fallback can block scoring. | frontend/offline_app/offline_app_gui_llm_csv.py【F:frontend/offline_app/offline_app_gui_llm_csv.py†L83-L134】 | MEDIUM | Persist logs to file and surface clear offline-only mode when LLM components are unavailable. |
| Evidence extraction flattens XLSX content without structure and drops metadata for images beyond text, limiting audit trails. | backend/vamp_master.py【F:backend/vamp_master.py†L94-L220】 | LOW | Store basic metadata (sheet names, image hashes) alongside extracted text to improve traceability. |

## 11. Final Verdict
- **NWU-compliant?** **PARTIAL.** PA parsing/export and deterministic scoring align with the spec, but TA ingestion failures and missing Addendum/KPI fidelity break full compliance.
- **Safe for performance review?** **Conditionally**, with manual verification of TA parsing and KPI completeness; otherwise risk of mis-weighted scores.
- **Must fix before production:** Stabilise TA parser against real workbooks, ensure Addendum/module data and authoritative KPIs propagate through contract and export, and harden UI fallbacks/logging.

## 12. Appendix — Traceability Table

| Batch | Requirement | File(s) | Status | Notes |
| --- | --- | --- | --- | --- |
| 1 | Evidence ingestion/extraction | backend/vamp_master.py | Partial | Extracts all artefacts with OCR warnings; limited metadata for images/XLSX. 【F:backend/vamp_master.py†L78-L220】 |
| 2 | TA parsing baseline | backend/nwu_formats/ta_parser.py | Partial | Grand total-only parsing; crash on provided TA. 【F:backend/nwu_formats/ta_parser.py†L84-L139】 |
| 3 | PA reading | backend/nwu_formats/pa_reader.py | Complete | Targets `pa-report`, column mapping A–G. 【F:backend/nwu_formats/pa_reader.py†L31-L152】 |
| 4 | TA/PA merge | backend/contracts/contract_builder.py | Partial | TA hours/weights kept; PA outputs/KPIs merged; KPI auto-generation; no Addendum propagation. 【F:backend/contracts/contract_builder.py†L1-L159】 |
| 5 | Contract expectations | backend/expectation_engine.py | Partial | Captures teaching modules and KPA hours but not merged into contract. 【F:backend/expectation_engine.py†L121-L236】 |
| 6 | Evidence taxonomy | backend/knowledge/evidence_taxonomy.json | Complete | KPA-aligned evidence types with credibility weights. 【F:backend/knowledge/evidence_taxonomy.json†L1-L170】 |
| 7 | LLM-assisted passes | backend/batch7_scorer.py | Complete | Two-pass prompts with deterministic overrides. 【F:backend/batch7_scorer.py†L133-L343】 |
| 8 | Deterministic aggregation | backend/batch8_aggregator.py | Complete | ACS/KCS/KCR, rating bands, tier logic. 【F:backend/batch8_aggregator.py†L154-L338】 |
| 9 | UI/UX | frontend/offline_app/offline_app_gui_llm_csv.py | Partial | Layout described; dependence on optional LLM and no log persistence. 【F:frontend/offline_app/offline_app_gui_llm_csv.py†L8-L198】 |
| 10 | PA export | backend/batch10_pa_generator.py | Complete | `pa-report` layout with validation; no scoring data. 【F:backend/batch10_pa_generator.py†L30-L228】 |
