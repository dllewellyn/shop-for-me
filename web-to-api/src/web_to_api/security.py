from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin

import anyio
import httpx
from protego import Protego


class UnsafeUrlError(ValueError):
    """Raised when a URL could reach a non-public network destination."""


class RobotsDeniedError(PermissionError):
    """Raised when robots.txt disallows crawling a URL."""


async def validate_public_url(url: str) -> httpx.URL:
    parsed = httpx.URL(url)
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise UnsafeUrlError("Only absolute HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Credentials in URLs are not supported")

    try:
        literal_ip = ipaddress.ip_address(parsed.host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise UnsafeUrlError("The URL resolves to a non-public IP address")
        return parsed

    def resolve() -> set[str]:
        return {
            item[4][0]
            for item in socket.getaddrinfo(parsed.host, parsed.port or 443, type=socket.SOCK_STREAM)
        }

    try:
        addresses = await anyio.to_thread.run_sync(resolve)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {parsed.host}") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise UnsafeUrlError("The URL resolves to a non-public IP address")
    return parsed


@dataclass(slots=True)
class PublicResponse:
    response: httpx.Response
    body: bytes


async def fetch_public(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    max_redirects: int = 5,
) -> PublicResponse:
    current = await validate_public_url(url)
    for _ in range(max_redirects + 1):
        async with client.stream("GET", current, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise httpx.TooManyRedirects("Redirect was missing a Location header")
                current = await validate_public_url(urljoin(str(current), location))
                continue
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"Response exceeded the {max_bytes}-byte investigation limit")
                chunks.append(chunk)
            return PublicResponse(response=response, body=b"".join(chunks))
    raise httpx.TooManyRedirects(f"More than {max_redirects} redirects")


async def assert_robots_allowed(
    client: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
    max_bytes: int,
) -> None:
    target = await validate_public_url(url)
    robots_url = target.copy_with(path="/robots.txt", query=None, fragment=None)
    result = await fetch_public(client, str(robots_url), max_bytes=min(max_bytes, 512_000))
    if result.response.status_code == 404:
        return
    if result.response.status_code >= 400:
        raise RobotsDeniedError(
            f"Could not establish robots policy ({result.response.status_code})"
        )
    parser = Protego.parse(result.body.decode("utf-8", errors="replace"))
    if not parser.can_fetch(str(target), user_agent):
        raise RobotsDeniedError(f"robots.txt disallows {target.path}")
