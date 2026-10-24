import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def validate_upstream(url):
    value = urlsplit(url)
    if (value.scheme not in {"http", "https"} or value.hostname not in {"127.0.0.1", "localhost", "::1"}
            or value.username or value.password or value.query or value.fragment
            or value.path not in {"", "/"} or value.port in {19091, 19092}):
        raise ValueError("Gateway upstream must be a loopback MinerU origin, excluding ports 19091/19092.")
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    token: str
    data_dir: Path
    upstream: str = "http://127.0.0.1:58666"
    expected_version: str = "3.1.1"
    max_upload_mb: int = 20
    max_pages: int = 200
    max_pending: int = 4
    poll_interval: float = 2
    request_timeout: float = 60
    backend: str = ""
    cache_namespace: str = "v1"

    def __post_init__(self):
        if len(self.token) < 32 or self.token.startswith("REPLACE_") or not self.token.isascii():
            raise ValueError("Set a new ASCII GATEWAY_TOKEN of at least 32 characters in gateway/.env.")
        validate_upstream(self.upstream)
        if min(self.max_upload_mb, self.max_pages, self.max_pending, self.poll_interval, self.request_timeout) <= 0:
            raise ValueError("Gateway limits must be positive.")
        if self.backend not in {"", "pipeline", "hybrid-auto-engine", "vlm-auto-engine"}:
            raise ValueError("Only local MinerU backends are supported; no client-supplied server URL.")


def environment():
    return {**dotenv_values(ROOT / ".env"), **os.environ}


def load_settings():
    values = environment()
    directory = Path(values.get("GATEWAY_DATA_DIR", "data"))
    return Settings(
        token=values.get("GATEWAY_TOKEN", ""), data_dir=directory if directory.is_absolute() else ROOT / directory,
        upstream=values.get("GATEWAY_UPSTREAM_URL", "http://127.0.0.1:58666").rstrip("/"),
        expected_version=values.get("GATEWAY_EXPECTED_VERSION", "3.1.1"),
        max_upload_mb=int(values.get("GATEWAY_MAX_UPLOAD_MB", "20")),
        max_pages=int(values.get("GATEWAY_MAX_PAGES", "200")),
        max_pending=int(values.get("GATEWAY_MAX_PENDING", "4")),
        poll_interval=float(values.get("GATEWAY_POLL_INTERVAL", "2")),
        request_timeout=float(values.get("GATEWAY_REQUEST_TIMEOUT", "60")), backend=values.get("GATEWAY_BACKEND", ""),
        cache_namespace=values.get("GATEWAY_CACHE_NAMESPACE", "v1"),
    )
