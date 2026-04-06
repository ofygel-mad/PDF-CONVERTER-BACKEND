from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
OCR_REVIEWS_DIR = DATA_DIR / "ocr-reviews"
PRESETS_FILE = DATA_DIR / "presets.json"
SESSIONS_INDEX_FILE = DATA_DIR / "sessions-index.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
OCR_MAPPING_TEMPLATES_FILE = DATA_DIR / "ocr-mapping-templates.json"
JOB_UPLOADS_DIR = DATA_DIR / "job-uploads"

DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
OCR_REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
JOB_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
