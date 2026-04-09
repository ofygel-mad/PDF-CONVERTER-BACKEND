from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PDF Converter API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    app_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("APP_HOST"))
    app_port: int = Field(default=8000, validation_alias=AliasChoices("APP_PORT", "PORT"))
    app_reload: bool = Field(default=False, validation_alias=AliasChoices("APP_RELOAD", "UVICORN_RELOAD"))
    startup_db_timeout_seconds: float = Field(
        default=12.0,
        validation_alias=AliasChoices("STARTUP_DB_TIMEOUT_SECONDS"),
    )
    startup_storage_timeout_seconds: float = Field(
        default=8.0,
        validation_alias=AliasChoices("STARTUP_STORAGE_TIMEOUT_SECONDS"),
    )
    allowed_origins: Annotated[str, NoDecode] = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
        validation_alias=AliasChoices("ALLOWED_ORIGINS"),
    )

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5433/pdf_converter",
        validation_alias=AliasChoices("DATABASE_URL"),
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # Railway (and Heroku) provide postgres:// or postgresql:// — psycopg3 needs +psycopg driver prefix
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+psycopg://", 1)
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @field_validator("minio_secure", mode="before")
    @classmethod
    def parse_minio_secure(cls, v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return False

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL"),
    )
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        validation_alias=AliasChoices("CELERY_BROKER_URL", "REDIS_URL"),
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        validation_alias=AliasChoices("CELERY_RESULT_BACKEND", "REDIS_URL"),
    )

    minio_endpoint: str = Field(
        default="localhost:9000",
        validation_alias=AliasChoices("MINIO_ENDPOINT"),
    )
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_ACCESS_KEY"),
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_SECRET_KEY"),
    )
    minio_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("MINIO_SECURE"),
    )
    minio_bucket_raw: str = Field(
        default="raw-documents",
        validation_alias=AliasChoices("MINIO_BUCKET_RAW"),
    )
    minio_bucket_exports: str = Field(
        default="excel-exports",
        validation_alias=AliasChoices("MINIO_BUCKET_EXPORTS"),
    )

    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_key: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
