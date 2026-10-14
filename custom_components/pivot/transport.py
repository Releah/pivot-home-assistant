"""Explicit transport configuration; no redirects, TLS bypass or downgrade."""
import ssl
from urllib.parse import urlsplit


def transport_settings(settings):
    mode = settings["transport"]
    origin = settings["origin"]
    if mode not in ("http", "https") or not isinstance(origin, str):
        raise ValueError("transport_invalid")
    parsed = urlsplit(origin)
    if (parsed.scheme != mode or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
            or "?" in origin or "#" in origin or any(c.isspace() for c in origin)):
        raise ValueError("origin_invalid")
    if parsed.port is None:
        raise ValueError("explicit_port_required")
    if mode == "http":
        if "ca_file" in settings:
            raise ValueError("transport_invalid")
        return origin, True
    ca_file = settings["ca_file"]
    if not isinstance(ca_file, str) or not ca_file:
        raise ValueError("ca_required")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return origin, context
