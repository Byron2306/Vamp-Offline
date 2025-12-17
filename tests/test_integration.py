"""
Integration tests to verify all major features of the VAMP Offline system.
"""
import json
import tempfile
from pathlib import Path

import pytest

from backend.staff_profile import StaffProfile, KPA, KPI, create_or_load_profile
from backend.contracts.task_agreement_import import import_task_agreement_excel
from backend.vamp_master import extract_text_for, generate_run_id
from backend.expectation_engine import parse_task_agreement

# Test constants
WEIGHT_TOLERANCE = 1.0  # Allow 1% tolerance for total weight validation


class TestIntegration:
    """Integration tests for end-to-end workflows."""

    def test_ta_parsing_with_real_file(self):
        """Test that we can parse the actual TA file without crashing."""
        ta_file = Path("Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx")
        
        if not ta_file.exists():
            pytest.skip("TA file not found")
        
        # Parse the TA
        summary = parse_task_agreement(str(ta_file), director_level=False)
        
        # Verify basic structure
        assert isinstance(summary, dict)
        assert "kpa_summary" in summary
        assert "norm_hours" in summary
        
        # Verify KPAs were found
        kpa_summary = summary["kpa_summary"]
        assert len(kpa_summary) > 0
        
        # Verify teaching modules were extracted
        assert "teaching_modules" in summary
        modules = summary["teaching_modules"]
        assert isinstance(modules, list)

    def test_contract_import_workflow(self):
        """Test creating a profile and importing TA contract."""
        ta_file = Path("Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx")
        
        if not ta_file.exists():
            pytest.skip("TA file not found")
        
        # Create profile
        profile = create_or_load_profile(
            staff_id="test_integration_001",
            name="Integration Test User",
            position="Lecturer",
            cycle_year=2024,
            faculty="Test Faculty"
        )
        
        # Import TA
        profile = import_task_agreement_excel(profile, ta_file)
        
        # Verify import
        assert "TA_IMPORTED" in profile.flags
        assert len(profile.kpas) == 5  # Should have 5 standard KPAs
        
        # Verify TA context was attached
        for kpa in profile.kpas:
            if kpa.code in ["KPA1", "KPA2", "KPA3", "KPA4", "KPA5"]:
                assert kpa.ta_context is not None
                assert "hours" in kpa.ta_context or "weight_pct" in kpa.ta_context

    def test_evidence_extraction(self, tmp_path):
        """Test text extraction from various file types."""
        # Create a test text file in temporary directory
        txt_file = tmp_path / "test_evidence.txt"
        txt_content = "This is a teaching rubric for module BSTE312. It assesses student learning outcomes."
        txt_file.write_text(txt_content)
        
        # Test extraction
        result = extract_text_for(txt_file)
        
        assert result.extract_status == "ok"
        assert txt_content in result.extracted_text
        assert len(result.extracted_text) > 0

    def test_run_id_generation(self):
        """Test that run IDs are generated correctly."""
        run_id = generate_run_id()
        
        assert run_id.startswith("run-")
        assert len(run_id) > 10
        
        # Generate another one - should be different
        run_id2 = generate_run_id()
        assert run_id != run_id2

    def test_staff_profile_persistence(self):
        """Test that staff profiles can be saved and loaded."""
        # Create a profile
        profile = StaffProfile(
            staff_id="test_persist_001",
            name="Persist Test User",
            position="Senior Lecturer",
            cycle_year=2024,
            faculty="Test Faculty",
            kpas=[
                KPA(
                    code="KPA1",
                    name="Teaching and Learning",
                    weight=80.0,
                    hours=1400.0,
                    kpis=[
                        KPI(
                            kpi_id="KPI1_1",
                            description="Deliver quality teaching",
                            outputs="Lectures and materials"
                        )
                    ]
                )
            ]
        )
        
        # Save it
        profile.save()
        
        # Verify file exists
        assert profile.contract_path.exists()
        
        # Load it back
        loaded_data = json.loads(profile.contract_path.read_text())
        
        assert loaded_data["staff_id"] == "test_persist_001"
        assert loaded_data["name"] == "Persist Test User"
        assert len(loaded_data["kpas"]) == 1
        assert loaded_data["kpas"][0]["code"] == "KPA1"

    def test_kpa_structure_validation(self):
        """Test that KPA structures are validated correctly."""
        # Create a profile with all KPAs
        profile = StaffProfile(
            staff_id="test_kpa_validation",
            name="KPA Test User",
            position="Lecturer",
            cycle_year=2024,
            kpas=[
                KPA(code="KPA1", name="Teaching and Learning", weight=70.0, hours=1200.0),
                KPA(code="KPA2", name="OHS", weight=0.5, hours=10.0),
                KPA(code="KPA3", name="Research", weight=20.0, hours=350.0),
                KPA(code="KPA4", name="Leadership", weight=7.5, hours=130.0),
                KPA(code="KPA5", name="Social Responsiveness", weight=2.0, hours=35.0),
            ]
        )
        
        # Verify total weight is approximately 100%
        total_weight = sum(kpa.weight for kpa in profile.kpas if kpa.weight)
        assert abs(total_weight - 100.0) < WEIGHT_TOLERANCE

    def test_kpi_structure(self):
        """Test that KPI structures work correctly."""
        kpi = KPI(
            kpi_id="TEST_KPI_001",
            description="Test KPI description",
            outputs="Test outputs",
            outcomes="Test outcomes",
            measure="Test measure",
            target="Test target",
            evidence_types=["document", "report"],
            weight=50.0,
            hours=875.0
        )
        
        assert kpi.kpi_id == "TEST_KPI_001"
        assert kpi.active is True  # Should default to True
        assert kpi.generated_by_ai is False  # Should default to False
        assert len(kpi.evidence_types) == 2
