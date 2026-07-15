from __future__ import annotations

import re
from typing import Any

from openapi_spec_validator import validate

from .models import ApiDesign, ApiField


def _field_schema(field: ApiField) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": field.type, "description": field.description}
    if field.format:
        schema["format"] = field.format
    if field.type == "array":
        schema["items"] = {}
    return schema


def render_openapi(design: ApiDesign) -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    paths: dict[str, Any] = {}
    for resource in design.resources:
        required = [field.name for field in resource.fields if field.required]
        schema: dict[str, Any] = {
            "type": "object",
            "description": resource.description,
            "properties": {field.name: _field_schema(field) for field in resource.fields},
        }
        if required:
            schema["required"] = required
        schemas[resource.name] = schema

        mappings = [
            mapping.model_dump(mode="json")
            for mapping in design.mappings
            if mapping.resource == resource.name
        ]
        path_parameters = [
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
            for name in re.findall(r"{([^}]+)}", resource.path)
        ]
        operation: dict[str, Any] = {
            "operationId": f"list_{resource.name.lower()}",
            "summary": resource.description,
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": f"#/components/schemas/{resource.name}"},
                            }
                        }
                    },
                },
                "502": {"description": "The upstream website could not be read"},
            },
            "x-source-mapping": mappings,
        }
        if mappings:
            best = min(mappings, key=lambda item: _strategy_rank(item["strategy"]))
            operation["x-source-strategy"] = best["strategy"]
            operation["x-source-url"] = best["source_url"]
            operation["x-mapping-confidence"] = min(item["confidence"] for item in mappings)
        if path_parameters:
            operation["parameters"] = path_parameters
        paths[resource.path] = {"get": operation}

    document = {
        "openapi": "3.1.0",
        "info": {
            "title": design.title,
            "description": design.description,
            "version": design.version,
            "x-data-freshness": design.freshness,
        },
        "paths": paths,
        "components": {"schemas": schemas},
    }
    validate(document)
    return document


def _strategy_rank(strategy: str) -> int:
    return {
        "rss": 0,
        "json_feed": 0,
        "backend_json": 1,
        "embedded_json": 2,
        "static_html": 3,
        "headless_browser": 4,
    }[strategy]
