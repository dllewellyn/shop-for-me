from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import logfire
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic_ai.models import Model

from .agent import AgentDependencies, create_agent
from .investigator import BrowserInvestigator, SiteInvestigator
from .settings import Settings, get_settings
from .storage import ProjectNotFoundError, ProjectStore


def create_app(
    settings: Settings | None = None,
    *,
    browser: BrowserInvestigator | None = None,
    model: str | Model | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="web-to-api",
        service_version="0.1.0",
    )
    logfire.instrument_pydantic_ai(
        include_content=settings.logfire_include_content,
    )

    store = ProjectStore(settings)
    investigator = SiteInvestigator(settings, store, browser=browser)
    deps = AgentDependencies(investigator=investigator, store=store)
    agent = create_agent(model or settings.pydantic_ai_model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.projects_dir.mkdir(parents=True, exist_ok=True)
        yield
        await investigator.close()
        await store.close()

    application = FastAPI(
        title="Web-to-API bootstrap service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.store = store
    application.state.investigator = investigator
    application.state.agent = agent
    logfire.instrument_fastapi(application, capture_headers=False)

    @application.get("/healthz", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/projects/{project_id}", tags=["projects"])
    async def project(project_id: str):
        try:
            return await store.summary(project_id)
        except (ProjectNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @application.get(
        "/api/projects/{project_id}/openapi.yaml",
        response_class=FileResponse,
        tags=["projects"],
    )
    async def openapi_artifact(project_id: str) -> FileResponse:
        try:
            path = store.project_dir(project_id) / "openapi.yaml"
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="OpenAPI artifact not found")
        return FileResponse(path, media_type="application/yaml", filename="openapi.yaml")

    # Register the catch-all UI last so FastAPI's routes and docs retain precedence.
    application.mount("/", agent.to_web(deps=deps), name="chat")
    return application


def run() -> None:
    uvicorn.run("web_to_api.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=True)
