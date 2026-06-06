#!/usr/bin/env python3
"""Rebuild expectations from TA, verify fixes, save updated JSON, and resync tasks in DB."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.expectation_engine import parse_task_agreement, build_expectations_from_ta
from mapper import ensure_tasks
from progress_store import ProgressStore

STAFF_ID = "20172672"
YEAR = 2026
TA_PATH = "/home/byron/Downloads/B Bunt 2026 FEDU_Task_Agreement_Form (5).xlsx"
EXPECT_OUT = f"backend/data/staff_expectations/expectations_{STAFF_ID}_{YEAR}.json"

print(f"=== Rebuilding expectations from {TA_PATH} ===")
ta_summary = parse_task_agreement(TA_PATH)
result = build_expectations_from_ta(STAFF_ID, YEAR, ta_summary)
tasks = result.get("tasks", [])
print(f"Generated {len(tasks)} tasks total")

# Verify ROR fix
ror_tasks = [t for t in tasks if "ror" in t.get("title", "").lower() or "orientation" in t.get("title", "").lower()]
print("\n--- ROR tasks (should all be January only) ---")
for t in ror_tasks:
    print(f"  months={t.get('months')} | {t.get('title')}")

# Verify research + January
r_jan = [t for t in tasks if t.get("kpa_code") == "KPA3" and 1 in (t.get("months") or [])]
print(f"\n--- Research tasks that include January ({len(r_jan)}) ---")
for t in r_jan:
    print(f"  months={t.get('months')} | {t.get('title','')[:70]}")

# Show Jan/Feb/Mar task counts
for m in [1, 2, 3]:
    month_tasks = [t for t in tasks if m in (t.get("months") or [])]
    print(f"\nMonth {m}: {len(month_tasks)} tasks")
    for t in month_tasks:
        print(f"  [{t.get('kpa_code')}] {t.get('title','')[:75]}")

# Backup and save
import shutil
if os.path.exists(EXPECT_OUT):
    shutil.copy(EXPECT_OUT, EXPECT_OUT + ".pre_rebuild_bak")
    print(f"\nBacked up old expectations to {EXPECT_OUT}.pre_rebuild_bak")

with open(EXPECT_OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(f"Saved new expectations to {EXPECT_OUT}")

# Resync tasks in DB
print("\n=== Resyncing tasks in database ===")
store = ProgressStore()
count_before = len([dict(r) for r in store.list_tasks_for_window(YEAR, list(range(1, 13)), kpa_code=None)])
print(f"Tasks before resync: {count_before}")

ensure_tasks(store, staff_id=STAFF_ID, year=YEAR, expectations=result)

count_after = len([dict(r) for r in store.list_tasks_for_window(YEAR, list(range(1, 13)), kpa_code=None)])
print(f"Tasks after resync: {count_after}")
print("\n=== Done. Ready to run Outlook collection. ===")
