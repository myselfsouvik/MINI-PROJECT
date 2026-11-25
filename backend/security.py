"""
Access control and input checks for the web server.

Two rules:

1. **Who can use the API.** Requests from this computer (127.0.0.1 / ::1) are
   always allowed: that's the person running the demo. Any other device (a
   phone or teammate on the Wi-Fi) must send the access token printed when
   the server starts, either as an ``X-Access-Token`` header or ``?token=``.
   With no token configured, other devices are refused entirely.

2. **What can be opened as a camera.** Through the API, video files must be
   inside the media folder (``recordings/`` by default), and stream URLs can't
   point at link-local / multicast addresses (e.g. 169.254.x.x) or, for
   requests from other devices, at this computer itself. This stops the
   "camera" feature being used to read files from the disk or to make the
   laptop fetch other internal services. Sources given on the command line
   (``--source``) are trusted and skip these checks.
"""

from __future__ import annotations

import ipaddress
import secrets
import socket
from pathlib import Path
from urllib.parse import urlparse

from backend.cameras import parse_source

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_local_client(host: str | None) -> bool:
    return host in LOCAL_HOSTS


def new_token() -> str:
    return secrets.token_urlsafe(12)


def token_ok(expected: str | None, given: str | None) -> bool:
    return bool(expected) and bool(given) and secrets.compare_digest(expected, given)


def check_source(source: str, media_dir: Path, local_client: bool) -> None:
    """Raise ValueError if ``source`` isn't allowed to be opened through the API."""
    kind, value = parse_source(source)   # also raises ValueError for nonsense

    if kind == "file":
        path = Path(value).resolve()
        media = Path(media_dir).resolve()
        if not path.is_relative_to(media):
            raise ValueError(
                f"Video files must be inside the media folder ({media}). Copy the video there first."
            )
        return

    if kind == "stream":
        host = urlparse(str(value)).hostname
        if not host:
            raise ValueError(f"Stream URL {value!r} has no host.")
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except socket.gaierror:
            raise ValueError(f"Can't find the address {host!r}. Check the IP shown in the phone app.")
        for addr in addresses:
            ip = ipaddress.ip_address(addr.split("%")[0])
            if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
                raise ValueError(f"{host} ({ip}) is not allowed as a camera address.")
            if ip.is_loopback and not local_client:
                raise ValueError("Only this computer can add a stream from its own address (localhost).")
