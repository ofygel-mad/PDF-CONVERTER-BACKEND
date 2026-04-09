from __future__ import annotations

import socket
from minio import Minio
from minio.error import S3Error

from app.core.config import settings


def get_minio_client() -> Minio:
    # Set socket timeout to 5 seconds to prevent hanging
    socket.setdefaulttimeout(5)
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region="us-east-1",  # Cloudflare R2 requires region
    )


def ensure_storage_buckets() -> None:
    try:
        client = get_minio_client()
        required_buckets = [settings.minio_bucket_raw, settings.minio_bucket_exports]
        for bucket_name in required_buckets:
            try:
                if not client.bucket_exists(bucket_name):
                    client.make_bucket(bucket_name)
            except S3Error as e:
                raise RuntimeError(f"Failed to access bucket '{bucket_name}': {e.code}")
    except Exception as e:
        # Storage service not available - app can continue with limited functionality
        import sys
        print(f"⚠️  Storage service unavailable at startup: {e}", file=sys.stderr, flush=True)
        print(f"Endpoint: {settings.minio_endpoint}", file=sys.stderr, flush=True)


def get_storage_health() -> tuple[bool, str]:
    try:
        client = get_minio_client()
        buckets = {bucket.name for bucket in client.list_buckets()}
        required = {settings.minio_bucket_raw, settings.minio_bucket_exports}
        if required.issubset(buckets):
            return True, "ok"
        return False, "missing_required_buckets"
    except S3Error as exc:
        return False, exc.code
    except Exception as exc:
        return False, str(exc)
