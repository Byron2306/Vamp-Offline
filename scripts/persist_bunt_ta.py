#!/usr/bin/env python3
import shutil, json, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STAFF = '20172672'
YEAR = '2025'
TA_XLSX = ROOT / '2025 FEDU_Task_Agreement_Form (V1_test) B Bunt.xlsx'
EXPECT_DIR = ROOT / 'backend' / 'data' / 'staff_expectations'
PROG_DIR = ROOT / 'backend' / 'data' / 'progress'
EXPECT_FILE = EXPECT_DIR / f'expectations_{STAFF}_{YEAR}.json'
PROG_DB = PROG_DIR / 'progress.db'

print('TA file:', TA_XLSX.exists(), TA_XLSX)

# Backups
ts = int(time.time())
if EXPECT_FILE.exists():
    bak = EXPECT_FILE.with_name(f"{EXPECT_FILE.stem}.{ts}.bak")
    shutil.copy2(EXPECT_FILE, bak)
    print('Backed up expectations to', bak)
else:
    print('No existing expectations to back up')

if PROG_DB.exists():
    bakdb = PROG_DB.with_name(f"{PROG_DB.stem}.{ts}.bak")
    shutil.copy2(PROG_DB, bakdb)
    print('Backed up progress DB to', bakdb)
else:
    print('No existing progress DB to back up')

# Run parser
from backend.expectation_engine import parse_task_agreement, build_expectations_from_ta

if not TA_XLSX.exists():
    print('TA workbook not found:', TA_XLSX)
    sys.exit(2)

print('Parsing TA workbook...')
ta_summary = parse_task_agreement(str(TA_XLSX))
print('TA summary keys:', list(ta_summary.keys()))

print('Building expectations...')
expectations = build_expectations_from_ta(STAFF, int(YEAR), ta_summary)

print('Generated tasks:', len(expectations.get('tasks', [])))

# Persist expectations
EXPECT_DIR.mkdir(parents=True, exist_ok=True)
with open(EXPECT_FILE, 'w') as f:
    json.dump(expectations, f, indent=2)

print('Wrote expectations to', EXPECT_FILE)

# Upsert tasks into DB using mapper.ensure_tasks
from progress_store import ProgressStore
from mapper import ensure_tasks
store = ProgressStore()
ensure_tasks(store, staff_id=STAFF, year=int(YEAR), expectations=expectations)

# Verify DB count
tasks = store.list_tasks_for_window(STAFF, int(YEAR))
print('Tasks now in DB for', STAFF, YEAR, ':', len(tasks))

print('Done')
