from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from app.core.config import settings


def get_minio_client() -> Minio:
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
        for bucket_name in [settings.minio_bucket_raw, settings.minio_bucket_exports]:
            if not client.bucket_exists(bucket_name):
                client.make_bucket(bucket_name)
    except Exception as e:
        # Storage service not available - app can continue with limited functionality
        import sys
        print(f"Warning: Storage service unavailable: {e}", file=sys.stderr, flush=True)


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
