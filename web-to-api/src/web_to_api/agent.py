from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from .investigator import SiteInvestigator
from .models import ApiDesign
from .openapi import render_openapi
from .storage import ProjectNotFoundError, ProjectStore


@dataclass(slots=True)
class AgentDependencies:
    investigator: SiteInvestigator
    store: ProjectStore


INSTRUCTIONS = """
You help a developer turn a public website into a well-designed read-only API.

Start by asking for a public website URL if none has been supplied. Once you have one, call
investigate_site. Explain the useful data sources found, in this strict preference order:
published RSS/JSON feeds, JSON used by the site's backend, JSON embedded in HTML, static HTML,
then an async headless browser. Browser use during discovery does not change that ranking.

After investigation, ask what resources and fields the user wants. Keep asking focused questions
until resource names, parent/child relationships, identifiers, fields, pagination, and freshness
are clear. For example, matches may be a top-level resource while results and commentary are
nested below a match id. Do not invent fields the user has not requested.

Propose a concise design and mapping expressions supported by the investigation evidence. JSON
sources use JSONPath; HTML sources use CSS selectors. Confidence should be honest and mappings
must reference declared resource fields. When the user agrees, call save_api_design. This tool
requires explicit approval in the UI. This bootstrap writes design artifacts only; never claim
that a generated scraping API is already running.
""".strip()


def create_agent(model: str | Model) -> Agent[AgentDependencies, str]:
    agent: Agent[AgentDependencies, str] = Agent(
        model,
        deps_type=AgentDependencies,
        name="web_to_api_designer",
        instructions=INSTRUCTIONS,
        defer_model_check=True,
        retries=1,
    )

    @agent.tool
    async def investigate_site(
        ctx: RunContext[AgentDependencies],
        url: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Investigate a public website and return ranked extraction candidates.

        Args:
            url: Absolute public HTTP or HTTPS URL to investigate.
            force_refresh: Ignore the one-hour investigation cache when true.
        """
        try:
            report = await ctx.deps.investigator.investigate(url, force_refresh=force_refresh)
        except (ValueError, PermissionError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        preferred = report.preferred_candidate
        return {
            "ok": True,
            "project_id": report.project_id,
            "url": str(report.canonical_url),
            "title": report.title,
            "cached": report.cached,
            "preferred_strategy": preferred.strategy if preferred else None,
            "candidates": [candidate.model_dump(mode="json") for candidate in report.candidates],
            "warnings": report.warnings,
        }

    @agent.tool
    async def load_project(
        ctx: RunContext[AgentDependencies],
        project_id: str,
    ) -> dict[str, Any]:
        """Load an existing local project and its current design, if any."""
        try:
            investigation = await ctx.deps.store.load_investigation(project_id)
            design = await ctx.deps.store.load_design(project_id)
        except (ProjectNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "investigation": investigation.model_dump(mode="json"),
            "design": design.model_dump(mode="json") if design else None,
        }

    @agent.tool(requires_approval=True, sequential=True)
    async def save_api_design(
        ctx: RunContext[AgentDependencies],
        project_id: str,
        design: ApiDesign,
    ) -> dict[str, Any]:
        """Validate and save the agreed API design and extraction mapping.

        Args:
            project_id: Project id returned by investigate_site.
            design: The complete user-approved API and source mapping design.
        """
        try:
            document = render_openapi(design)
            await ctx.deps.store.save_design(project_id, design, document)
        except (ValueError, ProjectNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "project_id": project_id,
            "openapi_url": f"/api/projects/{project_id}/openapi.yaml",
        }

    return agent
