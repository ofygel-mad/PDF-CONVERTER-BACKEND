from types import SimpleNamespace

from app.services.ocr_service import build_statement_from_layout


def test_build_statement_from_layout_parses_generic_table() -> None:
    analyze_result = SimpleNamespace(
        tables=[
            SimpleNamespace(
                row_count=3,
                column_count=4,
                cells=[
                    SimpleNamespace(row_index=0, column_index=0, content="Date"),
                    SimpleNamespace(row_index=0, column_index=1, content="Amount"),
                    SimpleNamespace(row_index=0, column_index=2, content="Description"),
                    SimpleNamespace(row_index=0, column_index=3, content="Operation"),
                    SimpleNamespace(row_index=1, column_index=0, content="2026-04-01"),
                    SimpleNamespace(row_index=1, column_index=1, content="15000"),
                    SimpleNamespace(row_index=1, column_index=2, content="Client payment"),
                    SimpleNamespace(row_index=1, column_index=3, content="Incoming transfer"),
                    SimpleNamespace(row_index=2, column_index=0, content="2026-04-02"),
                    SimpleNamespace(row_index=2, column_index=1, content="-4800"),
                    SimpleNamespace(row_index=2, column_index=2, content="Office rent"),
                    SimpleNamespace(row_index=2, column_index=3, content="Outgoing transfer"),
                ],
            )
        ],
        pages=[],
    )

    statement = build_statement_from_layout("scan.jpeg", analyze_result)

    assert statement.metadata.parser_key == "ocr_scanned_statement"
    assert statement.metadata.transaction_count == 2
    assert statement.transactions[0].income == 15000
    assert statement.transactions[1].expense == 4800
