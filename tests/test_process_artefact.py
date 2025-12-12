import csv
from types import SimpleNamespace

from backend.vamp_master import generate_run_id
from frontend.offline_app.offline_app_gui_llm_csv import CSV_COLUMNS, process_artefact


def test_broken_file_generates_needs_review_row(tmp_path):
    broken_file = tmp_path / "broken.txt"
    broken_file.write_text("placeholder")

    messages = []

    def logger(msg: str) -> None:
        messages.append(msg)

    run_id = generate_run_id()
    profile = SimpleNamespace(staff_id="12345", cycle_year=2024)

    row, ctx, impact = process_artefact(
        path=broken_file,
        month_bucket="2024-01",
        run_id=run_id,
        profile=profile,
        contract_context="",
        kpa_hint="",
        use_ollama=False,
        prefer_llm_rating=False,
        log=logger,
        extract_fn=lambda p: (_ for _ in ()).throw(RuntimeError("kaboom")),
        contextual_fn=None,
        brain_fn=None,
    )

    assert row["filename"] == broken_file.name
    assert row["run_id"] == run_id
    assert row["extract_status"] == "failed"
    assert row["status"] == "NEEDS_REVIEW"

    output_csv = tmp_path / "results.csv"
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(row)

    with output_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["status"] == "NEEDS_REVIEW"
