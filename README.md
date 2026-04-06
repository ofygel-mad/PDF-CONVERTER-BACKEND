## Backend

Run local API:

```powershell
uv run python main.py
```

Run worker:

```powershell
uv run celery -A app.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

Run tests:

```powershell
uv run pytest
```
