# Environment Variables

## Frontend service

Set this in Railway for the Next.js frontend service:

```env
API_URL=https://your-backend.up.railway.app
```

The frontend uses only `API_URL`. It is read by the Next.js proxy route and forwarded to the browser client through `/api/backend/...`.

## Backend service

Set these in Railway for the FastAPI backend service:

```env
APP_NAME=PDF Converter API
ENVIRONMENT=production
LOG_LEVEL=INFO
APP_HOST=0.0.0.0
APP_PORT=8000
API_V1_PREFIX=/api/v1
ALLOWED_ORIGINS=https://your-frontend.up.railway.app
DATABASE_URL=postgresql+psycopg://user:pass@host.railway.internal:5432/railway

AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

`AZURE_DOCUMENT_INTELLIGENCE_*` are optional and only matter if you want OCR assistance for scanned documents. The regular Excel/PDF upload -> preview -> export flow does not require them.

## Notes

- `DATABASE_URL` is the only required infrastructure connection for the backend.
- `ALLOWED_ORIGINS` must contain the exact frontend origin, for example `https://bisultan-pdf.up.railway.app`.
- The backend normalizes quoted env values, but it is still better to store Railway variables without outer quotes.
