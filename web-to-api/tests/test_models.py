from web_to_api.models import InvestigationReport, SourceCandidate, SourceStrategy


def test_preferred_candidate_uses_required_source_order() -> None:
    report = InvestigationReport(
        project_id="example-123",
        requested_url="https://example.com",
        canonical_url="https://example.com",
        candidates=[
            SourceCandidate(
                strategy=SourceStrategy.HEADLESS_BROWSER,
                url="https://example.com",
                evidence="rendered",
                confidence=1,
            ),
            SourceCandidate(
                strategy=SourceStrategy.BACKEND_JSON,
                url="https://example.com/api",
                evidence="xhr",
                confidence=0.4,
            ),
            SourceCandidate(
                strategy=SourceStrategy.RSS,
                url="https://example.com/feed.xml",
                evidence="alternate link",
                confidence=0.2,
            ),
        ],
    )

    assert report.preferred_candidate is not None
    assert report.preferred_candidate.strategy is SourceStrategy.RSS
