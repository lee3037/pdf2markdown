"""Check the local gateway using its token without printing credentials."""
import json

import httpx

from .config import load_settings


def main():
    settings = load_settings()
    try:
        response = httpx.get("http://127.0.0.1:19092/health", headers={"Authorization": "Bearer " + settings.token},
                             timeout=15, trust_env=False, follow_redirects=False)
        body = response.json()
        print(json.dumps({"http_status": response.status_code, "health": body}, ensure_ascii=False, indent=2))
        return 0 if response.status_code == 200 and body.get("status") == "healthy" else 1
    except (httpx.HTTPError, ValueError):
        print(json.dumps({"available": False, "code": "gateway_connection_or_response_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
