"""Unit tests for URL safety validation and SSRF protections."""

import socket

import pytest
from fastapi import HTTPException

from ai_ingestion_retrieval_platform.core.url_safety import validate_url_is_safe


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com",
    ],
)
async def test_validate_url_is_safe_allows_public_http_https(
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return fake_addresses

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await validate_url_is_safe(url)
    assert result.hostname == "example.com"
    assert result.resolved_ip == "93.184.216.34"
    assert result.host_header == "example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("ftp://example.com", "Only http and https URLs are allowed"),
        ("file:///etc/hosts", "Only http and https URLs are allowed"),
        ("https://", "URL must include a valid hostname"),
        ("http://localhost", "Localhost URLs are not allowed"),
        ("http://127.0.0.1", "Private/internal IP URLs are not allowed"),
        ("http://10.1.2.3", "Private/internal IP URLs are not allowed"),
        ("http://169.254.169.254", "Private/internal IP URLs are not allowed"),
        ("http://[::1]", "Private/internal IP URLs are not allowed"),
    ],
)
async def test_validate_url_is_safe_rejects_invalid_or_internal_targets(
    url: str,
    expected_detail: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await validate_url_is_safe(url)

    assert exc_info.value.status_code == 400
    assert str(exc_info.value.detail) == expected_detail


@pytest.mark.asyncio
async def test_validate_url_is_safe_rejects_unresolvable_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(HTTPException) as exc_info:
        await validate_url_is_safe("https://does-not-resolve.test")

    assert exc_info.value.status_code == 400
    assert str(exc_info.value.detail) == "URL hostname could not be resolved"


@pytest.mark.asyncio
async def test_validate_url_is_safe_rejects_hostname_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # getaddrinfo tuple shape: (family, type, proto, canonname, sockaddr)
    fake_addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0)),
    ]

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return fake_addresses

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(HTTPException) as exc_info:
        await validate_url_is_safe("https://public-looking-domain.test")

    assert exc_info.value.status_code == 400
    assert str(exc_info.value.detail) == "URL resolves to a private/internal IP"


@pytest.mark.asyncio
async def test_validate_url_is_safe_allows_hostname_resolving_to_public_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ]

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return fake_addresses

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await validate_url_is_safe("https://public-domain.test")
    assert result.hostname == "public-domain.test"
    assert result.resolved_ip == "93.184.216.34"
    assert result.host_header == "public-domain.test"


@pytest.mark.asyncio
async def test_validate_url_is_safe_includes_non_default_port_in_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 8443)),
    ]

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return fake_addresses

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await validate_url_is_safe("https://public-domain.test:8443/path")
    assert result.host_header == "public-domain.test:8443"
