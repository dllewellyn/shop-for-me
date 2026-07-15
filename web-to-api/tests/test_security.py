import pytest

from web_to_api.security import UnsafeUrlError, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "https://user:password@example.com",
    ],
)
async def test_private_and_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url(url)


async def test_public_literal_ip_is_allowed() -> None:
    parsed = await validate_public_url("https://93.184.216.34/")
    assert parsed.scheme == "https"
