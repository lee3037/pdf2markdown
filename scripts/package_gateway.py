"""Build a Windows source deployment ZIP using an explicit public-file allowlist."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gateway"


def package(destination):
    files = [SOURCE / name for name in ["README.md", "pyproject.toml", "uv.lock", ".env.example"]]
    files += sorted((SOURCE / "pure_gateway").glob("*.py"))
    files += sorted((SOURCE / "windows").glob("*.ps1"))
    manifest = {path.relative_to(SOURCE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(SOURCE).as_posix())
        archive.writestr("MANIFEST.sha256.json", json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    target = ROOT / ".local/pdf2markdown-gateway-windows.zip"
    contents = package(target)
    print(f"Packaged {len(contents)} public files: {target}")
