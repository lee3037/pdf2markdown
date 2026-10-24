"""Public synthetic inputs for real-engine acceptance, never Mock output.

Regenerate with: uv run --with reportlab python scripts/generate_live_fixtures.py
Requires Poppler's pdftoppm on PATH. The scan is rasterized at 180 dpi.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/fixtures"
SIZE = (595, 842)


def make_text(path, font):
    pdfmetrics.registerFont(TTFont("FixtureCJK", str(font)))
    doc = canvas.Canvas(str(path), pagesize=SIZE, invariant=1)
    doc.setTitle("Public synthetic MinerU acceptance fixture")
    for page in (1, 2):
        doc.setFont("Helvetica", 10)
        doc.drawString(48, 806, "PUBLIC SYNTHETIC FIXTURE - no business data")
        doc.setFont("Helvetica-Bold", 20)
        doc.drawString(48, 755, f"{page}. {'PDF Conversion Acceptance' if page == 1 else 'Retrieval Context'}")
        doc.setFont("FixtureCJK", 16)
        doc.drawString(48, 718, "知识库转换验收" if page == 1 else "来源与检索上下文")
        doc.setFont("Helvetica", 12)
        lines = (["The calibration code is ORCHID-4827.",
                  "The invoice total is 1234.50 CNY.",
                  "1. Keep the section heading with its paragraph.",
                  "2. Preserve every table cell and row relationship."] if page == 1 else
                 ["The second chapter explains independent knowledge blocks.",
                  "Source pages must be traceable without invented mappings.",
                  "The review code is RIVER-9362."])
        for i, line in enumerate(lines):
            doc.drawString(48, 675 - i * 28, line)
        if page == 1:
            xs, ys = [48, 290, 400, 547], [510, 478, 446, 414]
            for x in xs:
                doc.line(x, ys[-1], x, ys[0])
            for y in ys:
                doc.line(xs[0], y, xs[-1], y)
            for row, values in enumerate([("Item", "Quantity", "Amount (CNY)"), ("Atlas", "3", "300.00"), ("Beacon", "7", "934.50")]):
                doc.setFont("Helvetica-Bold" if row == 0 else "Helvetica", 12)
                for col, value in enumerate(values):
                    doc.drawString(xs[col] + 8, ys[row] - 21, value)
        doc.setFont("Helvetica", 10)
        doc.drawCentredString(SIZE[0] / 2, 30, str(page))
        doc.showPage()
    doc.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
                        help="CJK TrueType font to subset/embed; use an installed compatible font on other systems")
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error("Pass --font with an installed CJK TrueType font; no fallback with missing glyphs is allowed.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    native = OUTPUT / "live-text.pdf"
    make_text(native, args.font)
    with tempfile.TemporaryDirectory(prefix="pdf2markdown-fixtures-") as temporary:
        prefix = Path(temporary) / "page"
        subprocess.run(["pdftoppm", "-r", "180", "-png", str(native), str(prefix)], check=True)
        scanned = canvas.Canvas(str(OUTPUT / "live-scan.pdf"), pagesize=SIZE, invariant=1)
        scanned.setTitle("Public image-only synthetic OCR acceptance fixture")
        for image in sorted(Path(temporary).glob("page-*.png")):
            scanned.drawImage(ImageReader(str(image)), 0, 0, width=SIZE[0], height=SIZE[1])
            scanned.showPage()
        scanned.save()
    print("Generated public text and image-only scan fixtures (2 pages each).")


if __name__ == "__main__":
    main()
