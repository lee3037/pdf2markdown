"""Input preconditions only; these tests do not prove OCR engine quality."""
from pathlib import Path

from pypdf import PdfReader

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures"


def test_real_acceptance_text_fixture_contains_known_source_and_table_values():
    reader = PdfReader(FIXTURES / "live-text.pdf")
    assert len(reader.pages) == 2
    text = "\n".join(page.extract_text() for page in reader.pages)
    for phrase in ["ORCHID-4827", "1234.50", "Atlas", "300.00", "Beacon", "934.50", "RIVER-9362", "知识库转换验收"]:
        assert phrase in text


def test_real_acceptance_scan_fixture_is_image_only_on_every_page():
    reader = PdfReader(FIXTURES / "live-scan.pdf")
    assert len(reader.pages) == 2
    for page in reader.pages:
        assert not page.extract_text().strip()
        assert len(page.images) == 1
