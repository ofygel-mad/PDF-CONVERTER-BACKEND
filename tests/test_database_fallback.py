import app.core.database as database


def test_invalid_primary_database_falls_back_to_sqlite(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        database.settings,
        "database_url",
        "postgresql+psycopg://postgres:postgres@127.0.0.1:1/pdf_converter",
    )
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "_resolved_database_url", None)
    monkeypatch.setattr(database, "_initialized", False)

    engine = database.get_engine()

    try:
        assert str(engine.url).startswith("sqlite:///")
        assert database.get_resolved_database_url().startswith("sqlite:///")
    finally:
        engine.dispose()
