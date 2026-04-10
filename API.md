# Environment Variables

## Frontend service

Set this in Railway for the Next.js frontend service:

```env
NEXT_PUBLIC_API_URL=https://your-backend.up.railway.app
```

`NEXT_PUBLIC_API_URL` is the main frontend variable. `API_URL` is also accepted as a server-side fallback.

## Backend service

Set these in Railway for the FastAPI backend service:

```env
ENVIRONMENT=production
LOG_LEVEL=INFO
ALLOWED_ORIGINS=https://your-frontend.up.railway.app

DATABASE_URL=postgresql+psycopg://user:pass@host.railway.internal:5432/railway

REDIS_URL=redis://default:password@host.railway.internal:6379
CELERY_BROKER_URL=redis://default:password@host.railway.internal:6379/1
CELERY_RESULT_BACKEND=redis://default:password@host.railway.internal:6379/2

MINIO_ENDPOINT=<account-id>.r2.cloudflarestorage.com
MINIO_ACCESS_KEY=<R2 Access Key ID>
MINIO_SECRET_KEY=<R2 Secret Access Key>
MINIO_SECURE=true
MINIO_BUCKET_RAW=raw-documents
MINIO_BUCKET_EXPORTS=excel-exports

AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

## Notes

Railway usually injects `DATABASE_URL` and `REDIS_URL` automatically when the Postgres and Redis plugins are attached. If not, open the plugin and copy the connection URL from `Connect`.

For Cloudflare R2 you need:

1. Account ID from `R2 Object Storage -> Overview`.
2. Access Key and Secret Key from `Manage R2 API Tokens`.
3. Existing bucket names for raw uploads and exports.
