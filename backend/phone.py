"""
Helpers for connecting a phone through its web browser.

Phone browsers only allow camera access on HTTPS pages (or on localhost), so
the server needs a certificate. We create a *self-signed* one for this
laptop's Wi-Fi address. The phone shows a "connection not private" warning
the first time; tap *Advanced → Proceed* (Chrome) or *Show Details → visit
this website* (Safari). That's expected for a local demo server.
"""

from __future__ import annotations

import datetime as dt
import io
import ipaddress
import socket
from pathlib import Path


def lan_ips() -> list[str]:
    """This computer's IPv4 addresses on the local network, best guess first."""
    ips: list[str] = []
    # The address the OS would use to reach the internet (no packet is sent).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except socket.gaierror:
        pass
    out = []
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if ip not in out and not addr.is_loopback and not addr.is_link_local:
            out.append(ip)
    return out


def ensure_certificate(cert_dir: Path, ips: list[str]) -> tuple[Path, Path]:
    """
    Return (cert_file, key_file), creating a self-signed certificate if there
    isn't one yet or if it doesn't cover the current IP addresses.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_file, key_file = cert_dir / "phone-cert.pem", cert_dir / "phone-key.pem"
    wanted = {ipaddress.ip_address(i) for i in [*ips, "127.0.0.1"]}

    if cert_file.exists() and key_file.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = set(san.get_values_for_type(x509.IPAddress))
            not_expired = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
            if wanted <= have and not_expired:
                return cert_file, key_file
        except Exception:
            pass   # unreadable / old format: make a new one

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DogWatch local server")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), *(x509.IPAddress(i) for i in sorted(wanted, key=str))]),
            critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_file, key_file


def qr_svg(text: str) -> str:
    """QR code for ``text`` as an SVG string (no image libraries needed)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")
