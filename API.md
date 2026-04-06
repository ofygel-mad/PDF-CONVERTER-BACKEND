# Environment Variables

---

## FRONTEND — Railway (Next.js repo)

Вставляешь в Railway → твой фронт-проект → Variables:

```env
# URL бэкенда — тот домен, который Railway выдал твоему бэк-проекту
NEXT_PUBLIC_API_URL=https://your-backend.up.railway.app
```

> Это единственная переменная нужна фронту. Она говорит браузеру куда слать запросы.

---

## BACKEND — Railway (FastAPI repo)

Вставляешь в Railway → твой бэк-проект → Variables:

```env
# ── Приложение ────────────────────────────────────────────────────────────────
ENVIRONMENT=production
LOG_LEVEL=INFO

# Домен твоего фронта — чтобы CORS пропускал запросы
ALLOWED_ORIGINS=https://your-frontend.up.railway.app

# ── База данных ───────────────────────────────────────────────────────────────
# Railway PostgreSQL сам подставляет DATABASE_URL — просто добавь плагин Postgres
# Если Railway не подставил автоматически, скопируй из PostgreSQL → Connect:
DATABASE_URL=postgresql+psycopg://user:pass@host.railway.internal:5432/railway

# ── Redis ─────────────────────────────────────────────────────────────────────
# Railway Redis сам подставляет REDIS_URL — просто добавь плагин Redis
# Или вставь URL вручную:
REDIS_URL=redis://default:password@host.railway.internal:6379

# Celery использует тот же Redis (можно не трогать, возьмёт из REDIS_URL)
CELERY_BROKER_URL=redis://default:password@host.railway.internal:6379/1
CELERY_RESULT_BACKEND=redis://default:password@host.railway.internal:6379/2

# ── Cloudflare R2 (вместо MinIO) ─────────────────────────────────────────────
# Endpoint: Account ID берёшь в Cloudflare → R2 → Overview → Account ID
MINIO_ENDPOINT=<account-id>.r2.cloudflarestorage.com
MINIO_ACCESS_KEY=<R2 Access Key ID>
MINIO_SECRET_KEY=<R2 Secret Access Key>
MINIO_SECURE=true                    # обязательно true для R2

# Названия бакетов — те, что ты уже создал в Cloudflare R2
MINIO_BUCKET_RAW=raw-documents
MINIO_BUCKET_EXPORTS=excel-exports

# ── Azure Document Intelligence (опционально) ─────────────────────────────────
# Оставь пустым если не используешь Azure OCR
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

---

## Где брать значения для Cloudflare R2

1. **Account ID** → cloudflare.com → R2 Object Storage → правый блок "Account ID"
2. **Access Key / Secret Key** → R2 → Manage R2 API Tokens → Create API Token
3. **Bucket names** → те имена, которые ты задал при создании бакетов

## Где брать значения для Railway Redis / Postgres

Railway сам добавляет переменные `DATABASE_URL` и `REDIS_URL` когда добавляешь плагины.  
Проверь: Railway проект → твой бэк-сервис → Variables → там должны быть уже подставлены.  
Если нет — зайди в плагин (Postgres / Redis) → Connect → скопируй URL вручную.
