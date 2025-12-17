# Quick Start Guide - New Expectations System

## What Changed?

### Before
- ❌ Only 4 tasks from 2 KPAs
- ❌ Flat table view (confusing)
- ❌ No monthly breakdown
- ❌ No way to track month completion

### After
- ✅ 100+ tasks across all 5 KPAs
- ✅ Collapsible monthly view (per KPA)
- ✅ Month-by-month tracking with checkboxes
- ✅ AI checks if monthly expectations are met
- ✅ Month "closes" when complete, move to next

## How to Use

### Step 1: Enrol & Import TA
```
1. Go to "Profile" tab
2. Enter staff ID and details
3. Click "Enrol Staff"
4. Upload Task Agreement Excel file
5. Wait for "Expectations ✓" in top status bar
```

### Step 2: View Monthly Expectations
```
1. Go to "Expectations" tab
2. See 5 collapsible KPA sections:
   - KPA1: Teaching and Learning
   - KPA2: Occupational Health & Safety
   - KPA3: Research, Innovation & Creative Outputs
   - KPA4: Academic Leadership & Administration
   - KPA5: Social Responsiveness
   
3. Click any KPA header to expand/collapse
4. See tasks organized by month within each KPA
5. Each task shows:
   - Description
   - Cadence (monthly, quarterly, milestone)
   - Min-Stretch targets (e.g., 2-4 items)
   - 🤖 Ask AI button
```

### Step 3: Upload Evidence for Current Month
```
1. Select current month: [January 2025 ▼]
2. Go to "Scan" tab
3. Upload evidence files
4. AI classifies them by KPA
5. Files automatically map to monthly tasks
```

### Step 4: Check Month Status
```
1. Go back to "Expectations" tab
2. Ensure correct month is selected
3. Click "Check Month Status" button
4. See status pill change:
   - "Complete ✓" (green) = All expectations met
   - "Incomplete ⚠️" (red) = Still need evidence
   
5. Read AI Month Review box:
   - Shows what's missing
   - Provides specific guidance
   - Suggests next steps
```

### Step 5: Month Closes → Move to Next
```
When "Complete ✓":
1. All evidence for month stored
2. Month is locked (conceptually)
3. Select next month from dropdown
4. Repeat process
```

### Step 6: Generate PA (Reports Tab)
```
1. Go to "Reports" tab
2. Review "Complete Expectations Overview" table
   - Shows ALL tasks across all months
   - Verify all 5 KPAs included
   - Check outputs and evidence hints
   
3. Click "Generate Final PA"
4. Download your Performance Agreement
```

## UI Elements Guide

### Expectations Tab
```
┌─────────────────────────────────────────────┐
│ Monthly Expectations                   [⚙]  │
│ Track progress month-by-month          [🔄] │
├─────────────────────────────────────────────┤
│ Current Month: [Jan 2025 ▼]  [Check Status] │
│                                 [Incomplete⚠️]│
├─────────────────────────────────────────────┤
│ ▼ KPA1 — Teaching and Learning              │
│   ├─ January 2025                            │
│   │  ☐ Teaching delivery [monthly, 2-4] 🤖  │
│   │  ☐ ...                                   │
│   └─ February 2025                           │
│      ☐ ...                                   │
│                                               │
│ ► KPA2 — Occupational Health & Safety       │
│ ► KPA3 — Research, Innovation & Creative... │
│ ► KPA4 — Academic Leadership & Admin        │
│ ► KPA5 — Social Responsiveness              │
├─────────────────────────────────────────────┤
│ AI Month Review                              │
│ ⚠️ Month Incomplete                          │
│ You have uploaded 3 of 8 required items...  │
│ Missing: KPA1: 1/4, KPA3: 2/3, KPA4: 0/1   │
└─────────────────────────────────────────────┘
```

### Reports Tab
```
┌─────────────────────────────────────────────┐
│ Reports & PA Generation          [Generate] │
├─────────────────────────────────────────────┤
│ Complete Expectations Overview               │
│ ┌──────┬────────┬───────┬─────────┬────┐   │
│ │ KPA  │ Task   │ Month │ Cadence │... │   │
│ ├──────┼────────┼───────┼─────────┼────┤   │
│ │ KPA1 │Teaching│ 1     │ monthly │... │   │
│ │ KPA1 │Teaching│ 2     │ monthly │... │   │
│ │ KPA1 │Marks   │ 6     │milestone│... │   │
│ │ KPA2 │OHS     │ 2     │quarterly│... │   │
│ │ ...  │...     │ ...   │ ...     │... │   │
│ └──────┴────────┴───────┴─────────┴────┘   │
│                                               │
│ PA Generation Output                         │
│ [Click Generate to create PA document]       │
└─────────────────────────────────────────────┘
```

## Task Cadences Explained

- **monthly**: Required every month (e.g., teaching delivery)
- **quarterly**: Required every 3 months (e.g., OHS compliance)
- **milestone**: One-time at specific month (e.g., semester marks submission)

## Minimum vs Stretch Targets

Example: `2-4 items`
- **2** = Minimum required (must have at least this many)
- **4** = Stretch target (aim for excellence)

If you upload fewer than minimum, month shows "Incomplete ⚠️"

## AI Guidance Features

### Task-Level Help
Click 🤖 button next to any task:
- Get specific guidance for that task
- See evidence type suggestions
- Ask questions about requirements

### Month-Level Review
Click "Check Month Status":
- AI analyzes all evidence for the month
- Identifies gaps by KPA
- Provides actionable next steps
- Celebrates when complete

## Tips for Success

1. **Start of Month**: Review expectations for that month
2. **As You Work**: Upload evidence immediately (don't wait)
3. **Mid-Month**: Check status to see progress
4. **End of Month**: Ensure "Complete ✓" before moving on
5. **Use AI**: Don't hesitate to click 🤖 for guidance

## Troubleshooting

### "No expectations loaded"
- Ensure you've imported a Task Agreement
- Check "Expectations ✓" shows in top status bar
- Click "Rebuild expectations" if needed

### "Only 4 tasks showing"
- This was the old bug - now fixed!
- Should see 100+ tasks across all months
- If not, reimport your TA

### "Month stays incomplete"
- Check which KPAs need evidence (see AI review)
- Verify evidence files are uploading correctly
- Ensure evidence month matches selected month

### "KPA sections won't expand"
- Click directly on the KPA header
- Look for arrow (▼/►) that indicates expand/collapse
- Try refreshing the page

## Advanced: Checkbox States

Currently checkboxes are visual only - they help you track mentally.

**Future Enhancement**: Checkboxes will persist to database so:
- Your progress saves across sessions
- System knows exactly which tasks are done
- Can generate "tasks remaining" reports

## Questions?

Click the 🤖 "Ask VAMP" button in any section or use the VAMP assistant in the bottom-right to ask questions about:
- Specific tasks
- What evidence to upload
- How to interpret requirements
- Month completion criteria

---

**Remember**: The system now generates expectations for all 5 KPAs automatically. Focus on one month at a time, and use AI guidance to stay on track!
