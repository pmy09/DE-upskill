"""Fast orchestration tests using mocked pipeline stages."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import pipeline


def test_run_validation_uses_supplied_employees(valid_employees, monkeypatch):
    expected = pd.DataFrame({"status": ["PASS"]})
    observed = {}

    def fake_checks(frame, *, enforce_gate):
        observed["frame"] = frame
        observed["enforce_gate"] = enforce_gate
        return expected

    monkeypatch.setattr(pipeline, "run_quality_checks", fake_checks)

    result = pipeline.run_validation(valid_employees, enforce_gate=False)

    assert result is expected
    assert observed == {"frame": valid_employees, "enforce_gate": False}


def test_run_pipeline_executes_stages_in_order(valid_employees, tmp_path, monkeypatch):
    calls = []
    ingested = {"source": pd.DataFrame({"raw": [1]})}
    cleaned = {"source": pd.DataFrame({"clean": [1]})}
    ghosts = pd.DataFrame(columns=["payroll_employee_id"])
    probable = pd.DataFrame(columns=["record_1_id"])
    quality = pd.DataFrame({"status": ["PASS"], "check": ["x"]})
    eda_path = tmp_path / "eda.png"
    export_paths = {
        "golden_dataset": tmp_path / "golden",
        "schema_doc": tmp_path / "schema.md",
        "ghost_employees": tmp_path / "ghosts.csv",
        "probable_matches": tmp_path / "matches.csv",
    }

    monkeypatch.setattr(
        pipeline,
        "run_ingestion",
        lambda: calls.append("ingest") or ingested,
    )
    monkeypatch.setattr(
        pipeline,
        "run_cleaning",
        lambda frames: calls.append(("clean", frames)) or cleaned,
    )
    monkeypatch.setattr(
        pipeline,
        "run_deduplication",
        lambda frames: calls.append(("dedup", frames))
        or {
            "employees": valid_employees,
            "ghost_employees": ghosts,
            "probable_matches": probable,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "run_validation",
        lambda employees, enforce_gate: calls.append(
            ("validate", employees, enforce_gate)
        )
        or quality,
    )
    monkeypatch.setattr(
        pipeline,
        "run_eda",
        lambda employees, report: calls.append(("eda", employees, report))
        or eda_path,
    )
    monkeypatch.setattr(
        pipeline,
        "run_export",
        lambda employees, ghost_frame, matches: calls.append(
            ("export", employees, ghost_frame, matches)
        )
        or export_paths,
    )

    result = pipeline.run_pipeline()

    assert calls[0] == "ingest"
    assert [call[0] for call in calls[1:]] == [
        "clean",
        "dedup",
        "validate",
        "eda",
        "export",
    ]
    assert isinstance(result["employees"], pd.DataFrame)
    assert isinstance(result["ghost_employees"], pd.DataFrame)
    assert result["golden_dataset"] == export_paths["golden_dataset"]
    assert result["export_paths"] == export_paths


def test_run_export_reuses_all_supplied_frames(
    valid_employees, tmp_path, monkeypatch
):
    ghosts = pd.DataFrame({"payroll_employee_id": []})
    probable = pd.DataFrame({"record_1_id": []})
    expected = {"golden_dataset": Path(tmp_path / "golden")}
    observed = {}

    def fake_export(employees, ghost_frame, matches):
        observed["args"] = (employees, ghost_frame, matches)
        return expected

    monkeypatch.setattr(pipeline, "export_final_artifacts", fake_export)
    monkeypatch.setattr(
        pipeline,
        "run_deduplication",
        lambda: (_ for _ in ()).throw(AssertionError("should not rerun dedup")),
    )

    result = pipeline.run_export(valid_employees, ghosts, probable)

    assert result is expected
    assert observed["args"] == (valid_employees, ghosts, probable)
