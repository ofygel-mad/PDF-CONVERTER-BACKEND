from __future__ import annotations

import os
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.statement import (
    AddOnboardingSampleRequest,
    AppliedRuleInfo,
    CorrectionMemoryEntry,
    CreateOnboardingProjectRequest,
    CreatePreviewJobResponse,
    CreateTemplateRequest,
    ExportCsvRequest,
    ExportRequest,
    JobSummary,
    MaterializeOCRReviewRequest,
    OCRMappingTemplate,
    OCRRuleManagerSnapshot,
    OCRRuleVersionDiff,
    OnboardingProject,
    ParserMatch,
    PreferenceRecord,
    PreviewResponse,
    SavePreferenceRequest,
    TransformationTemplate,
    UpdateOCRRuleRequest,
    UpdateRowRequest,
    UpdateTemplateRequest,
    VisionStatus,
)
from app.services.document_service import (
    DocumentParseError,
    list_supported_parsers,
    parse_statement_with_diagnostics,
)
from app.services.export_service import export_statement, export_statement_csv
from app.services.job_service import create_preview_job, get_job, list_jobs
from app.services.ocr_mapping_template_service import (
    compare_ocr_mapping_template_versions,
    find_best_ocr_mapping_match,
    get_ocr_mapping_template,
    get_ocr_rule_manager_snapshot,
    list_ocr_mapping_templates,
    rollback_ocr_mapping_template,
    set_ocr_mapping_template_status,
)
from app.services.ocr_review_service import (
    create_ocr_review_session,
    materialize_ocr_review,
    save_mapping_template_from_review,
)
from app.services.onboarding_service import (
    add_onboarding_sample,
    create_onboarding_project,
    get_onboarding_project,
    list_onboarding_projects,
)
from app.services.quality_service import analyze_statement_quality
from app.services.session_service import (
    get_preference,
    list_correction_memory,
    list_preferences,
    list_recent_sessions,
    load_session,
    save_preference,
    save_session,
    update_session_transaction,
)
from app.services.template_service import create_template, list_templates, update_template
from app.services.variant_service import apply_template_to_variant, build_template_seed, build_variants
from app.services.vision_service import get_vision_status
from app.workers.tasks import preview_transform_job

router = APIRouter(prefix="/transforms")


@router.post("/preview", response_model=PreviewResponse)
async def preview_transform(file: UploadFile = File(...)) -> PreviewResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой.")

    try:
        statement, parser_matches = parse_statement_with_diagnostics(
            file.filename or "uploaded-document",
            content,
        )
    except DocumentParseError as exc:
        review_response = _build_ocr_review_preview(file.filename or "uploaded-document", content)
        if review_response is not None:
            return review_response
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session_id = save_session(statement)
    preference = get_preference(statement.metadata.parser_key)
    return _build_preview_response(session_id, statement, preference, parser_matches)


@router.post("/jobs/preview", response_model=CreatePreviewJobResponse)
async def create_preview_transform_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> CreatePreviewJobResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой.")

    job = create_preview_job(file.filename or "uploaded-document", content)
    if os.getenv("PYTEST_CURRENT_TEST"):
        preview_transform_job(job.job_id)
    else:
        try:
            preview_transform_job.delay(job.job_id)
        except Exception:
            background_tasks.add_task(preview_transform_job, job.job_id)

    return CreatePreviewJobResponse(job_id=job.job_id, status=job.status)


@router.get("/jobs", response_model=list[JobSummary])
async def get_preview_jobs() -> list[JobSummary]:
    return list_jobs()


@router.get("/jobs/{job_id}", response_model=JobSummary)
async def get_preview_job(job_id: str) -> JobSummary:
    try:
        return get_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=PreviewResponse)
async def get_session_preview(session_id: str) -> PreviewResponse:
    try:
        statement = load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    preference = get_preference(statement.metadata.parser_key)
    parser_label = next(
        (
            parser.label
            for parser in list_supported_parsers()
            if parser.key == statement.metadata.parser_key
        ),
        statement.metadata.parser_key,
    )
    return _build_preview_response(
        session_id,
        statement,
        preference,
        [ParserMatch(key=statement.metadata.parser_key, label=parser_label, score=1.0, matched=True)],
    )


@router.post("/export")
async def export_transform(request: ExportRequest) -> StreamingResponse:
    try:
        statement = load_session(request.session_id)
        workbook_bytes = export_statement(statement, request.variant_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = f"{request.variant_key}-{request.session_id}.xlsx"
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/csv")
async def export_transform_csv(request: ExportCsvRequest) -> StreamingResponse:
    try:
        statement = load_session(request.session_id)
        csv_bytes = export_statement_csv(statement, request.variant_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = f"{request.variant_key}-{request.session_id}.csv"
    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ocr-reviews/{review_id}/materialize", response_model=PreviewResponse)
async def materialize_review_to_preview(
    review_id: str,
    request: MaterializeOCRReviewRequest,
) -> PreviewResponse:
    try:
        statement = materialize_ocr_review(review_id, request)
        if request.save_mapping_template:
            save_mapping_template_from_review(review_id, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_id = save_session(statement)
    preference = get_preference(statement.metadata.parser_key)
    parser_label = next(
        (
            parser.label
            for parser in list_supported_parsers()
            if parser.key == statement.metadata.parser_key
        ),
        statement.metadata.parser_key,
    )
    return _build_preview_response(
        session_id,
        statement,
        preference,
        [ParserMatch(key=statement.metadata.parser_key, label=parser_label, score=1.0, matched=True)],
    )


@router.patch("/sessions/{session_id}/rows/{row_number}", response_model=PreviewResponse)
async def patch_session_row(
    session_id: str,
    row_number: int,
    request: UpdateRowRequest,
) -> PreviewResponse:
    try:
        statement = update_session_transaction(
            session_id,
            row_number,
            date=request.date,
            amount=request.amount,
            operation=request.operation,
            detail=request.detail,
            direction=request.direction,
            note=request.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    preference = get_preference(statement.metadata.parser_key)
    parser_label = next(
        (
            parser.label
            for parser in list_supported_parsers()
            if parser.key == statement.metadata.parser_key
        ),
        statement.metadata.parser_key,
    )
    return _build_preview_response(
        session_id,
        statement,
        preference,
        [ParserMatch(key=statement.metadata.parser_key, label=parser_label, score=1.0, matched=True)],
    )


@router.post("/preferences")
async def upsert_preference(request: SavePreferenceRequest) -> PreferenceRecord:
    preference = PreferenceRecord(
        parser_key=request.parser_key,
        preferred_variant_key=request.preferred_variant_key,
        always_show_alternatives=request.always_show_alternatives,
        updated_at=datetime.now(UTC),
    )
    return save_preference(preference)


@router.get("/preferences")
async def get_preferences() -> list[PreferenceRecord]:
    return list_preferences()


@router.get("/correction-memory", response_model=list[CorrectionMemoryEntry])
async def get_correction_memory(parser_key: str | None = None) -> list[CorrectionMemoryEntry]:
    return [CorrectionMemoryEntry.model_validate(item) for item in list_correction_memory(parser_key)]


@router.get("/history")
async def get_history():
    return list_recent_sessions()


@router.get("/parsers")
async def get_parsers():
    return list_supported_parsers()


@router.get("/vision-status", response_model=VisionStatus)
async def get_vision_runtime_status() -> VisionStatus:
    return get_vision_status()


@router.get("/templates")
async def get_templates(parser_key: str | None = None) -> list[TransformationTemplate]:
    return list_templates(parser_key)


@router.post("/templates")
async def post_template(request: CreateTemplateRequest) -> TransformationTemplate:
    return create_template(request)


@router.patch("/templates/{template_id}")
async def patch_template(template_id: str, request: UpdateTemplateRequest) -> TransformationTemplate:
    try:
        return update_template(template_id, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ocr-mapping-templates", response_model=list[OCRMappingTemplate])
async def get_ocr_mapping_templates() -> list[OCRMappingTemplate]:
    return list_ocr_mapping_templates()


@router.get("/ocr-rule-manager", response_model=OCRRuleManagerSnapshot)
async def get_ocr_rule_manager() -> OCRRuleManagerSnapshot:
    return get_ocr_rule_manager_snapshot()


@router.patch("/ocr-mapping-templates/{template_id}/status", response_model=OCRMappingTemplate)
async def patch_ocr_mapping_template_status(
    template_id: str,
    request: UpdateOCRRuleRequest,
) -> OCRMappingTemplate:
    try:
        return set_ocr_mapping_template_status(template_id, is_active=request.is_active)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ocr-mapping-templates/{template_id}/rollback", response_model=OCRMappingTemplate)
async def post_ocr_mapping_template_rollback(template_id: str) -> OCRMappingTemplate:
    try:
        return rollback_ocr_mapping_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ocr-mapping-templates/{template_id}/compare", response_model=OCRRuleVersionDiff)
async def get_ocr_mapping_template_compare(template_id: str) -> OCRRuleVersionDiff:
    try:
        return compare_ocr_mapping_template_versions(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/template-seed/{session_id}/{variant_key}")
async def get_template_seed(session_id: str, variant_key: str):
    try:
        statement = load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    base_variant = next((variant for variant in build_variants(statement) if variant.key == variant_key), None)
    if base_variant is None:
        raise HTTPException(status_code=404, detail="Базовый вариант не найден.")

    return {
        "session_id": session_id,
        "variant_key": variant_key,
        "columns": build_template_seed(base_variant),
    }


@router.get("/onboarding/projects", response_model=list[OnboardingProject])
async def get_onboarding_projects() -> list[OnboardingProject]:
    return list_onboarding_projects()


@router.post("/onboarding/projects", response_model=OnboardingProject)
async def post_onboarding_project(request: CreateOnboardingProjectRequest) -> OnboardingProject:
    return create_onboarding_project(request)


@router.get("/onboarding/projects/{project_id}", response_model=OnboardingProject)
async def get_onboarding_project_details(project_id: str) -> OnboardingProject:
    try:
        return get_onboarding_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/onboarding/projects/{project_id}/samples", response_model=OnboardingProject)
async def post_onboarding_sample(
    project_id: str,
    request: AddOnboardingSampleRequest,
) -> OnboardingProject:
    try:
        add_onboarding_sample(project_id, request)
        return get_onboarding_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _build_preview_response(
    session_id: str,
    statement,
    preference: PreferenceRecord | None,
    parser_matches: list[ParserMatch],
    applied_rule: AppliedRuleInfo | None = None,
) -> PreviewResponse:
    quality_summary, row_diagnostics = analyze_statement_quality(statement)
    base_variants = build_variants(statement)
    templates = list_templates(statement.metadata.parser_key)
    base_lookup = {variant.key: variant for variant in base_variants}
    saved_variants = [
        apply_template_to_variant(base_lookup[template.base_variant_key], template)
        for template in templates
        if template.base_variant_key in base_lookup
    ]
    default_template = next((template for template in templates if template.is_default), None)
    default_variant_key = f"template::{default_template.template_id}" if default_template else None

    return PreviewResponse(
        session_id=session_id,
        document=statement.metadata,
        parser_matches=parser_matches,
        applied_rule=applied_rule,
        quality_summary=quality_summary,
        row_diagnostics=row_diagnostics,
        ocr_review=None,
        variants=base_variants,
        saved_variants=saved_variants,
        templates=templates,
        preference=preference,
        default_variant_key=default_variant_key,
        ai_insights=statement.ai_insights,
    )


def _build_ocr_review_preview(filename: str, content: bytes) -> PreviewResponse | None:
    try:
        review = create_ocr_review_session(filename, content)
    except Exception:
        return None

    best_match = find_best_ocr_mapping_match(review)
    if best_match is not None:
        template = get_ocr_mapping_template(best_match.template_id)
        if template is not None:
            try:
                statement = materialize_ocr_review(
                    review.review_id,
                    MaterializeOCRReviewRequest(
                        table_index=best_match.table_index,
                        header_row_index=best_match.header_row_index,
                        title=review.source_filename,
                        column_mapping=template.column_mapping,
                    ),
                )
                session_id = save_session(statement)
                preference = get_preference(statement.metadata.parser_key)
                return _build_preview_response(
                    session_id,
                    statement,
                    preference,
                    [
                        ParserMatch(
                            key=statement.metadata.parser_key,
                            label=f"OCR Auto Mapping · {template.name}",
                            score=best_match.score,
                            matched=True,
                        )
                    ],
                    AppliedRuleInfo(
                        rule_type="ocr_mapping_template",
                        template_id=template.template_id,
                        name=template.name,
                        version=template.version,
                        score=best_match.score,
                        reason=_build_rule_reason(best_match),
                        header_score=best_match.header_score,
                        title_score=best_match.title_score,
                        matched_header_signature=best_match.matched_header_signature,
                        matched_title_keywords=best_match.matched_title_keywords,
                    ),
                )
            except Exception:
                pass

    return PreviewResponse(
        session_id="",
        document={
            "source_filename": filename,
            "title": filename,
            "parser_key": "ocr_raw_review",
            "account_holder": None,
            "card_number": None,
            "account_number": None,
            "currency": None,
            "period_start": None,
            "period_end": None,
            "opening_balance": None,
            "closing_balance": None,
            "transaction_count": 0,
            "totals": {
                "income_total": 0.0,
                "expense_total": 0.0,
                "purchase_total": 0.0,
                "transfer_total": 0.0,
                "topup_total": 0.0,
                "cash_withdrawal_total": 0.0,
            },
        },
        parser_matches=[],
        applied_rule=None,
        quality_summary={"overall_confidence": 0.0},
        row_diagnostics=[],
        ocr_review=review,
        variants=[],
        saved_variants=[],
        templates=[],
        preference=None,
        default_variant_key=None,
    )


def _build_rule_reason(best_match: Any) -> str:
    reasons: list[str] = []
    if getattr(best_match, "matched_header_signature", None):
        reasons.append(f"header matched: {', '.join(best_match.matched_header_signature[:4])}")
    if getattr(best_match, "matched_title_keywords", None):
        reasons.append(f"title matched: {', '.join(best_match.matched_title_keywords[:4])}")
    if not reasons:
        reasons.append("best available OCR template match")
    return " | ".join(reasons)
