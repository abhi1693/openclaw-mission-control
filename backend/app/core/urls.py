from __future__ import annotations


def public_api_base_url() -> str:
    """Return a LAN-reachable base URL for the Mission Control API.

    Priority:
    1) MISSION_CONTROL_BASE_URL env var (recommended)
    2) First non-loopback IPv4 from `hostname -I`

    Never returns localhost because agents may run on another machine.
    """

    import os
    import re
    import subprocess

    explicit = os.environ.get("MISSION_CONTROL_BASE_URL")
    if explicit:
        return explicit.rstrip("/")

    try:
        out = subprocess.check_output(["bash", "-lc", "hostname -I"], text=True).strip()
        ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", out)
        for ip in ips:
            if ip.startswith("127."):
                continue
            if ip.startswith("172.17."):
                continue
            if ip.startswith(("192.168.", "10.", "172.")):
                return f"http://{ip}:8000"
    except Exception:
        pass

    return "http://<dev-machine-ip>:8000"
