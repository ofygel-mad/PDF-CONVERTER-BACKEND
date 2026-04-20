"""Re-export suppress_stamps for convenience; full logic lives in preprocessor.py."""
from app.services.scanned.preprocessor import suppress_stamps

__all__ = ["suppress_stamps"]
