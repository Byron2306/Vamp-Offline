# VAMP Offline - Evidence-Based Performance Assessment

VAMP (Validation, Assessment, and Management Platform) Offline is a comprehensive system for managing academic performance agreements and evidence-based assessment for NWU (North-West University) staff.

## Features

- **Task Agreement (TA) Parsing**: Import and parse NWU Task Agreement Excel files
- **Performance Agreement (PA) Management**: Read and generate PA reports
- **Evidence Extraction**: Extract text from various document formats (PDF, DOCX, XLSX, PPTX, TXT)
- **Deterministic Scoring**: Score evidence using NWU brain scorer with KPA routing and tier detection
- **Evidence Aggregation**: Aggregate evidence across KPIs and KPAs with completion tracking
- **PA Report Generation**: Generate standardized PA Excel reports
- **Offline GUI**: Tkinter-based graphical interface for evidence scanning and scoring

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Required Dependencies

```bash
pip install pytest requests pillow openpyxl pandas
```

### Optional Dependencies (for enhanced features)

```bash
# For OCR support
pip install pytesseract pdf2image

# For PDF processing
pip install pdfminer.six pdfplumber pikepdf

# For DOCX/PPTX processing
pip install python-docx python-pptx
```

## Quick Start

### Running the GUI Application

```bash
python run_offline.py
```

This launches the Tkinter GUI for:
- Loading staff profiles
- Importing Task Agreements
- Scanning evidence folders
- Scoring and aggregating evidence
- Generating PA reports

### Using as a Library

```python
from backend.staff_profile import create_or_load_profile
from backend.contracts.task_agreement_import import import_task_agreement_excel
from pathlib import Path

# Create a staff profile
profile = create_or_load_profile(
    staff_id="12345",
    name="Jane Doe",
    position="Senior Lecturer",
    cycle_year=2024,
    faculty="Faculty of Education"
)

# Import Task Agreement
ta_file = Path("task_agreement.xlsx")
profile = import_task_agreement_excel(profile, ta_file)

# Profile is now ready for evidence scanning
print(f"Imported {len(profile.kpas)} KPAs")
```

## Testing

Run the test suite to verify all features:

```bash
# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_integration.py -v
pytest tests/test_batch7_scorer.py -v
pytest tests/test_batch8_aggregator.py -v
```

**Current Status**: ✅ 31 tests passing, 1 skipped (GUI in headless environment)

See [TEST_REPORT.md](TEST_REPORT.md) for detailed test results.

## Architecture

### Backend Modules

- **staff_profile.py**: Staff profile and contract management
- **vamp_master.py**: Evidence ingestion and text extraction
- **expectation_engine.py**: TA parsing and expectation building
- **nwu_brain_scorer.py**: Deterministic evidence scoring
- **batch7_scorer.py**: Evidence understanding and KPI mapping
- **batch8_aggregator.py**: Evidence aggregation and rating calculation
- **batch10_pa_generator.py**: PA Excel report generation

### Contract Management

- **task_agreement_import.py**: Import TA Excel files
- **pa_excel.py**: PA Excel generation
- **pa_generator.py**: PA skeleton generation
- **validation.py**: Contract validation

### NWU Formats

- **ta_parser.py**: Parse NWU Task Agreement format
- **pa_reader.py**: Read NWU Performance Agreement format

## Key Concepts

### KPAs (Key Performance Areas)

The system uses 5 standard KPAs aligned with NWU structure:

1. **KPA1**: Teaching and Learning
2. **KPA2**: Occupational Health and Safety
3. **KPA3**: Research and Innovation / Creative Outputs
4. **KPA4**: Academic Leadership and Management
5. **KPA5**: Social Responsiveness / Community Engagement

For directors, a 6th KPA (People Management) is included.

### KPIs (Key Performance Indicators)

Each KPA contains multiple KPIs that define specific outputs, outcomes, measures, and targets.

### Evidence Scoring

Evidence is scored using:
- **Credibility Weight**: Based on evidence type (e.g., rubric = 0.9, screenshot = 0.3)
- **Completion Estimate**: How much the evidence contributes to KPI completion
- **Confidence**: LLM or system confidence in the mapping
- **Tier**: Transformational / Developmental / Compliance

### Aggregation

- **ACS (Artefact Contribution Score)**: completion × credibility × confidence
- **KCS (KPI Completion Score)**: Sum of ACS per KPI (capped at 1.0)
- **KCR (KPA Completion Rating)**: Average of KPI scores
- **Overall Rating**: Weighted sum of KCRs using TA weights

## Data Storage

### Contract Files

Contracts are stored as JSON in `backend/data/contracts/`:
- Format: `contract_{staff_id}_{year}.json`
- Contains KPAs, KPIs, weights, hours, and context

### Evidence Data

Evidence and scoring results are stored in:
- CSV format for tabular data
- JSON for detailed scoring metadata

## Configuration

### Evidence Taxonomy

Evidence types and credibility weights are defined in:
`backend/knowledge/evidence_taxonomy.json`

### NWU Brain Configuration

Scoring rules are in `backend/data/nwu_brain/`:
- `kpa_router.json`: KPA routing rules
- `values_index.json`: NWU core values
- `tier_keywords.json`: Tier classification
- `policy_registry.json`: Policy detection

## Limitations and Design Decisions

1. **Addendum Modules**: Teaching modules from Addendum B are extracted but remain in context only, not propagated to final PA export.

2. **Auto-Generated KPIs**: When PA KPIs are missing, the system can auto-generate them. These should be reviewed for institutional alignment.

3. **LLM Features**: Optional Ollama integration for contextual scoring. System works offline without LLM.

4. **GUI**: Requires display for Tkinter GUI. Core library functions work in headless environments.

## Contributing

When contributing:

1. Run the full test suite: `pytest tests/ -v`
2. Ensure all tests pass
3. Add tests for new features
4. Update documentation

## Audit and Compliance

See [VAMP_NWU_IMPLEMENTATION_AUDIT.md](VAMP_NWU_IMPLEMENTATION_AUDIT.md) for:
- Detailed implementation audit
- NWU format compliance review
- Security assessment
- Risk analysis

## Support

For issues or questions:
- Check [TEST_REPORT.md](TEST_REPORT.md) for known limitations
- Review test files in `tests/` for usage examples
- Check the audit document for implementation details

## License

[Add license information here]

## Version

Current Version: 1.0.0 (Tested and Verified - December 2025)
