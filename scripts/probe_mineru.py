"""Read-only contract check. No PDFs are submitted by this command."""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import load_settings
from backend.app.mineru.client import MinerUClient, MinerUError, ADAPTER_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Optional alternate origin; configured credentials are not sent to a different origin")
    args = parser.parse_args()
    settings = load_settings()
    base = (args.base_url or settings.mineru_base_url).rstrip("/")
    settings = replace(settings, mode="remote", mineru_base_url=base,
                       mineru_api_key=settings.mineru_api_key if base == settings.mineru_base_url else "")
    client = MinerUClient(settings)
    try:
        contract = client.discover()
        result = {"available": True, "style": contract.style, "version": contract.version or "unknown",
                  "adapter": ADAPTER_VERSION, "fingerprint": contract.fingerprint,
                  "form_fields": sorted(contract.fields), "pdf_submitted": False}
    except MinerUError as exc:
        result = {"available": False, "code": exc.code, "message": str(exc), "pdf_submitted": False}
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
