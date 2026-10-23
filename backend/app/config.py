import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    mode: str = "mock"
    max_upload_mb: int = 20
    max_pdf_pages: int = 200

    def __post_init__(self):
        if self.mode != "mock":
            raise ValueError("M1 仅支持 mock 模式，真实 MinerU 接入将在 M2 实现。")
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
    )
