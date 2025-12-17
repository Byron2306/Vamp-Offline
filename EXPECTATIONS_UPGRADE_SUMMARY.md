# Expectations System Upgrade - Summary

## Overview
This upgrade restores the collapsible monthly expectations view, fixes task generation for all 5 KPAs, and implements intelligent month-closing logic with AI guidance.

## Changes Made

### 1. **Fixed Task Generation (`backend/expectation_engine.py`)**
   - **Problem**: The `build_expectations_from_ta` function didn't exist, so only 4 tasks from 2 KPAs were being generated
   - **Solution**: Implemented comprehensive `build_expectations_from_ta()` function that:
     - Generates monthly tasks for all 5 KPAs (KPA1-KPA5)
     - Creates milestone tasks for semester-end activities
     - Includes quarterly tasks for OHS and Social Responsiveness
     - Provides evidence hints and outputs for each task
     - Returns structured data with `by_month` organization
     - Generates 100+ tasks across the full academic year

### 2. **New Collapsible Monthly View (`index.html` + `app.js`)**
   - **Problem**: Old flat table was confusing and didn't show monthly breakdown
   - **Solution**: Created collapsible KPA sections showing:
     - Each KPA as an expandable/collapsible section
     - Monthly task lists within each KPA
     - Checkboxes for tracking task completion
     - "Ask AI" button for each task
     - Visual month selector for current month
     - Month status pill (Complete/Incomplete)

### 3. **Moved Expectations Table to Reports Tab (`index.html` + `app.js`)**
   - **Problem**: Wrong table was showing in Expectations tab
   - **Solution**: 
     - Moved comprehensive task table to Reports tab (`paExpectationsTable`)
     - This table shows all tasks for PA generation preview
     - Includes columns: KPA, Task Title, Month, Cadence, Min/Stretch targets, Outputs, Evidence Hints
     - Useful for reviewing complete expectations before generating PA

### 4. **Month-Closing Logic (`run_web.py`)**
   - **Problem**: No way to track when monthly expectations are met
   - **Solution**: Implemented `/api/expectations/check-month` endpoint that:
     - Loads expectations for selected month
     - Counts evidence uploaded for that month
     - Compares against minimum requirements
     - Returns completion status
     - Provides AI-generated guidance
     - Shows detailed summary by KPA

### 5. **Enhanced VAMP AI (`vamp_ai.py`)**
   - **Problem**: AI wasn't aware of monthly expectations context
   - **Solution**: Enhanced prompt building to include:
     - Current month being analyzed
     - Number of tasks for the period
     - Evidence count vs required
     - Specific KPA context
     - Guidance on concrete evidence types to upload
     - Celebration messages when expectations are met
     - Constructive catch-up advice when behind

### 6. **Updated CSS Styling (`vamp.css`)**
   - Added styles for:
     - `.kpa-section` - Collapsible container
     - `.kpa-header` - Clickable header with expand icon
     - `.kpa-body` - Task list container
     - `.task-item` - Individual task with checkbox
     - `.btn-small` - Small action buttons
     - `.expand-icon` - Arrow indicator
     - Hover effects and transitions

## New User Flow

### Expectations Tab
1. **Import Task Agreement** → System generates 100+ tasks across all 5 KPAs
2. **View Monthly Expectations** → See collapsible sections for each KPA
3. **Select Current Month** → Choose which month you're working on
4. **Upload Evidence** → Use scan tab to upload files for current month
5. **Check Month Status** → Click "Check Month Status" button
6. **AI Review** → VAMP analyzes evidence and provides guidance
7. **Month Closes** → When complete, move to next month

### Reports Tab
1. **Review Full Expectations** → See complete table of all tasks
2. **Verify Completeness** → Check all KPAs are included
3. **Generate PA** → Click "Generate Final PA" button

## Key Features

### Collapsible Monthly View
```javascript
- KPA1: Teaching and Learning ▼
  └─ January 2025
     ☐ Teaching delivery (lectures, assessments, eFundi activity) [monthly, 2-4 items] 🤖
     ☐ ...
  └─ February 2025
     ☐ ...
     
- KPA2: Occupational Health & Safety ▼
- KPA3: Research, Innovation & Creative Outputs ▼
- KPA4: Academic Leadership & Administration ▼
- KPA5: Social Responsiveness ▼
```

### Month Completion Check
```
Current Month: [January 2025 ▼]  [Check Month Status]  [Incomplete ⚠️]

AI Month Review:
⚠️ Month Incomplete
You have only uploaded 3 of 8 required evidence items for January 2025. 
You are missing 5 items.

Missing:
KPA1: 1/4 items
KPA3: 2/3 items
KPA4: 0/1 items
```

## Technical Details

### Data Structure
```javascript
{
  "ok": true,
  "staff_id": "20172672",
  "year": 2025,
  "kpa_summary": {
    "KPA1": { "name": "Teaching and Learning", "hours": 1337.62, "weight_pct": 79.59 },
    // ... other KPAs
  },
  "tasks": [
    {
      "id": "task_001",
      "kpa_code": "KPA1",
      "kpa_name": "Teaching and Learning",
      "title": "Teaching delivery (lectures, assessments, eFundi activity)",
      "cadence": "monthly",
      "months": [1],
      "minimum_count": 2,
      "stretch_count": 4,
      "evidence_hints": ["lecture", "assessment", "efundi", "lms", "class"],
      "outputs": "Teaching activities as per TA"
    },
    // ... 100+ more tasks
  ],
  "by_month": {
    "2025-01": [/* tasks for January */],
    "2025-02": [/* tasks for February */],
    // ... all 12 months
  },
  "lead_lag": {
    "KPA1": { "lead": "Teaching delivery", "lag": "Assessment completion" },
    // ... other KPAs
  }
}
```

### API Endpoints

#### `/api/expectations` (GET)
- Returns full expectations structure
- Includes `by_month` breakdown
- Provides `tasks` array for Reports tab

#### `/api/expectations/check-month` (POST)
```json
Request:
{
  "staff_id": "20172672",
  "month": "2025-01"
}

Response:
{
  "complete": false,
  "evidence_count": 3,
  "required": 8,
  "message": "AI guidance...",
  "summary": "KPA1: 1/4 items\nKPA3: 2/3 items\nKPA4: 0/1 items",
  "missing": "Upload 5 more evidence items"
}
```

## Benefits

1. **Clear Monthly Tracking**: Staff can see exactly what's expected each month
2. **All 5 KPAs Covered**: No more missing KPAs - comprehensive coverage
3. **Progressive Disclosure**: Collapsible sections reduce cognitive load
4. **AI-Guided Progress**: VAMP provides specific guidance on what's missing
5. **Month Closing**: Clear signal when a month is complete, can move forward
6. **Evidence Mapping**: Each task knows what evidence types to look for
7. **Reports Ready**: Full table in Reports tab for PA generation

## Testing Recommendations

1. **Import a Task Agreement**
   - Verify all 5 KPAs appear
   - Check that tasks span all 12 months
   - Confirm milestone tasks appear in correct months

2. **Navigate Expectations Tab**
   - Click on each KPA header to expand/collapse
   - Verify monthly tasks show correctly
   - Check checkboxes work (visual feedback)

3. **Upload Evidence**
   - Upload files for current month
   - Verify they map to correct tasks
   - Check evidence count increases

4. **Check Month Status**
   - Select a month
   - Click "Check Month Status"
   - Verify AI provides relevant guidance
   - Check completion status updates

5. **Review Reports Tab**
   - Verify full table shows all tasks
   - Check all 8 columns display correctly
   - Confirm evidence hints are visible

## Future Enhancements

1. **Task Persistence**: Save checkbox states to database
2. **Progress Visualization**: Show completion percentage per KPA
3. **Auto-Advance**: Automatically move to next month when current complete
4. **Evidence Suggestions**: AI suggests specific files to upload
5. **Historical View**: See past months and their completion status
6. **Export Progress**: Download monthly progress reports
7. **Notification System**: Alert when approaching month end with incomplete tasks

## Files Modified

1. `/workspaces/Vamp-Offline/backend/expectation_engine.py` - Added `build_expectations_from_ta()`
2. `/workspaces/Vamp-Offline/index.html` - New collapsible view + moved table to Reports
3. `/workspaces/Vamp-Offline/app.js` - Rendering functions for new views
4. `/workspaces/Vamp-Offline/run_web.py` - Month-checking API endpoint
5. `/workspaces/Vamp-Offline/vamp_ai.py` - Enhanced AI prompt building
6. `/workspaces/Vamp-Offline/vamp.css` - New collapsible section styles

## Conclusion

The expectations system is now fully functional with:
- ✅ All 5 KPAs generating tasks
- ✅ Collapsible monthly view for easy tracking
- ✅ Comprehensive table in Reports for PA generation
- ✅ Month-closing logic with AI guidance
- ✅ Enhanced VAMP AI for contextual help

The system is ready for testing and can be further enhanced with the future improvements listed above.
