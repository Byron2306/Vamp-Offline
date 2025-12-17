# Expectations System Architecture

## System Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER IMPORTS TASK AGREEMENT                  │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│           backend/expectation_engine.py                              │
│           parse_task_agreement(excel_path)                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  • Reads TA Excel file                                        │   │
│  │  • Extracts hours per SECTION (maps to KPA)                  │   │
│  │  • Identifies teaching, research, leadership activities      │   │
│  │  • Detects practice windows, modules                         │   │
│  │  • Returns: kpa_summary, teaching[], research[], etc.        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                 │                                                     │
│                 ▼                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  build_expectations_from_ta(staff_id, year, ta_summary)      │   │
│  │  ┌────────────────────────────────────────────────────────┐  │   │
│  │  │  FOR EACH KPA:                                          │  │   │
│  │  │  • KPA1 (Teaching): 12 monthly + 2 milestone tasks      │  │   │
│  │  │  • KPA2 (OHS): 4 quarterly tasks                        │  │   │
│  │  │  • KPA3 (Research): 12 monthly + 2 milestone tasks      │  │   │
│  │  │  • KPA4 (Leadership): 12 monthly tasks                  │  │   │
│  │  │  • KPA5 (Social): 4 quarterly tasks                     │  │   │
│  │  │                                                           │  │   │
│  │  │  EACH TASK INCLUDES:                                     │  │   │
│  │  │  • id, kpa_code, kpa_name                               │  │   │
│  │  │  • title, cadence (monthly/quarterly/milestone)         │  │   │
│  │  │  • months[] (which months apply)                        │  │   │
│  │  │  • minimum_count, stretch_count                         │  │   │
│  │  │  • evidence_hints[] (keywords to match evidence)        │  │   │
│  │  │  • outputs (from TA)                                    │  │   │
│  │  └────────────────────────────────────────────────────────┘  │   │
│  │                 │                                              │   │
│  │                 ▼                                              │   │
│  │  Returns: {tasks: [100+ tasks], by_month: {...}, ...}        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA STORED IN BACKEND                            │
│  backend/data/staff_expectations/expectations_{id}_{year}.json      │
│  {                                                                   │
│    "tasks": [ {...100+ tasks...} ],                                 │
│    "by_month": {                                                     │
│      "2025-01": [tasks for Jan],                                    │
│      "2025-02": [tasks for Feb],                                    │
│      ...                                                             │
│    },                                                                │
│    "kpa_summary": { KPA1: {...}, KPA2: {...}, ... },               │
│    "lead_lag": { KPA1: {lead: ..., lag: ...}, ... }                │
│  }                                                                   │
└────────────────┬────────────────────────────────────────────────────┘
                 │
    ┌────────────┴──────────────┐
    │                           │
    ▼                           ▼
┌─────────────────┐   ┌──────────────────────┐
│ EXPECTATIONS    │   │ REPORTS TAB          │
│ TAB             │   │                      │
│ (Monthly View)  │   │ (Full Table)         │
└─────────────────┘   └──────────────────────┘
```

## Component Interactions

```
┌──────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (index.html)                       │
├──────────────────┬───────────────────────┬──────────────────────────┤
│ EXPECTATIONS TAB │ SCAN TAB              │ REPORTS TAB              │
│                  │                        │                          │
│ renderMonthly    │ uploadEvidence()       │ renderPATable()          │
│ Expectations()   │        │               │        ▲                 │
│        │         │        ▼               │        │                 │
│        │         │ ┌─────────────────┐   │        │                 │
│        │         │ │Evidence uploaded│   │        │                 │
│        │         │ │and classified   │   │        │                 │
│        │         │ └────────┬────────┘   │        │                 │
│        │         │          │             │        │                 │
│        │         │          ▼             │        │                 │
│        │         │ Stored in evidence.csv│        │                 │
│        ▼         │          │             │        │                 │
│ checkMonthStatus()◄─────────┘             │        │                 │
│        │                                   │        │                 │
│        └───────────────────────────────────┴────────┘                 │
└────────┬─────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      BACKEND API (run_web.py)                         │
├──────────────────────────────────────────────────────────────────────┤
│  GET /api/expectations?staff_id=X&year=Y                             │
│  └─→ Returns full expectations JSON                                  │
│      • tasks[] (all 100+ tasks)                                      │
│      • by_month{} (organized by month)                               │
│      • kpa_summary{} (hours, weights)                                │
│                                                                       │
│  POST /api/expectations/check-month                                  │
│  Body: { staff_id, month }                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 1. Load expectations for month from JSON                       │  │
│  │ 2. Load evidence from evidence_{id}_{year}.csv                 │  │
│  │ 3. Count evidence items per KPA for that month                 │  │
│  │ 4. Calculate: evidence_count >= sum(minimum_count)?            │  │
│  │ 5. Build AI prompt with context                                │  │
│  │ 6. Call query_ollama() for guidance                            │  │
│  │ 7. Return: { complete, evidence_count, required, message, ... }│  │
│  └────────────────────────────────────────────────────────────────┘  │
└────────────────┬─────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        VAMP AI (vamp_ai.py)                           │
│  query_ollama(prompt, context)                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Enhanced context includes:                                     │  │
│  │  • staff_id, cycle_year                                         │  │
│  │  • month being analyzed                                         │  │
│  │  • tasks count for period                                       │  │
│  │  • evidence_count uploaded                                      │  │
│  │  • required minimum                                             │  │
│  │                                                                  │  │
│  │  AI Provides:                                                   │  │
│  │  • Specific KPA guidance                                        │  │
│  │  • Concrete evidence suggestions                               │  │
│  │  • Progress celebration (if complete)                          │  │
│  │  • Catch-up advice (if behind)                                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

## Data Flow: Task Generation

```
TA EXCEL FILE
    │
    ▼
┌────────────────────────────────────────┐
│ SECTION 1: Research (200 hrs)         │ → KPA3 (Research)
│ SECTION 2: Teaching (1340 hrs)        │ → KPA1 (Teaching)
│ SECTION 3: Social Resp (80 hrs)       │ → KPA5 (Social)
│ SECTION 4: Leadership (300 hrs)       │ → KPA4 (Leadership)
│ SECTION 5: OHS (8 hrs)                │ → KPA2 (OHS)
└────────────────────────────────────────┘
    │
    ▼ parse_task_agreement()
    │
┌────────────────────────────────────────┐
│ kpa_summary = {                        │
│   KPA1: {hours: 1340, weight: 77.5%}  │
│   KPA2: {hours: 8, weight: 0.5%}      │
│   KPA3: {hours: 200, weight: 11.6%}   │
│   KPA4: {hours: 300, weight: 17.4%}   │
│   KPA5: {hours: 80, weight: 4.6%}     │
│ }                                      │
└────────────────────────────────────────┘
    │
    ▼ build_expectations_from_ta()
    │
┌────────────────────────────────────────┐
│ FOR KPA1 (Teaching, 1340 hrs):        │
│   Generate 12 monthly tasks            │
│   + 2 milestone tasks (Jun, Nov)       │
│   = 14 tasks                           │
│                                        │
│ FOR KPA2 (OHS, 8 hrs):                │
│   Generate 4 quarterly tasks           │
│   (Feb, May, Aug, Nov)                 │
│   = 4 tasks                            │
│                                        │
│ FOR KPA3 (Research, 200 hrs):         │
│   Generate 12 monthly tasks            │
│   + 2 milestone tasks (Jun, Nov)       │
│   = 14 tasks                           │
│                                        │
│ FOR KPA4 (Leadership, 300 hrs):       │
│   Generate 12 monthly tasks            │
│   = 12 tasks                           │
│                                        │
│ FOR KPA5 (Social, 80 hrs):            │
│   Generate 4 quarterly tasks           │
│   (Mar, Jun, Sep, Dec)                 │
│   = 4 tasks                            │
│                                        │
│ TOTAL: 48 tasks (if all KPAs active)  │
└────────────────────────────────────────┘
```

## Monthly Progress Tracking

```
MONTH: January 2025
├─ KPA1: Teaching (4 tasks expected)
│  ├─ Task 1: Teaching delivery [monthly, 2-4 items]
│  │  └─ Evidence uploaded: 3 items ✓ (meets minimum 2)
│  ├─ Task 2: eFundi updates [monthly, 1-2 items]
│  │  └─ Evidence uploaded: 1 item ✓ (meets minimum 1)
│  ├─ Task 3: Assessment prep [monthly, 1-3 items]
│  │  └─ Evidence uploaded: 0 items ✗ (needs minimum 1)
│  └─ Task 4: Supervision meetings [monthly, 2-3 items]
│     └─ Evidence uploaded: 2 items ✓ (meets minimum 2)
│
├─ KPA3: Research (1 task expected)
│  └─ Task 5: Research progress [monthly, 1-3 items]
│     └─ Evidence uploaded: 0 items ✗ (needs minimum 1)
│
├─ KPA4: Leadership (1 task expected)
│  └─ Task 6: Committee work [monthly, 1-2 items]
│     └─ Evidence uploaded: 1 item ✓ (meets minimum 1)
│
└─ MONTH STATUS: Incomplete ⚠️
   Need: 2 more evidence items (KPA1 Task 3, KPA3 Task 5)
```

## UI State Management

```javascript
// Global State
currentExpectations = []; // All tasks loaded from API
currentProfile = {...};   // Staff profile
currentScanResults = []; // Evidence from current scan

// On Load
loadExpectations() 
  → fetch('/api/expectations')
  → currentExpectations = data.tasks
  → renderMonthlyExpectations(data.by_month, data.tasks)
  → renderPAExpectationsTable(data.tasks)

// Collapsible Rendering
renderMonthlyExpectations(byMonth, allTasks)
  → Group tasks by KPA
  → For each KPA:
      → Create collapsible section
      → For each month in KPA:
          → Render month div
          → For each task in month:
              → Render checkbox + label + AI button
              → Wire up expand/collapse click handler

// Month Status Check
checkMonthStatus()
  → Read selected month from dropdown
  → POST to /api/expectations/check-month
  → Update statusPill (Complete/Incomplete)
  → Update reviewBox with AI guidance
  → Show detailed missing items
```

## File Structure

```
/workspaces/Vamp-Offline/
├── backend/
│   ├── expectation_engine.py          ← Core: parse TA + build expectations
│   ├── data/
│   │   ├── staff_expectations/
│   │   │   └── expectations_{id}_{year}.json  ← Generated tasks
│   │   ├── evidence/
│   │   │   └── evidence_{id}_{year}.csv       ← Evidence log
│   │   └── contracts/
│   │       └── contract_{id}_{year}.json      ← TA summary
│   └── vamp_agent.py                  ← AI query helper
│
├── frontend/
│   ├── index.html                     ← UI structure (3 tabs updated)
│   ├── app.js                         ← Rendering + API calls
│   └── vamp.css                       ← Collapsible styles
│
├── run_web.py                         ← Flask API server
│                                         • /api/expectations (GET)
│                                         • /api/expectations/check-month (POST)
│
└── EXPECTATIONS_*.md                  ← Documentation (this file!)
```

## Key Design Decisions

### Why Collapsible by KPA?
- **Progressive Disclosure**: Staff don't need to see all 100+ tasks at once
- **Mental Model**: KPAs are the primary organizational unit at NWU
- **Focus**: Can focus on one KPA at a time

### Why Monthly Breakdown?
- **Natural Rhythm**: Academics work in monthly cycles
- **Evidence Upload**: Evidence is dated and belongs to specific months
- **Progress Tracking**: Clear checkpoints ("Is January done?")

### Why Minimum + Stretch?
- **Clear Expectations**: Must meet minimum, encouraged to exceed
- **Flexibility**: Different KPAs have different activity levels
- **Motivation**: Stretch goals provide aspiration

### Why AI Month Review?
- **Context-Aware**: AI knows what's expected vs what's uploaded
- **Actionable**: Provides specific next steps, not generic advice
- **Motivational**: Celebrates success, encourages catch-up

## Performance Considerations

### Task Generation
- Generates 40-60 tasks per staff member (varies by TA)
- One-time operation on TA import
- Cached in JSON file
- Fast lookup by month via `by_month` structure

### Evidence Mapping
- CSV format for fast append-only logging
- Evidence auto-maps to tasks via hints (keywords)
- Month filtering via `month_bucket` column
- O(n) scan through evidence (acceptable for typical volumes)

### UI Rendering
- Collapsible sections prevent rendering all 100+ tasks at once
- Only expanded KPAs show their month lists
- Lazy rendering possible (future enhancement)

## Security Notes

- All file paths use `secure_filename()` sanitization
- Staff IDs validated before file operations
- No user-provided data in system commands
- Evidence files stored with hash-based names
- Month parameter validated (YYYY-MM format)

---

This architecture ensures:
1. **Scalability**: Handles 100+ tasks per staff effortlessly
2. **Maintainability**: Clear separation of concerns
3. **Usability**: Progressive disclosure reduces cognitive load
4. **Intelligence**: AI provides contextual guidance
5. **Accuracy**: All 5 KPAs covered automatically
