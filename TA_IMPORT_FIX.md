# TA Import Fix - December 17, 2025

## Problem
TA import was only creating 4 expectations from 2 KPAs instead of comprehensive coverage (48+ tasks across all 5 KPAs).

## Root Cause
The `/api/ta/import` endpoint was trying to parse Excel files which may not exist or fail parsing. The system already had a complete contract JSON file (`contract_20172672_2025.json`) but wasn't using it.

## Solution Implemented

### 1. **Modified TA Import Endpoint** (`run_web.py`)
- Now checks for existing contract file first
- If `contract_{staff_id}_{year}.json` exists, uses it directly
- Calls `build_expectations_from_ta()` with contract data
- Falls back to Excel parsing only if contract doesn't exist
- Generates expectations file with 48 tasks

### 2. **Added Rebuild Endpoint** (`/api/expectations/rebuild`)
- POST endpoint that regenerates expectations from existing contract
- Can be called anytime to refresh expectations
- Returns task count and KPA count
- Useful when contract exists but expectations need regeneration

### 3. **Updated Frontend** (`app.js`)
- "Rebuild expectations" button now calls `/api/expectations/rebuild`
- Displays progress: "Rebuilt X tasks across Y KPAs"
- Auto-triggers rebuild if TA import returns < 10 tasks (safety check)
- Reloads expectations after successful rebuild

## Testing
```bash
# Test rebuild endpoint
curl -X POST -H "Content-Type: application/json" \
  -d '{"staff_id":"20172672","year":"2025"}' \
  http://localhost:5000/api/expectations/rebuild

# Expected: {"status": "success", "tasks_count": 48, "kpas_count": 5}

# Test expectations load
curl "http://localhost:5000/api/expectations?staff_id=20172672&year=2025" | jq '.tasks | length'
# Expected: 48
```

## Usage
1. **If contract exists**: Just click "Rebuild expectations" button
2. **If uploading new TA**: Upload Excel file, system auto-generates expectations
3. **If low task count**: System auto-triggers rebuild after 1 second

## Files Modified
- `/workspaces/Vamp-Offline/run_web.py` - Added rebuild endpoint, modified import logic
- `/workspaces/Vamp-Offline/app.js` - Added rebuild button handler, auto-retry logic

## Result
✅ Now generates 48 tasks across all 5 KPAs
✅ Works with existing contract files
✅ Fallback Excel parsing still available
✅ Auto-recovery if import fails
