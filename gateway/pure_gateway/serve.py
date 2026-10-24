import uvicorn

from .config import environment, load_settings


def main():
    load_settings()  # Validate before binding a listener.
    values = environment()
    port = int(values.get("GATEWAY_PORT", "19092"))
    if port != 19092:
        raise SystemExit("This standalone deployment reserves port 19092; it never binds port 19091.")
    uvicorn.run("pure_gateway.app:create_app", factory=True,
                host=values.get("GATEWAY_HOST", "127.0.0.1"), port=port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
