from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.mock import sample_pdf

target = ROOT / "tests/fixtures/sample.pdf"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(sample_pdf())
print("Generated public synthetic fixture:", target)
