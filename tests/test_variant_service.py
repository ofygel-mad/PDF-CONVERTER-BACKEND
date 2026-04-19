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

    assert len(variants) == 1
    assert variants[0].key == "classic_financier"


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

    assert len(variants) == 1
    assert variants[0].group == "kaspi_business_plus"
    assert variants[0].key == "business_compact_classic"
    assert [column.key for column in variants[0].columns] == [
        "date",
        "income",
        "expense",
        "detail",
        "comment",
    ]


def test_halyk_variant_expands_foreign_purchase_into_fx_rows() -> None:
    statement = ParsedStatement(
        metadata=StatementMetadata(
            source_filename="halyk.pdf",
            title="Halyk statement",
            parser_key="halyk_fiz_statement",
            totals=StatementTotals(),
        ),
        transactions=[
            StatementTransaction(
                date="27.03.26",
                amount=-3.67,
                income=None,
                expense=3.67,
                operation="Покупка",
                detail="Операция оплаты у коммерсанта FACEBK *85TSXE5P62",
                details_operation="FACEBK *85TSXE5P62 / Покупка",
                direction="outflow",
                currency_op="USD",
                processing_date="29.03.26",
                comment="Дата тр: 27.03.26",
            ),
            StatementTransaction(
                date="27.03.26",
                amount=-7.34,
                income=None,
                expense=7.34,
                operation="Покупка",
                detail="Операция оплаты у коммерсанта FACEBK *R4J2AGRP62",
                details_operation="FACEBK *R4J2AGRP62 / Покупка",
                direction="outflow",
                currency_op="USD",
                processing_date="29.03.26",
                comment="Дата тр: 27.03.26",
            ),
            StatementTransaction(
                date="28.03.26",
                amount=-5349.76,
                income=None,
                expense=5349.76,
                operation="autoconv",
                detail="Автоконвертация дополнительной суммы по прошедшим операциям",
                details_operation="Автоконвертация дополнительной суммы по прошедшим операциям",
                direction="outflow",
                currency_op="USD",
                processing_date="28.03.26",
                note="fx:-11.01",
            ),
            StatementTransaction(
                date="28.03.26",
                amount=11.01,
                income=11.01,
                expense=None,
                operation="autoconv",
                detail="Автоконвертация дополнительной суммы по прошедшим операциям",
                details_operation="Автоконвертация дополнительной суммы по прошедшим операциям",
                direction="inflow",
                currency_op="USD",
                processing_date="28.03.26",
                note="fx:11.01",
            ),
        ],
    )

    variants = build_variants(statement)

    assert len(variants) == 1
    variant = variants[0]
    assert [column.key for column in variant.columns] == [
        "processing_date",
        "currency_op",
        "detail",
        "income",
        "expense",
        "comment",
        "aux_summary",
        "aux_detail",
    ]
    assert len(variant.rows) == 6

    purchase_rows = [row for row in variant.rows if row["detail"] in {"FACEBK *85TSXE5P62", "FACEBK *R4J2AGRP62"}]
    assert len(purchase_rows) == 2
    assert all("(Общий 11,1 usd = в kzt общий 5 349,76)" in str(row["comment"]) for row in purchase_rows)
    assert all(row["aux_summary"] for row in purchase_rows)
    assert {row["aux_detail"] for row in purchase_rows} == {"FACEBK *85TSXE5P62", "FACEBK *R4J2AGRP62"}

    kzt_rows = [row for row in variant.rows if "- (Авто. Конв) - (общий 5 349,76)" in str(row["detail"])]
    assert len(kzt_rows) == 2
    assert sum(float(row["expense"]) for row in kzt_rows) == 5349.76
    assert all("Дата тр: 28.03.26" in str(row["comment"]) for row in kzt_rows)
    assert all(row["aux_summary"] for row in kzt_rows)
    assert all("Автоконвертация дополнительной суммы" in str(row["aux_detail"]) for row in kzt_rows)

    currency_rows = [row for row in variant.rows if "- (Авто. Конв) - (общий 11,1)" in str(row["detail"])]
    assert len(currency_rows) == 2
    assert sum(float(row["income"]) for row in currency_rows) == 11.01
    assert all(row["aux_summary"] for row in currency_rows)
    assert all("Автоконвертация дополнительной суммы" in str(row["aux_detail"]) for row in currency_rows)


def test_halyk_variant_matches_positive_autoconv_that_arrives_earlier() -> None:
    statement = ParsedStatement(
        metadata=StatementMetadata(
            source_filename="halyk.pdf",
            title="Halyk statement",
            parser_key="halyk_fiz_statement",
            totals=StatementTotals(),
        ),
        transactions=[
            StatementTransaction(
                date="28.03.26",
                amount=-2.98,
                income=None,
                expense=2.98,
                operation="Покупка",
                detail="Операция оплаты у коммерсанта FACEBK *Y9MFSG5Q62",
                details_operation="FACEBK *Y9MFSG5Q62 / Покупка",
                direction="outflow",
                currency_op="USD",
                processing_date="30.03.26",
                comment="Дата тр: 28.03.26",
            ),
            StatementTransaction(
                date="29.03.26",
                amount=8.94,
                income=8.94,
                expense=None,
                operation="autoconv",
                detail="Автоконвертация дополнительной суммы по прошедшим операциям",
                details_operation="Автоконвертация дополнительной суммы по прошедшим операциям",
                direction="inflow",
                currency_op="USD",
                processing_date="29.03.26",
                note="fx:8.94",
            ),
            StatementTransaction(
                date="29.03.26",
                amount=-5.96,
                income=None,
                expense=5.96,
                operation="Покупка",
                detail="Операция оплаты у коммерсанта FACEBK *GWGUKGVP62",
                details_operation="FACEBK *GWGUKGVP62 / Покупка",
                direction="outflow",
                currency_op="USD",
                processing_date="30.03.26",
                comment="Дата тр: 29.03.26",
            ),
            StatementTransaction(
                date="29.03.26",
                amount=-4343.95,
                income=None,
                expense=4343.95,
                operation="autoconv",
                detail="Автоконвертация дополнительной суммы по прошедшим операциям",
                details_operation="Автоконвертация дополнительной суммы по прошедшим операциям",
                direction="outflow",
                currency_op="USD",
                processing_date="29.03.26",
                note="fx:-8.94",
            ),
        ],
    )

    variant = build_variants(statement)[0]

    assert len(variant.rows) == 6
    assert len([row for row in variant.rows if "- (Авто. Конв) - (общий 4343,95)" in str(row["detail"])]) == 2
    assert len([row for row in variant.rows if "- (Авто. Конв) - (общий 8,94)" in str(row["detail"])]) == 2
    assert all(
        "(Общий 8,94 usd = в kzt общий 4 343,95)" in str(row["comment"])
        for row in variant.rows
        if "FACEBK *" in str(row["detail"])
    )
    assert sum(1 for row in variant.rows if row["aux_detail"] is None) >= 1
