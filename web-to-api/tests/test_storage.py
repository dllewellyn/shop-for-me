from pathlib import Path

import yaml

from web_to_api.models import InvestigationReport
from web_to_api.openapi import render_openapi
from web_to_api.settings import Settings
from web_to_api.storage import ProjectStore

from .test_openapi import sample_design


async def test_store_writes_project_artifacts_atomically(tmp_path: Path) -> None:
    store = ProjectStore(Settings(data_dir=tmp_path))
    report = InvestigationReport(
        project_id="example-123",
        requested_url="https://example.com",
        canonical_url="https://example.com",
    )
    design = sample_design()
    try:
        await store.save_investigation(report)
        await store.save_design(report.project_id, design, render_openapi(design))
        summary = await store.summary(report.project_id)
    finally:
        await store.close()

    assert summary.design_saved is True
    artifact = tmp_path / "projects" / report.project_id / "openapi.yaml"
    assert yaml.safe_load(artifact.read_text())["openapi"] == "3.1.0"
