# -*- coding: utf-8 -*-
"""
Search tools for the Jeonse Guarantee Advisory Agent.

이 파일은 Gemini Enterprise Data Store 검색 Tool을 담습니다.

분리 목적:
- 기존 root_agent와 향후 JeonseOrchestrator가 같은 검색 함수를 재사용할 수 있게 합니다.
- agent.py가 너무 커지는 것을 막습니다.
- Tool은 외부 검색/API 호출 성격이므로 sub-agent가 아니라 별도 tool 모듈로 유지합니다.
"""

from .ge_search import search_gemini_enterprise


def _short_doc(doc: dict) -> dict:
    """충돌 분석에 필요한 최소 문서 정보만 추립니다."""
    return {
        "title": doc.get("title", ""),
        "document_type": doc.get("document_type", "unknown"),
        "effective_date_candidate": doc.get("effective_date_candidate", ""),
        "date_confidence": doc.get("date_confidence", "none"),
        "link": doc.get("link", ""),
        "evidence": (doc.get("evidence", "") or "")[:250],
    }


def _build_policy_conflict_analysis(docs_by_type: dict) -> dict:
    """
    외규 / 내규 / Q&A 검색 결과 조합을 보고 규정 충돌 가능성을 구조화합니다.

    v0.2에서는 의미상 충돌을 확정 판정하지 않습니다.
    대신 어떤 유형의 문서가 함께 검색되었는지에 따라 상담원이 확인해야 할 우선순위를 제공합니다.
    """
    external_docs = docs_by_type.get("external_regulation", [])
    internal_docs = docs_by_type.get("internal_policy", [])
    qa_docs = docs_by_type.get("qa", [])
    unknown_docs = docs_by_type.get("unknown", [])

    has_external = len(external_docs) > 0
    has_internal = len(internal_docs) > 0
    has_qa = len(qa_docs) > 0
    has_any = has_external or has_internal or has_qa or len(unknown_docs) > 0

    source_priority = [
        "internal_policy",
        "external_regulation",
        "qa",
    ]

    conflict_candidates = []
    recommended_handling = []
    rules_applied = []

    if not has_any:
        return {
            "risk_level": "high",
            "source_priority": source_priority,
            "rules_applied": ["no_search_results"],
            "conflict_candidates": [
                {
                    "type": "no_evidence",
                    "summary": "검색 결과가 없어 문서 기반 판단을 할 수 없습니다.",
                    "involved_document_types": [],
                    "handling": "상담원 또는 담당 부서의 추가 확인이 필요합니다.",
                }
            ],
            "recommended_handling": [
                "문서 근거가 없으므로 가능 여부를 확정하지 않습니다.",
                "관련 외규, 내규, Q&A 문서를 추가 확인합니다.",
            ],
            "confidence_note": "검색 결과가 없습니다. 상담원 추가 확인이 필요합니다.",
        }

    if has_internal:
        rules_applied.append("internal_policy_found")
        recommended_handling.append(
            "은행 내규가 검색된 경우, 외규나 Q&A보다 내규의 제한 조건을 우선 확인합니다."
        )

    if has_external:
        rules_applied.append("external_regulation_found")
        recommended_handling.append(
            "외규는 보증기관 또는 정책 기준으로 참고하되, 은행 내부 취급 기준과 함께 확인합니다."
        )

    if has_qa:
        rules_applied.append("qa_found")
        recommended_handling.append(
            "Q&A는 상담 참고자료로 사용하되, 외규 또는 내규와 충돌하는 경우 단독 최종 근거로 사용하지 않습니다."
        )

    if has_external and has_internal:
        conflict_candidates.append(
            {
                "type": "external_vs_internal",
                "summary": "외규와 내규가 모두 검색되었습니다. 외규상 가능하더라도 내규상 제한이 있을 수 있습니다.",
                "involved_document_types": ["external_regulation", "internal_policy"],
                "external_examples": [_short_doc(doc) for doc in external_docs[:2]],
                "internal_examples": [_short_doc(doc) for doc in internal_docs[:2]],
                "handling": "내규 제한 조건을 우선 확인하고, 고객에게는 최종 가능 여부를 확정하지 않습니다.",
            }
        )

    if has_qa and has_internal:
        conflict_candidates.append(
            {
                "type": "qa_vs_internal",
                "summary": "Q&A와 내규가 함께 검색되었습니다. Q&A가 내규보다 최신이거나 구체적으로 보여도 내규 제한 조건을 우선 확인해야 합니다.",
                "involved_document_types": ["qa", "internal_policy"],
                "qa_examples": [_short_doc(doc) for doc in qa_docs[:2]],
                "internal_examples": [_short_doc(doc) for doc in internal_docs[:2]],
                "handling": "Q&A는 상담 참고자료로 표시하고, 내규 확인 필요 문구를 포함합니다.",
            }
        )

    if has_qa and has_external and not has_internal:
        conflict_candidates.append(
            {
                "type": "qa_vs_external_without_internal",
                "summary": "Q&A와 외규는 검색되었으나 내규가 검색되지 않았습니다. 외규와 Q&A만으로 은행의 최종 취급 가능 여부를 확정하기 어렵습니다.",
                "involved_document_types": ["qa", "external_regulation"],
                "qa_examples": [_short_doc(doc) for doc in qa_docs[:2]],
                "external_examples": [_short_doc(doc) for doc in external_docs[:2]],
                "handling": "외규와 Q&A를 참고하되, 은행 내부 취급 기준 확인 필요를 표시합니다.",
            }
        )

    if has_external and not has_internal:
        rules_applied.append("internal_policy_missing")
        recommended_handling.append(
            "내규가 검색되지 않은 경우, 외규 문서가 있더라도 은행 내부 취급 가능 여부는 별도 확인이 필요합니다."
        )

    if has_internal and has_external:
        risk_level = "high"
        confidence_note = "외규와 내규가 함께 검색되었습니다. 내규 제한 조건을 우선 확인해야 합니다."
    elif has_internal:
        risk_level = "medium"
        confidence_note = "내규 문서가 검색되었습니다. 상담 답변 시 내규 기준을 우선 확인해야 합니다."
    elif has_external and has_qa:
        risk_level = "medium"
        confidence_note = "외규와 Q&A는 검색되었으나 내규 문서가 함께 검색되지 않았습니다. 은행 내부 취급 기준 확인이 필요합니다."
    elif has_external:
        risk_level = "medium"
        confidence_note = "외규 문서는 검색되었으나 내규 문서가 함께 검색되지 않았습니다. 은행 내부 취급 기준 확인이 필요합니다."
    elif has_qa:
        risk_level = "medium"
        confidence_note = "Q&A 문서 중심으로 검색되었습니다. 외규/내규 추가 확인이 필요합니다."
    else:
        risk_level = "low"
        confidence_note = "기타 문서가 검색되었습니다. 문서 유형 확인이 필요합니다."

    return {
        "risk_level": risk_level,
        "source_priority": source_priority,
        "rules_applied": rules_applied,
        "conflict_candidates": conflict_candidates,
        "recommended_handling": recommended_handling,
        "confidence_note": confidence_note,
    }


# 기능2 : 질문 정규화
def search_regulation_documents(question: str) -> dict:
    """
    Gemini Enterprise App에 연결된 Data Store에서 관련 문서를 검색하고,
    상담 Agent가 사용하기 쉬운 형태로 검색 결과를 정리합니다.

    v0.2 구현에서는 최신성 판단과 충돌 후보 판단을 별도 Tool로 분리하지 않고,
    이 검색 Tool 내부에서 우선 처리합니다.
    """
    search_response = search_gemini_enterprise(question, page_size=5)
    raw_results = search_response.get("results", [])

    compact_results = []
    docs_by_type = {
        "external_regulation": [],
        "internal_policy": [],
        "qa": [],
        "unknown": [],
    }

    for result in raw_results:
        doc_type = result.get("document_type", "unknown")
        title = result.get("title", "")
        link = result.get("link", "")
        effective_date = result.get("effective_date_candidate", "")
        relevance_score = result.get("relevance_score")

        # ge_search.py에서 이미 evidence를 정리해서 넘겨주므로 이것을 우선 사용합니다.
        evidence_text = result.get("evidence", "") or ""

        # fallback: 혹시 evidence가 비어 있으면 snippets / extractive_answers를 보조로 사용합니다.
        if not evidence_text:
            snippets = result.get("snippets", []) or []
            extractive_answers = result.get("extractive_answers", []) or []

            if extractive_answers:
                evidence_text = extractive_answers[0]
            elif snippets:
                evidence_text = snippets[0]

        # 너무 긴 근거 문장은 Agent 함수 호출 안정성을 위해 자릅니다.
        evidence_text = evidence_text[:500] if evidence_text else ""

        compact_doc = {
            "document_type": doc_type,
            "title": title,
            "link": link,
            "effective_date_candidate": effective_date,
            "effective_date_source": result.get("effective_date_source", "none"),
            "date_confidence": result.get("date_confidence", "none"),
            "freshness_basis": result.get("freshness_basis", "no_date_found"),
            "date_candidates": result.get("date_candidates", []),
            "freshness_warning": result.get("freshness_warning", ""),
            "relevance_score": relevance_score,
            "evidence": evidence_text,
        }

        compact_results.append(compact_doc)

        if doc_type in docs_by_type:
            docs_by_type[doc_type].append(compact_doc)
        else:
            docs_by_type["unknown"].append(compact_doc)

    # 문서 유형별 최신 날짜 후보 정리
    latest_candidates = {}

    for doc_type, docs in docs_by_type.items():
        dated_docs = [
            doc for doc in docs
            if doc.get("effective_date_candidate")
        ]

        if dated_docs:
            latest_doc = sorted(
                dated_docs,
                key=lambda x: x.get("effective_date_candidate", ""),
                reverse=True,
            )[0]

            latest_candidates[doc_type] = {
                "title": latest_doc.get("title", ""),
                "effective_date_candidate": latest_doc.get("effective_date_candidate", ""),
                "effective_date_source": latest_doc.get("effective_date_source", "none"),
                "date_confidence": latest_doc.get("date_confidence", "none"),
                "freshness_basis": latest_doc.get("freshness_basis", "no_date_found"),
                "freshness_warning": latest_doc.get("freshness_warning", ""),
                "link": latest_doc.get("link", ""),
            }


    policy_conflict_analysis = _build_policy_conflict_analysis(docs_by_type)

    conflict_candidates = [
        candidate.get("summary", "")
        for candidate in policy_conflict_analysis.get("conflict_candidates", [])
        if candidate.get("summary")
    ]

    confidence_note = policy_conflict_analysis.get(
        "confidence_note",
        "상담원 추가 확인이 필요합니다.",
    )


    # 충돌 가능성 간단 판단 0.1
    # has_external = len(docs_by_type["external_regulation"]) > 0
    # has_internal = len(docs_by_type["internal_policy"]) > 0
    # has_qa = len(docs_by_type["qa"]) > 0

    # conflict_candidates = []

    # if has_external and has_internal:
    #     conflict_candidates.append(
    #         "외규와 내규가 모두 검색되었습니다. 외규상 가능하더라도 내규상 제한이 있을 수 있으므로 내규 확인이 필요합니다."
    #     )

    # if has_qa and (has_external or has_internal):
    #     conflict_candidates.append(
    #         "Q&A 문서는 상담 참고자료로 사용하고, 외규 또는 내규와 충돌하는 경우 최종 판단 근거로 단독 사용하지 않는 것이 안전합니다."
    #     )

    # if not compact_results:
    #     confidence_note = "검색 결과가 없습니다. 상담원 추가 확인이 필요합니다."
    # elif has_internal:
    #     confidence_note = "내규 문서가 검색 결과에 포함되어 있어 상담 답변 시 내규 확인 항목을 반드시 포함해야 합니다."
    # elif has_external:
    #     confidence_note = "외규 문서는 검색되었으나 내규 문서가 함께 검색되지 않았습니다. 은행 내부 취급 기준 확인이 필요합니다."
    # else:
    #     confidence_note = "Q&A 또는 기타 문서 중심으로 검색되었습니다. 외규/내규 추가 확인이 필요합니다."

    return {
        "query": question,
        "search_source": "gemini_enterprise_app_search_api",
        "app_id": "app-banking-advisory-app",
        "result_count": len(compact_results),
        "document_type_counts": {
            "external_regulation": len(docs_by_type["external_regulation"]),
            "internal_policy": len(docs_by_type["internal_policy"]),
            "qa": len(docs_by_type["qa"]),
            "unknown": len(docs_by_type["unknown"]),
        },
        "latest_candidates": latest_candidates,
        "conflict_candidates": conflict_candidates,
        "confidence_note": confidence_note,
        "results": compact_results,
        "policy_conflict_analysis": policy_conflict_analysis,
    }
