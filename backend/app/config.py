import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    mode: str = "mock"
    max_upload_mb: int = 20
    max_pdf_pages: int = 200
    mineru_base_url: str = ""
    mineru_api_key: str = ""
    mineru_backend: str = ""
    parse_method: str = "auto"
    language: str = "ch"
    request_timeout: float = 60
    connect_timeout: float = 5
    poll_interval: float = 2
    poll_timeout: float = 900
    cache_namespace: str = "v1"

    def __post_init__(self):
        if self.mode not in {"mock", "remote"}:
            raise ValueError("MINERU_MODE 必须为 mock 或 remote。")
        if self.mode == "remote":
            url = urlsplit(self.mineru_base_url)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("远程模式需要有效的 MINERU_BASE_URL，地址不能包含凭据、查询或片段。")
        if self.parse_method not in {"auto", "txt", "ocr"}:
            raise ValueError("MINERU_PARSE_METHOD 必须为 auto、txt 或 ocr。")
        if min(self.request_timeout, self.connect_timeout, self.poll_interval, self.poll_timeout) <= 0:
            raise ValueError("超时与轮询间隔必须大于零。")
        if self.max_upload_mb < 1 or self.max_pdf_pages < 1:
            raise ValueError("文件大小和页数上限必须大于零。")


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    directory = Path(os.environ.get("DATA_DIR", "data"))
    return Settings(
        data_dir=directory if directory.is_absolute() else ROOT / directory,
        mode=os.environ.get("MINERU_MODE", "mock"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "20")),
        max_pdf_pages=int(os.environ.get("MAX_PDF_PAGES", "200")),
        mineru_base_url=os.environ.get("MINERU_BASE_URL", "").rstrip("/"),
        mineru_api_key=os.environ.get("MINERU_API_KEY", ""),
        mineru_backend=os.environ.get("MINERU_BACKEND", ""),
        parse_method=os.environ.get("MINERU_PARSE_METHOD", "auto"),
        language=os.environ.get("MINERU_LANGUAGE", "ch"),
        request_timeout=float(os.environ.get("MINERU_REQUEST_TIMEOUT", "60")),
        connect_timeout=float(os.environ.get("MINERU_CONNECT_TIMEOUT", "5")),
        poll_interval=float(os.environ.get("MINERU_POLL_INTERVAL", "2")),
        poll_timeout=float(os.environ.get("MINERU_POLL_TIMEOUT", "900")),
        cache_namespace=os.environ.get("MINERU_CACHE_NAMESPACE", "v1"),
    )
