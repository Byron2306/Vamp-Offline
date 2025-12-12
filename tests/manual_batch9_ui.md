# Batch 9 UI manual checks

These manual steps cover the UX guarantees requested in Batch 9:

1. **Window layout**
   - Launch the app via `python frontend/offline_app/offline_app_gui_llm_csv.py`.
   - Confirm the three vertical zones: top dashboard (fixed), middle evidence table, bottom split (detail + log).
   - Resize the window and drag the bottom splitter; the log should remain visible.

2. **KPA breakdown always visible**
   - Enrol/load a staff profile.
   - Import a Task/Performance Agreement.
   - Verify the KPA Hours & Weight table stays visible without tabs.

3. **Evidence table clarity**
   - Run a scan with sample files.
   - Ensure NEEDS_REVIEW rows show the amber background and remain visible.
   - Try filters for Status, KPA, and Evidence Type; the table updates without hiding problems.

4. **Drill-down and traceability**
   - Select a row; the Artefact Detail panel shows KPA, KPI labels, rating/tier, confidence, impact summary, and raw JSON.
   - Scroll through the Activity Log to see contract loaded, scan started, each artefact processed, and scan stopped.

5. **Exports**
   - After scanning, click **Export CSV** and confirm the file includes the table columns plus hidden fields (confidence, status, extract_status, evidence_type).

6. **Edge cases**
   - Attempt to start a scan with no contract: Start Scan should be disabled and a blocking message shown.
   - Remove KPI weights/hours and confirm the contract status shows ⚠️ Contract Incomplete and blocks scanning.
   - Stop a scan midway; existing rows remain and detail/log panels stay populated.

7. **Summary alignment**
   - Open the Summary panel and confirm the KPA summary and deterministic justification text remain copyable.
