#!/usr/bin/env python3
"""Test expectations generation"""

import json
from pathlib import Path
from backend.expectation_engine import build_expectations_from_ta

# Load the existing contract
contract_file = Path("backend/data/contracts/contract_20172672_2025.json")

with open(contract_file, 'r') as f:
    ta_summary = json.load(f)

print("TA Summary loaded:")
print(f"  KPAs: {list(ta_summary.get('kpa_summary', {}).keys())}")

# Build expectations
print("\nBuilding expectations...")
expectations = build_expectations_from_ta("20172672", 2025, ta_summary)

print(f"\nExpectations generated:")
print(f"  Total tasks: {len(expectations.get('tasks', []))}")
print(f"  KPAs in summary: {list(expectations.get('kpa_summary', {}).keys())}")
print(f"  Months covered: {len(expectations.get('by_month', {}))}")

# Show sample tasks
print(f"\nSample tasks (first 5):")
for i, task in enumerate(expectations.get('tasks', [])[:5]):
    print(f"  {i+1}. [{task['kpa_code']}] {task['title']} (months: {task['months']})")

# Save to file
output_dir = Path("backend/data/staff_expectations")
output_dir.mkdir(parents=True, exist_ok=True)
output_file = output_dir / "expectations_20172672_2025.json"

with open(output_file, 'w') as f:
    json.dump(expectations, f, indent=2)

print(f"\n✓ Expectations saved to: {output_file}")
print(f"  File size: {output_file.stat().st_size} bytes")
