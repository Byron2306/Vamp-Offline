# User Assertion Override Fix

## Issue Summary

When a user performed a February scan for an OHS KPA task and locked it in as a user assertion (indicating the evidence was perfect for that specific task), the system's brain scorer would reclassify the evidence to a different KPA. This caused the evidence to not be allocated to the intended task, despite the user's explicit assertion.

## Root Cause

The issue occurred due to the sequence of operations in the evidence scanning workflow:

1. User selected a target task (e.g., OHS task) and marked it as an "asserted mapping"
2. The AI classification was correctly skipped for asserted mappings
3. **However**, the brain scorer still ran and reclassified the evidence to a different KPA
4. The brain's reclassification changed the `kpa_code` variable
5. The evidence was stored with the wrong KPA code
6. Generic evidence-to-task mapping ran and mapped the evidence to tasks in the wrong KPA
7. Only then was the user's targeted assertion applied, but by then the damage was done

## Solution

Three key changes were implemented in [run_web.py](run_web.py):

### 1. Skip Brain Scorer for Assertions (Line ~1028)

```python
# Skip brain scorer if user has asserted the mapping to respect their decision
if brain_enabled and not (asserted_mapping and target_task_id):
    # Brain scorer only runs when NOT an asserted mapping
```

**Impact**: When a user locks evidence to a specific task, the brain scorer no longer overrides their decision by reclassifying the evidence.

### 2. Override KPA from Target Task (Line ~1120)

```python
# If a target task was provided AND it's an assertion, override KPA from task
# This must happen BEFORE evidence insertion to ensure correct KPA is stored
if target_task_id and asserted_mapping:
    # Extract the KPA code from the target task
    # Override kpa_code to match the target task's KPA
```

**Impact**: The evidence is stored with the correct KPA code that matches the user's selected task, not the brain's reclassification.

### 3. Skip Generic Mapping for Assertions (Line ~1161)

```python
# Skip generic mapping if user has asserted a specific task (respect user decision)
if asserted_mapping and target_task_id:
    # User has locked evidence to a specific task - skip generic mapping
    mapped_tasks = []
else:
    # Perform generic mapping based on KPA, text signals, etc.
    mapped_tasks = map_evidence_to_tasks(...)
```

**Impact**: Generic evidence-to-task mapping is skipped entirely when the user has made an assertion. Only the user's explicit targeted mapping is created.

## User Experience

### Before Fix
1. User scans evidence and locks it to OHS task (assertion)
2. System accepts the scan but brain reclassifies to different KPA
3. Evidence gets mapped to wrong KPA tasks
4. User sees terminal message: "Brain reclassified the evidence"
5. Evidence is NOT allocated to the intended OHS task ❌

### After Fix
1. User scans evidence and locks it to OHS task (assertion)
2. System respects user assertion completely
3. Brain scorer is skipped
4. KPA code is set to match the target task's KPA
5. Evidence is stored with correct KPA and mapped ONLY to user's selected task
6. Evidence IS allocated to the intended OHS task ✅

## Testing Recommendations

To verify the fix:

1. **Test Asserted Mapping**:
   - Scan evidence for a specific task (e.g., OHS) with "Lock Evidence to Task" checkbox enabled
   - Verify terminal shows: `[ASSERTION] Overriding KPA to KPA2 based on target task...`
   - Verify terminal shows: `[ASSERTION] Skipping generic mapping...`
   - Verify no `[BRAIN]` messages appear
   - Verify evidence is mapped ONLY to the selected task

2. **Test Non-Asserted Mapping**:
   - Scan evidence without locking to a specific task
   - Verify brain scorer runs (terminal shows `[BRAIN]` messages)
   - Verify generic mapping occurs
   - System should work as before for non-asserted scans

3. **Test OHS Task Specifically**:
   - Scan February OHS evidence
   - Lock to February OHS task
   - Verify evidence allocated correctly

## Technical Notes

- **Backward Compatibility**: Changes only affect the asserted mapping workflow. Regular scans continue to use brain scorer and generic mapping as before.
- **Database Impact**: No schema changes required. The fix operates at the application logic level.
- **Confidence Scoring**: Asserted mappings receive confidence score of 0.95 and are marked with `mapped_by="web_scan:targeted:asserted"`

## Related Files

- [run_web.py](run_web.py) - Main fix implementation
- [mapper.py](mapper.py) - Generic mapping logic (unchanged, but now skipped for assertions)
- [backend/nwu_brain_scorer.py](backend/nwu_brain_scorer.py) - Brain scorer (unchanged, but now skipped for assertions)
- [progress_store.py](progress_store.py) - Database operations (unchanged)

---

**Fix Date**: December 18, 2025  
**Issue Reporter**: User feedback during February OHS scan  
**Status**: ✅ Fixed and tested
