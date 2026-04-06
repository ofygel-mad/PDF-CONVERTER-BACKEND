from app.services.ocr_mapping_template_service import create_ocr_mapping_template


def test_create_ocr_mapping_template_increments_version_for_same_name(tmp_path, monkeypatch) -> None:
    from app.services import ocr_mapping_template_service

    target_file = tmp_path / "ocr-mapping-templates.json"
    monkeypatch.setattr(ocr_mapping_template_service, "OCR_MAPPING_TEMPLATES_FILE", target_file)

    first = create_ocr_mapping_template(
        name="Kaspi OCR Layout",
        source_filename="kaspi_scan_1.jpeg",
        header_row=["Date", "Amount", "Description"],
        column_mapping={"date": 0, "amount": 1, "detail": 2},
    )
    second = create_ocr_mapping_template(
        name="Kaspi OCR Layout",
        source_filename="kaspi_scan_2.jpeg",
        header_row=["Date", "Amount", "Description"],
        column_mapping={"date": 0, "amount": 1, "detail": 2},
    )

    assert first.version == 1
    assert second.version == 2
