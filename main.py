import sys
print("=== STARTUP: Python interpreter OK ===", flush=True)

try:
    import uvicorn
    print("=== STARTUP: uvicorn imported OK ===", flush=True)
except Exception as e:
    print(f"=== STARTUP ERROR: uvicorn import failed: {e} ===", flush=True)
    sys.exit(1)

try:
    from app.core.config import settings
    print(f"=== STARTUP: config OK, port={settings.app_port}, host={settings.app_host} ===", flush=True)
except Exception as e:
    print(f"=== STARTUP ERROR: config import failed: {e} ===", flush=True)
    sys.exit(1)

try:
    from app.main import app  # noqa: F401 - triggers all route/service imports
    print("=== STARTUP: app imported OK, starting uvicorn ===", flush=True)
except Exception as e:
    print(f"=== STARTUP ERROR: app import failed: {e} ===", flush=True)
    sys.exit(1)


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )


if __name__ == "__main__":
    main()
