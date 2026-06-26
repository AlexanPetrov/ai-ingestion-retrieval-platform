import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import HTTPException

BLOCKED_HOSTNAMES = {"localhost"}
BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}

DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class SafeFetchTarget:
    """Result of a validated SSRF safety check.

    Carries the exact IP that was validated, plus the headers/SNI value
    needed to connect directly to that IP while still presenting the
    original hostname. This lets the caller pin the connection to the
    validated IP instead of letting httpx re-resolve the hostname later,
    which would reopen a DNS-rebinding gap between "the IP we checked" and
    "the IP we actually connect to", and would duplicate a blocking DNS
    lookup on the same shared thread pool.
    """

    hostname: str
    resolved_ip: str
    host_header: str


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in BLOCKED_IPS
    )


def _build_host_header(hostname: str, scheme: str, port: int) -> str:
    if port == DEFAULT_PORTS.get(scheme):
        return hostname
    return f"{hostname}:{port}"


async def validate_url_is_safe(url: str) -> SafeFetchTarget:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="Only http and https URLs are allowed",
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

    port = parsed.port or DEFAULT_PORTS[parsed.scheme]
    host_header = _build_host_header(hostname, parsed.scheme, port)

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise HTTPException(
                status_code=400,
                detail="Private/internal IP URLs are not allowed",
            )

        return SafeFetchTarget(
            hostname=hostname,
            resolved_ip=str(literal_ip),
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

    resolved_ips = [ipaddress.ip_address(address[4][0]) for address in addresses]

    for ip in resolved_ips:
        if _is_blocked_ip(ip):
            raise HTTPException(
                status_code=400,
                detail="URL resolves to a private/internal IP",
            )

    # Every address above was validated, so pinning to the first one is
    # safe -- it's the exact result the check above vouched for, not a
    # fresh lookup that could return something different.
    pinned_ip = resolved_ips[0]

    return SafeFetchTarget(
        hostname=hostname,
        resolved_ip=str(pinned_ip),
        host_header=host_header,
    )
