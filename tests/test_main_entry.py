"""
Test the main entry points to ensure the application can start.
"""
import sys
from pathlib import Path

import pytest


class TestMainEntry:
    """Test main application entry points."""

    def test_run_offline_imports(self):
        """Test that run_offline.py can be imported without errors."""
        # Add root to path
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        
        # Try to import - this will fail if there are syntax errors or missing dependencies
        try:
            import run_offline
            # Import succeeded - verify the module is loaded
            assert run_offline is not None
            assert hasattr(run_offline, '__file__')
        except ModuleNotFoundError as e:
            # tkinter is expected to be missing in headless environments
            if 'tkinter' in str(e).lower():
                pytest.skip("Tkinter not available in headless environment")
            else:
                raise

    def test_backend_modules_import(self):
        """Test that all backend modules can be imported."""
        modules = [
            'backend.staff_profile',
            'backend.vamp_master',
            'backend.expectation_engine',
            'backend.nwu_brain_scorer',
            'backend.evidence_store',
            'backend.batch7_scorer',
            'backend.batch8_aggregator',
            'backend.batch10_pa_generator',
        ]
        
        for module_name in modules:
            try:
                __import__(module_name)
            except Exception as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_contracts_modules_import(self):
        """Test that contract modules can be imported."""
        modules = [
            'backend.contracts.task_agreement_import',
            'backend.contracts.pa_excel',
            'backend.contracts.pa_generator',
            'backend.contracts.validation',
        ]
        
        for module_name in modules:
            try:
                __import__(module_name)
            except Exception as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_nwu_formats_modules_import(self):
        """Test that NWU format modules can be imported."""
        modules = [
            'backend.nwu_formats.ta_parser',
            'backend.nwu_formats.pa_reader',
        ]
        
        for module_name in modules:
            try:
                __import__(module_name)
            except Exception as e:
                pytest.fail(f"Failed to import {module_name}: {e}")
