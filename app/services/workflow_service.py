from __future__ import annotations

from app.schemas.statement import AppliedRuleInfo, MaterializeOCRReviewRequest, ParserMatch
from app.services.document_service import DocumentParseError, parse_statement_with_diagnostics
from app.services.job_service import mark_job_completed
from app.services.ocr_mapping_template_service import (
    find_best_ocr_mapping_match,
    get_ocr_mapping_template,
)
from app.services.ocr_review_service import create_ocr_review_session, materialize_ocr_review
from app.services.session_service import save_session


def process_preview_workflow(filename: str, content: bytes) -> dict:
    try:
        statement, parser_matches = parse_statement_with_diagnostics(filename, content)
        session_id = save_session(statement)
        return {
            "kind": "session",
            "session_id": session_id,
            "parser_key": statement.metadata.parser_key,
            "parser_matches": [item.model_dump(mode="json") for item in parser_matches],
        }
    except DocumentParseError:
        return process_ocr_review_workflow(filename, content)


def process_ocr_review_workflow(filename: str, content: bytes) -> dict:
    review = create_ocr_review_session(filename, content)
    best_match = find_best_ocr_mapping_match(review)
    if best_match is None:
        return {
            "kind": "ocr_review",
            "review_id": review.review_id,
            "parser_key": "ocr_raw_review",
        }

    template = get_ocr_mapping_template(best_match.template_id)
    if template is None:
        return {
            "kind": "ocr_review",
            "review_id": review.review_id,
            "parser_key": "ocr_raw_review",
        }

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
    return {
        "kind": "session",
        "session_id": session_id,
        "review_id": review.review_id,
        "parser_key": statement.metadata.parser_key,
        "parser_matches": [
            ParserMatch(
                key=statement.metadata.parser_key,
                label=f"OCR Auto Mapping · {template.name}",
                score=best_match.score,
                matched=True,
            ).model_dump(mode="json")
        ],
        "applied_rule": AppliedRuleInfo(
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
        ).model_dump(mode="json"),
    }


def _build_rule_reason(best_match) -> str:
    reasons: list[str] = []
    if best_match.matched_header_signature:
        reasons.append(f"header matched: {', '.join(best_match.matched_header_signature[:4])}")
    if best_match.matched_title_keywords:
        reasons.append(f"title matched: {', '.join(best_match.matched_title_keywords[:4])}")
    if not reasons:
        reasons.append("best available OCR template match")
    return " | ".join(reasons)
