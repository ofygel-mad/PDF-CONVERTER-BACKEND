from app.schemas.statement import ParsedStatement, StatementMetadata, StatementTotals, StatementTransaction
from app.services.variant_service import build_variants


def test_build_variants_returns_five_views() -> None:
    statement = ParsedStatement(
        metadata=StatementMetadata(
            source_filename="sample.pdf",
            title="Выписка",
            parser_key="kaspi_gold_statement",
            totals=StatementTotals(),
        ),
        transactions=[
            StatementTransaction(
                date="20.03.26",
                amount=7000,
                income=7000,
                expense=None,
                operation="Пополнение",
                detail="С Kaspi Депозита",
                details_operation="С Kaspi ДепозитаПополнение",
                direction="inflow",
            ),
            StatementTransaction(
                date="20.03.26",
                amount=-22000,
                income=None,
                expense=22000,
                operation="Перевод",
                detail="Нұрай Б.",
                details_operation="Нұрай Б.Перевод",
                direction="outflow",
            ),
        ],
    )

    variants = build_variants(statement)

    assert len(variants) == 5
    assert variants[0].key == "classic_financier"
    assert variants[3].key == "daily_summary"


def test_build_variants_adds_business_plus_group_for_kaspi_business() -> None:
    statement = ParsedStatement(
        metadata=StatementMetadata(
            source_filename="business.xlsx",
            title="Выписка по счету",
            parser_key="kaspi_business_statement",
            totals=StatementTotals(),
        ),
        transactions=[
            StatementTransaction(
                date="03.04.2026",
                amount=-500000,
                income=None,
                expense=500000,
                operation="Собственный перевод",
                detail="Мийрибек Азизулы У.",
                details_operation="Мийрибек Азизулы У. | Перевод собственных средств на карту Kaspi Gold *3205",
                direction="outflow",
                document_number="10232853",
                comment="Перевод собственных средств на карту Kaspi Gold *3205",
            )
        ],
    )

    variants = build_variants(statement)

    assert len(variants) == 10
    assert variants[0].group == "primary"
    assert variants[5].group == "kaspi_business_plus"
    assert variants[5].key == "business_compact_classic"
