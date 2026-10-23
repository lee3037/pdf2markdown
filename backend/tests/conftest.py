from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.app.config import Settings
from backend.app.main import create_app


def pdf_bytes(pages=1, password=None):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password:
        writer.encrypt(password)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, max_upload_mb=1, max_pdf_pages=3)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client
