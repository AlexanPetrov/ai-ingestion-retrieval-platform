import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

BLOCKED_HOSTNAMES = {"localhost"}
BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


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


async def validate_url_is_safe(url: str) -> None:
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

    try:
        ip = ipaddress.ip_address(hostname)
        if _is_blocked_ip(ip):
            raise HTTPException(
                status_code=400,
                detail="Private/internal IP URLs are not allowed",
            )
        return
    except ValueError:
        pass

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            None,
        )
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400,
            detail="URL hostname could not be resolved",
        ) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if _is_blocked_ip(ip):
            raise HTTPException(
                status_code=400,
                detail="URL resolves to a private/internal IP",
            )
