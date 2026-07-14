"""SSRF and DNS safety checks for outbound URL fetching."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import HTTPException

from ai_ingestion_retrieval_platform.core.config import Settings

BLOCKED_HOSTNAMES = {"localhost"}
BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}

DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class SafeFetchTarget:
    """Result of a validated SSRF safety check."""

    hostname: str
    resolved_ip: str
    host_header: str


def _normalize_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped

    return ip


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    normalized_ip = _normalize_ip(ip)

    return (
        normalized_ip.is_private
        or normalized_ip.is_loopback
        or normalized_ip.is_link_local
        or normalized_ip.is_multicast
        or normalized_ip.is_reserved
        or normalized_ip.is_unspecified
        or normalized_ip in BLOCKED_IPS
    )


def _build_host_header(hostname: str, scheme: str, port: int) -> str:
    if port == DEFAULT_PORTS.get(scheme):
        return hostname

    return f"{hostname}:{port}"


def _get_validated_port(
    scheme: str,
    port: int | None,
    allowed_ports: tuple[int, ...],
) -> int:
    resolved_port = port or DEFAULT_PORTS[scheme]

    if resolved_port not in allowed_ports:
        raise HTTPException(
            status_code=400,
            detail="URL port is not allowed",
        )

    return resolved_port


async def validate_url_is_safe(
    url: str,
    settings: Settings,
) -> SafeFetchTarget:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="Only http and https URLs are allowed",
        )

    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="URL credentials are not allowed",
        )

    if not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="URL must include a valid hostname",
        )

    hostname = parsed.hostname.lower().rstrip(".")

    if hostname in BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=400,
            detail="Localhost URLs are not allowed",
        )

    try:
        port = _get_validated_port(
            parsed.scheme,
            parsed.port,
            settings.allowed_fetch_ports,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="URL port is invalid",
        ) from exc

    host_header = _build_host_header(hostname, parsed.scheme, port)

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        normalized_literal_ip = _normalize_ip(literal_ip)

        if _is_blocked_ip(normalized_literal_ip):
            raise HTTPException(
                status_code=400,
                detail="Private/internal IP URLs are not allowed",
            )

        return SafeFetchTarget(
            hostname=hostname,
            resolved_ip=str(normalized_literal_ip),
            host_header=host_header,
        )

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
        )
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400,
            detail="URL hostname could not be resolved",
        ) from exc

    if not addresses:
        raise HTTPException(
            status_code=400,
            detail="URL hostname could not be resolved",
        )

    resolved_ips = {
        _normalize_ip(ipaddress.ip_address(address[4][0])) for address in addresses
    }

    for ip in resolved_ips:
        if _is_blocked_ip(ip):
            raise HTTPException(
                status_code=400,
                detail="URL resolves to a private/internal IP",
            )

    pinned_ip = next(iter(resolved_ips))

    return SafeFetchTarget(
        hostname=hostname,
        resolved_ip=str(pinned_ip),
        host_header=host_header,
    )
