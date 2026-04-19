from types import SimpleNamespace

from app import main


def test_ensure_alembic_version_stamps_existing_schema(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_has_table(_: str, table_name: str) -> bool:
        return table_name == "sessions"

    def fake_stamp(cfg, revision: str) -> None:
        calls.append((cfg.name, revision))

    monkeypatch.setattr(main, "_database_has_table", fake_has_table)
    monkeypatch.setattr("alembic.command.stamp", fake_stamp)

    cfg = SimpleNamespace(name="test-config")
    main._ensure_alembic_version("postgresql+psycopg://example/db", cfg)

    assert calls == [("test-config", "head")]


def test_ensure_alembic_version_skips_when_version_table_exists(monkeypatch) -> None:
    calls: list[str] = []

    def fake_has_table(_: str, table_name: str) -> bool:
        return table_name == "alembic_version"

    def fake_stamp(_, revision: str) -> None:
        calls.append(revision)

    monkeypatch.setattr(main, "_database_has_table", fake_has_table)
    monkeypatch.setattr("alembic.command.stamp", fake_stamp)

    main._ensure_alembic_version("postgresql+psycopg://example/db", SimpleNamespace())

    assert calls == []
