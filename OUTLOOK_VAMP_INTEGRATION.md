# Outlook Evidence Integration For VAMP

## Goal

Integrate Outlook Web collection into VAMP as a month-targeted evidence acquisition channel, not as a standalone mailbox triage subsystem.

The key rule is:

- VAMP decides what evidence is needed.
- Outlook collection only fetches candidate evidence for the selected month and selected expectation tasks.
- Collected items must flow through the existing VAMP evidence store and evidence-to-task mapping pipeline.

## Existing VAMP Control Points

VAMP already has the main pieces needed for this integration.

- Monthly expectations are generated from TA and stored in `backend/data/staff_expectations/expectations_{staff_id}_{year}.json`.
- Canonical per-month task rows are materialized in SQLite via `ensure_tasks(...)` in `mapper.py`.
- Evidence is stored in SQLite through `ProgressStore.insert_evidence(...)` in `progress_store.py`.
- Evidence is linked to tasks through `map_evidence_to_tasks(...)` in `mapper.py`.
- Month completion is decided by `/api/expectations/check-month` in `run_web.py` using task-level evidence counts.
- File uploads already use the canonical ingest path in `/api/scan/upload` in `run_web.py`.

This means Outlook should plug in beside `/api/scan/upload`, not around it.

## Correct Product Shape

The Outlook feature inside VAMP should be exposed as one of these flows:

- Collect Outlook evidence for selected month.
- Collect Outlook evidence for incomplete tasks in selected month.
- Collect Outlook evidence for a specific task.

It should not be:

- Scrape whole mailbox into VAMP.
- Store raw email dumps without task relevance.
- Run independent scoring or completion logic outside VAMP.

## Integration Architecture

### 1. Add an Outlook evidence collector service layer

Create a VAMP-side module, for example:

- `backend/outlook_evidence_collector.py`

Responsibilities:

- Accept a month window and optional task targets.
- Launch Playwright using saved session state.
- Search Outlook for task-relevant messages and attachments.
- Normalize results into candidate evidence records.
- Save attachments into a VAMP-controlled evidence acquisition folder.
- Return normalized candidates to the ingest pipeline.

This collector should not perform final VAMP scoring or completion decisions.

### 2. Add a VAMP API endpoint for targeted Outlook collection

Recommended endpoint:

- `POST /api/outlook/collect`

Suggested request payload:

```json
{
  "staff_id": "55291597",
  "year": 2025,
  "month": "2025-01",
  "mode": "incomplete_tasks",
  "task_ids": ["optional-specific-task-id"],
  "max_messages": 50,
  "include_body_only_candidates": true,
  "reuse_session": true
}
```

Suggested modes:

- `month_all_tasks`
- `incomplete_tasks`
- `specific_tasks`

The endpoint should:

- Load expectations for the given month.
- Ensure canonical tasks exist in SQLite.
- Derive search plans from those tasks.
- Call the Outlook collector.
- Push normalized candidates through VAMP evidence ingest.
- Return inserted evidence plus mapped-task summaries.

### 3. Derive search plans from monthly expectations

The collector should be driven by task rows, not just a free-text search.

For the selected month, VAMP should pull from:

- task `title`
- `kpa_code`
- `minimum_count`
- `evidence_hints`
- `outputs`
- any module codes, supervision names, committee labels, or milestone cues already present in the expectation payload

For each task, build a search plan like:

```json
{
  "task_id": "abc123",
  "month": "2025-01",
  "kpa_code": "KPA1",
  "title": "Teaching delivery evidence",
  "keywords": ["lecture", "assessment", "efundi", "lms", "class"],
  "date_from": "2025-01-01",
  "date_to": "2025-01-31",
  "min_required": 2
}
```

This must be month-bounded first, task-bounded second.

## Evidence Selection Policy

### Include as candidates

- Messages with attachments strongly matching task hints.
- Messages whose body is itself institutional evidence.
- Approval emails, confirmations, supervision feedback, moderation decisions, committee communications, acceptance notices, compliance notices, meeting records, and administrative confirmations.

### Exclude or down-rank

- Casual correspondence.
- Notifications without task relevance.
- Duplicate threads without new attachments or new decision content.
- Messages outside the selected month unless explicitly allowed as supporting spillover.

## Normalized Candidate Model

The collector should produce a VAMP-facing candidate structure like:

```json
{
  "source": "outlook_playwright",
  "source_message_id": "internet-or-derived-id",
  "staff_id": "55291597",
  "year": 2025,
  "month_bucket": "2025-01",
  "message_date": "2025-01-18T09:41:00Z",
  "subject": "Internal moderation approval for XYZ123",
  "sender": "example@nwu.ac.za",
  "recipients": "...",
  "body_text": "...",
  "attachment_paths": ["backend/data/evidence/outlook/2025-01/...pdf"],
  "task_candidates": ["task_id_1", "task_id_2"],
  "kpa_hint_code": "KPA1",
  "evidence_type_hint": "moderation",
  "search_reason": "matched task hints and month window",
  "meta": {
    "outlook_folder": "Inbox",
    "conversation_id": "...",
    "has_attachments": true
  }
}
```

## Ingest Path Inside VAMP

Once candidates are produced, they should reuse the same persistence pattern already used by `/api/scan/upload`.

Recommended flow per candidate:

1. Build an evidence text payload from subject, body, attachment names, and extracted attachment text if available.
2. Run `brain_score_evidence(...)` to get deterministic KPA, tier, rating, values, and policy hits.
3. Compute a stable `evidence_id` and SHA1.
4. Insert the record via `ProgressStore.insert_evidence(...)`.
5. Map it via `map_evidence_to_tasks(...)`.
6. If the request was task-targeted, also apply a high-confidence targeted mapping.

This gives Outlook evidence the same status as uploaded files.

## Attachment Handling

Outlook attachments should be treated as first-class evidence artifacts.

Recommended storage root:

- `backend/data/evidence/outlook/{staff_id}/{month_bucket}/{message_hash}/`

Recommended behavior:

- Save original filenames when safe.
- Preserve source message metadata in `meta_json`.
- If attachment text can be extracted, use it in the same way uploaded files are currently scored.
- If the email body itself is important evidence, store that as part of `meta_json` even when attachments exist.

## Month Window Rules

Default rule:

- Search only within the selected month.

Optional later refinement:

- Allow a configurable spillover window of a few days before and after the month for evidence that clearly belongs to the month’s task but was sent slightly outside the window.

Any spillover should still be assigned deliberately to the selected `month_bucket`, not implicitly.

## UI Changes In VAMP

On the Expectations tab, for the selected month, add:

- `Collect Outlook Evidence`
- `Collect For Incomplete Tasks`
- per-task `Find in Outlook`

Recommended UX:

- User chooses month first.
- VAMP displays month tasks and incomplete tasks.
- Outlook collection is launched with the current month and task context.
- Returned evidence is shown as staged or newly ingested items in the Evidence Log.

## Minimal Implementation Order

### Phase 1: Safe wiring

- Add `backend/outlook_evidence_collector.py`.
- Add `POST /api/outlook/collect`.
- Support month-targeted collection only.
- Insert collected evidence into SQLite using the existing pipeline.

### Phase 2: Task-targeted collection

- Build search plans from monthly task rows.
- Support `incomplete_tasks` mode.
- Add per-task targeted collection with stronger mappings.

### Phase 3: Better evidence quality

- Extract text from downloaded attachments.
- Improve de-duplication across repeated scans.
- Add confidence thresholds and candidate review.

## Concrete Build Recommendation

If implementing now, the first code slice should be:

1. New module: `backend/outlook_evidence_collector.py`
2. New endpoint in `run_web.py`: `POST /api/outlook/collect`
3. Reuse `ensure_tasks(...)`, `ProgressStore.insert_evidence(...)`, and `map_evidence_to_tasks(...)`
4. Add one UI button on the Expectations tab for month-targeted collection

That is the shortest path that respects VAMP’s actual architecture.

## Non-Goals

- Replacing the existing file upload evidence flow
- Treating all Outlook mail as evidence
- Building a second evidence database outside `progress_store.py`
- Letting Outlook logic decide month completion independently of VAMP
