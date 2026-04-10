from app.core.config import Settings


def test_port_env_takes_priority_over_app_port(monkeypatch) -> None:
    monkeypatch.setenv("APP_PORT", "8000")
    monkeypatch.setenv("PORT", "32109")

    settings = Settings()

    assert settings.app_port == 32109
