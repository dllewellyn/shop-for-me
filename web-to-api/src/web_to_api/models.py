from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class SourceStrategy(StrEnum):
    RSS = "rss"
    JSON_FEED = "json_feed"
    BACKEND_JSON = "backend_json"
    EMBEDDED_JSON = "embedded_json"
    STATIC_HTML = "static_html"
    HEADLESS_BROWSER = "headless_browser"


class SourceRank(IntEnum):
    RSS = 0
    JSON_FEED = 0
    BACKEND_JSON = 1
    EMBEDDED_JSON = 2
    STATIC_HTML = 3
    HEADLESS_BROWSER = 4


SOURCE_RANK: dict[SourceStrategy, int] = {
    SourceStrategy.RSS: SourceRank.RSS,
    SourceStrategy.JSON_FEED: SourceRank.JSON_FEED,
    SourceStrategy.BACKEND_JSON: SourceRank.BACKEND_JSON,
    SourceStrategy.EMBEDDED_JSON: SourceRank.EMBEDDED_JSON,
    SourceStrategy.STATIC_HTML: SourceRank.STATIC_HTML,
    SourceStrategy.HEADLESS_BROWSER: SourceRank.HEADLESS_BROWSER,
}


class SourceCandidate(BaseModel):
    strategy: SourceStrategy
    url: str
    content_type: str | None = None
    evidence: str
    sample_keys: list[str] = Field(default_factory=list)
    selectors: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class InvestigationReport(BaseModel):
    project_id: str
    requested_url: HttpUrl
    canonical_url: HttpUrl
    title: str | None = None
    investigated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cached: bool = False
    candidates: list[SourceCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def preferred_candidate(self) -> SourceCandidate | None:
        if not self.candidates:
            return None
        return min(
            self.candidates,
            key=lambda candidate: (SOURCE_RANK[candidate.strategy], -candidate.confidence),
        )


class ApiField(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: str = Field(
        description="JSON Schema primitive: string, integer, number, boolean, object, array"
    )
    description: str
    required: bool = True
    format: str | None = None


class ApiResource(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    description: str
    path: str = Field(pattern=r"^/")
    fields: list[ApiField] = Field(min_length=1)
    parent_resource: str | None = None
    pagination: bool = False


class FieldMapping(BaseModel):
    resource: str
    field: str
    strategy: SourceStrategy
    source_url: str
    expression: str = Field(description="JSONPath for JSON or CSS selector for HTML")
    attribute: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: str


class ApiDesign(BaseModel):
    title: str
    description: str
    version: str = "0.1.0"
    resources: list[ApiResource] = Field(min_length=1)
    mappings: list[FieldMapping] = Field(default_factory=list)
    freshness: str = "on demand"

    @model_validator(mode="after")
    def mappings_reference_known_fields(self) -> ApiDesign:
        fields = {
            (resource.name, field.name) for resource in self.resources for field in resource.fields
        }
        unknown = {(mapping.resource, mapping.field) for mapping in self.mappings} - fields
        if unknown:
            raise ValueError(f"Mappings reference unknown fields: {sorted(unknown)!r}")
        return self


class ProjectSummary(BaseModel):
    project_id: str
    url: HttpUrl
    preferred_strategy: SourceStrategy | None = None
    investigated_at: datetime
    design_saved: bool
    artifacts: dict[str, str] = Field(default_factory=dict)


class ProjectArtifact(BaseModel):
    project_id: str
    investigation: InvestigationReport
    design: ApiDesign | None = None
    openapi: dict[str, Any] | None = None
