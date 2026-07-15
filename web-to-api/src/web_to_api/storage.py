from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio
import yaml
from diskcache import Cache
from pydantic import BaseModel

from .models import ApiDesign, InvestigationReport, ProjectSummary
from .settings import Settings


class ProjectNotFoundError(FileNotFoundError):
    pass


class ProjectStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache = Cache(str(settings.cache_dir))

    async def close(self) -> None:
        await anyio.to_thread.run_sync(self._cache.close)

    async def cache_get(self, key: str) -> InvestigationReport | None:
        raw = await anyio.to_thread.run_sync(self._cache.get, key)
        return InvestigationReport.model_validate_json(raw) if raw else None

    async def cache_set(self, key: str, report: InvestigationReport) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._cache.set(
                key,
                report.model_dump_json(),
                expire=self.settings.cache_ttl_seconds,
            )
        )

    def project_dir(self, project_id: str) -> Path:
        if not project_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in project_id
        ):
            raise ValueError("Invalid project id")
        return self.settings.projects_dir / project_id

    async def save_investigation(self, report: InvestigationReport) -> None:
        await self._write_model(self.project_dir(report.project_id) / "investigation.json", report)

    async def load_investigation(self, project_id: str) -> InvestigationReport:
        path = self.project_dir(project_id) / "investigation.json"
        if not path.exists():
            raise ProjectNotFoundError(project_id)
        return InvestigationReport.model_validate_json(await anyio.Path(path).read_text())

    async def save_design(
        self, project_id: str, design: ApiDesign, openapi: dict[str, Any]
    ) -> None:
        directory = self.project_dir(project_id)
        if not (directory / "investigation.json").exists():
            raise ProjectNotFoundError(project_id)
        await self._write_model(directory / "design.json", design)
        await self._atomic_write(
            directory / "openapi.yaml",
            yaml.safe_dump(openapi, sort_keys=False, allow_unicode=True),
        )

    async def load_design(self, project_id: str) -> ApiDesign | None:
        path = self.project_dir(project_id) / "design.json"
        return (
            ApiDesign.model_validate_json(await anyio.Path(path).read_text())
            if path.exists()
            else None
        )

    async def summary(self, project_id: str) -> ProjectSummary:
        investigation = await self.load_investigation(project_id)
        directory = self.project_dir(project_id)
        preferred = investigation.preferred_candidate
        design_saved = (directory / "design.json").exists()
        artifacts = {"investigation": f"/api/projects/{project_id}"}
        if design_saved:
            artifacts["openapi"] = f"/api/projects/{project_id}/openapi.yaml"
        return ProjectSummary(
            project_id=project_id,
            url=investigation.canonical_url,
            preferred_strategy=preferred.strategy if preferred else None,
            investigated_at=investigation.investigated_at,
            design_saved=design_saved,
            artifacts=artifacts,
        )

    async def _write_model(self, path: Path, model: BaseModel) -> None:
        await self._atomic_write(path, model.model_dump_json(indent=2) + "\n")

    async def _atomic_write(self, path: Path, content: str) -> None:
        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)

        await anyio.to_thread.run_sync(write)
