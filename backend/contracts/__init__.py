"""Contracts package: staff profiles, KPAs, KPIs and task-agreement import.

This is Batch 1 of the 'contract brain' for the offline VAMP app.
"""

from .models import StaffProfile, KPA, KPI, create_default_kpas  # noqa: F401
from .storage import save_contract, load_contract, contract_path  # noqa: F401
