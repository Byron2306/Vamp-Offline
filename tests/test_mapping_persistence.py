from progress_store import ProgressStore
from mapper import ensure_tasks


def test_automatic_mappings_survive_task_rebuild(tmp_path):
    store = ProgressStore(tmp_path / "progress.db")
    expectations = {
        "tasks": [
            {
                "id": "task_001",
                "kpa_code": "KPA1",
                "title": "February teaching task",
                "cadence": "monthly",
                "months": [2],
                "minimum_count": 1,
                "stretch_count": 2,
                "evidence_hints": ["efundi", "assessment"],
            }
        ]
    }

    ensure_tasks(store, staff_id="20172672", year=2026, expectations=expectations)
    task_id = store.list_tasks_for_window(2026, [2])[0]["task_id"]

    store.insert_evidence(
        evidence_id="ev_test",
        sha1="abc",
        staff_id="20172672",
        year=2026,
        month_bucket="2026-02",
        kpa_code="KPA1",
        rating="",
        tier="",
        file_path="/tmp/evidence.txt",
        meta={"filename": "evidence.txt"},
    )
    store.upsert_mapping("ev_test", task_id, mapped_by="outlook_collect:targeted", confidence=0.9)

    ensure_tasks(store, staff_id="20172672", year=2026, expectations=expectations)

    mappings = store.list_mappings_for_evidence("ev_test")
    assert len(mappings) == 1
    assert mappings[0]["task_id"] == task_id
    assert mappings[0]["mapped_by"] == "outlook_collect:targeted"
