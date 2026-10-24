"""Read-only Windows-local preflight. Never uploads a PDF or changes the upstream."""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from .config import environment, validate_upstream
from .upstream import NativeClient, UpstreamError


async def inspect(args):
    values = environment()
    settings = SimpleNamespace(upstream=validate_upstream(values.get("GATEWAY_UPSTREAM_URL", "http://127.0.0.1:58666")),
        expected_version=values.get("GATEWAY_EXPECTED_VERSION", "3.1.1"), backend=values.get("GATEWAY_BACKEND", ""), request_timeout=10)
    client = NativeClient(settings)
    report = {"available": False, "pdf_submitted": False}
    try:
        report.update(await client.probe(), available=True, protocol="native-async")
        if args.save_schema:
            _, schema = await client.request("GET", "/openapi.json")
            path = Path(args.save_schema)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    except UpstreamError as exc:
        report["code"] = exc.code
    finally:
        await client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["available"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-schema", help="Optional local file for the upstream OpenAPI; do not commit live responses")
    return asyncio.run(inspect(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
