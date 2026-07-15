from openapi_spec_validator import validate

from web_to_api.models import ApiDesign, ApiField, ApiResource, FieldMapping, SourceStrategy
from web_to_api.openapi import render_openapi


def sample_design() -> ApiDesign:
    return ApiDesign(
        title="Match API",
        description="Upcoming matches and commentary",
        resources=[
            ApiResource(
                name="Match",
                description="Upcoming matches",
                path="/matches",
                pagination=True,
                fields=[
                    ApiField(name="id", type="string", description="Match id"),
                    ApiField(
                        name="starts_at", type="string", format="date-time", description="Kickoff"
                    ),
                ],
            ),
            ApiResource(
                name="Commentary",
                description="Commentary for one match",
                path="/matches/{match_id}/commentary",
                parent_resource="Match",
                fields=[ApiField(name="text", type="string", description="Commentary text")],
            ),
        ],
        mappings=[
            FieldMapping(
                resource="Match",
                field="id",
                strategy=SourceStrategy.BACKEND_JSON,
                source_url="https://example.com/api/matches",
                expression="$.matches[*].id",
                confidence=0.9,
                evidence="Captured JSON sample",
            )
        ],
    )


def test_rendered_openapi_is_valid_and_contains_mapping_extensions() -> None:
    document = render_openapi(sample_design())

    validate(document)
    operation = document["paths"]["/matches"]["get"]
    assert operation["x-source-strategy"] == "backend_json"
    assert operation["x-source-mapping"][0]["expression"] == "$.matches[*].id"
    nested = document["paths"]["/matches/{match_id}/commentary"]["get"]
    assert nested["parameters"][0]["name"] == "match_id"
