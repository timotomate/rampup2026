import re

from google.adk.agents import Agent
from .ge_search import search_gemini_enterprise

from .prompts import ROOT_AGENT_INSTRUCTION

from .audit_logger import (
    before_model_capture_question,
    after_tool_capture_search,
    after_model_log_qa,
)


# 기능1 : 질문 유형 분류(이 부분 추후 고도화 필요)
# ver0.2
def classify_consultation_question(question: str) -> dict:
    """
    전세보증 / 전세자금대출 상담 질문을 업무 처리 방식 기준으로 분류합니다.

    이 함수는 특정 테스트 질문에 맞춘 분류기가 아니라,
    전세 상담 업무에서 자주 등장하는 질문 유형을 범용적으로 분류하기 위한 rule-based classifier입니다.

    분류 목적:
    - Agent가 어떤 방식으로 답변해야 하는지 결정합니다.
    - 규정 조회형 / 사례 판단형 / 한도 계산형 / 서류 안내형 / 최신성 확인형 / 규정 충돌형을 구분합니다.
    - 최종 승인/가입 확정 금지와, 근거가 명확한 경우의 현재 기준 판단을 분리합니다.
    """
    q = question.strip()
    q_no_space = re.sub(r"\s+", "", q)

    entities = {}
    secondary_types = []
    risk_flags = ["final_approval_not_allowed"]
    required_checks = []

    # -----------------------------
    # 1. 금액 정보 추출
    # -----------------------------
    amounts = re.findall(r"(\d+(?:\.\d+)?)\s*억", q)
    if amounts:
        entities["amounts_mentioned"] = [f"{amount}억원" for amount in amounts]

        if any(keyword in q for keyword in ["대출", "대출금", "요청", "실행", "받고", "빌리"]):
            entities["requested_loan_amount_candidate"] = f"{amounts[-1]}억원"

        if any(keyword in q for keyword in ["전세계약", "임대차계약", "보증금", "전세금"]):
            entities["lease_deposit_or_contract_amount_candidate"] = f"{amounts[0]}억원"

    # -----------------------------
    # 2. 차주 / 임대인 / 주택 / 지역 조건 추출
    # -----------------------------
    if re.search(r"무주택", q):
        entities["home_count"] = "무주택자"
    elif re.search(r"1\s*주택|일\s*주택|1주택자|한\s*채", q):
        entities["home_count"] = "1주택자"
    elif re.search(r"2\s*주택|이\s*주택|2주택자|두\s*채", q):
        entities["home_count"] = "2주택자"
    elif re.search(r"다주택|3\s*주택|세\s*채|복수\s*주택", q):
        entities["home_count"] = "다주택자"

    if any(keyword in q for keyword in ["수도권", "서울", "경기", "인천"]):
        entities["region"] = "수도권"
    if any(keyword in q for keyword in ["규제지역", "투기과열", "조정대상"]):
        entities["regulation_area"] = "규제지역 관련"
    if any(keyword in q for keyword in ["비규제", "투기과열지구 외", "규제지역 외"]):
        entities["regulation_area"] = "비규제지역 또는 규제지역 외"

    if "임대인" in q:
        entities["party"] = "임대인"
    if "임차인" in q or "차주" in q or "고객" in q:
        entities["borrower_context_present"] = True

    if "외국인" in q:
        entities["special_party_condition"] = "외국인 관련"
    if "법인" in q:
        entities["special_party_condition"] = "법인 관련"
    if "재외국민" in q or "거소" in q:
        entities["special_party_condition"] = "재외국민/거소 관련"

    # -----------------------------
    # 3. 상품 / 기관 범위 추출
    # -----------------------------
    agencies = []
    if "HUG" in q or "주택도시보증" in q:
        agencies.append("HUG")
    if "HF" in q or "주택금융공사" in q:
        agencies.append("HF")
    if "SGI" in q or "서울보증" in q:
        agencies.append("SGI")
    if agencies:
        entities["guarantee_agencies"] = agencies

    product_scope = []
    if any(keyword in q for keyword in ["전세대출", "전세자금대출", "대출 실행", "대출"]):
        product_scope.append("전세자금대출")
    if any(keyword in q for keyword in ["보증보험", "반환보증", "전세보증", "전세금보장", "보증 가입"]):
        product_scope.append("전세보증/보증보험")
    if product_scope:
        entities["product_scope"] = product_scope

    # -----------------------------
    # 4. 질문의 업무 처리 축 분류
    # -----------------------------
    if any(keyword in q for keyword in ["한도", "최대", "금액", "얼마", "몇 억", "대출금", "보증금액"]):
        secondary_types.append("limit_or_amount_check")

    if any(keyword in q for keyword in ["가능", "불가", "되나요", "가능한가요", "가입", "실행", "승인", "취급"]):
        secondary_types.append("eligibility_or_execution_check")

    if any(keyword in q for keyword in ["서류", "제출", "준비", "증빙", "필요서류", "등기부", "계약서", "확인서"]):
        secondary_types.append("document_requirement")

    if any(keyword in q for keyword in ["절차", "프로세스", "어떻게", "순서", "신청 방법", "진행 방법"]):
        secondary_types.append("process_guidance")

    if any(keyword in q for keyword in ["최신", "개정", "시행", "기준일", "현재 기준", "과거", "2024", "2025", "2026"]):
        secondary_types.append("freshness_check")

    if any(keyword in q for keyword in ["외규", "내규", "규정", "약관", "업무지침", "상품요약서", "기준상"]):
        secondary_types.append("rule_lookup")

    if any(keyword in q for keyword in ["충돌", "상충", "다르면", "우선", "어느 기준", "무엇을 따라"]):
        secondary_types.append("policy_conflict_check")

    if any(keyword in q for keyword in ["외국인", "법인", "다주택", "2주택", "재외국민", "예외", "특례", "임대인 조건"]):
        secondary_types.append("exception_condition")

    # 중복 제거
    secondary_types = list(dict.fromkeys(secondary_types))

    # -----------------------------
    # 5. primary_type 결정
    # -----------------------------
    has_case_context = any(
        keyword in q
        for keyword in [
            "차주", "고객", "현재", "경우", "상황", "보유", "요청",
            "계약", "물건", "소득", "주택자", "임대인", "임차인"
        ]
    )

    if "policy_conflict_check" in secondary_types:
        primary_type = "policy_conflict"
    elif "freshness_check" in secondary_types and not has_case_context:
        primary_type = "freshness_check"
    elif has_case_context and (
        "eligibility_or_execution_check" in secondary_types
        or "limit_or_amount_check" in secondary_types
        or "exception_condition" in secondary_types
    ):
        primary_type = "scenario_judgment"
    elif "document_requirement" in secondary_types:
        primary_type = "document_requirement"
    elif "process_guidance" in secondary_types:
        primary_type = "process_guidance"
    elif "rule_lookup" in secondary_types or "limit_or_amount_check" in secondary_types:
        primary_type = "regulation_lookup"
    elif "exception_condition" in secondary_types:
        primary_type = "exception_condition"
    else:
        primary_type = "general_consultation"

    # -----------------------------
    # 6. 답변 모드 결정
    # -----------------------------
    if primary_type == "scenario_judgment":
        answer_mode = "case_based_answer_clear_if_evidence_exists"
        response_policy = (
            "고객 상황을 기준으로 답변합니다. 근거에 금액, 한도, 가능/불가 조건이 명확하면 "
            "'현재 검색된 기준상'이라는 표현으로 결론을 제시하되, 최종 승인/가입 확정은 하지 않습니다."
        )
    elif primary_type == "regulation_lookup":
        answer_mode = "rule_based_summary"
        response_policy = (
            "특정 규정 또는 상품 기준을 요약합니다. 문서명, 기준일, evidence를 함께 제시합니다."
        )
    elif primary_type == "document_requirement":
        answer_mode = "checklist_answer"
        response_policy = (
            "필요 서류와 확인 항목을 체크리스트 형태로 제시합니다."
        )
    elif primary_type == "freshness_check":
        answer_mode = "latest_document_priority"
        response_policy = (
            "기준일, 시행일, 개정일이 더 최신인 문서를 우선합니다."
        )
    elif primary_type == "policy_conflict":
        answer_mode = "source_priority_comparison"
        response_policy = (
            "내규, 외규, Q&A의 우선순위를 비교하고 충돌 가능성을 설명합니다."
        )
    elif primary_type == "process_guidance":
        answer_mode = "procedure_answer"
        response_policy = (
            "상담원이 확인해야 할 절차와 다음 액션을 순서대로 안내합니다."
        )
    else:
        answer_mode = "standard_consultation_draft"
        response_policy = (
            "일반 상담 초안 형식으로 답변합니다."
        )

    # -----------------------------
    # 7. 리스크 플래그 / 추가 확인 항목
    # -----------------------------
    if "eligibility_or_execution_check" in secondary_types:
        risk_flags.append("do_not_confirm_final_execution")
        required_checks.append("최종 대출 실행 여부는 은행 심사 결과 확인 필요")

    if "limit_or_amount_check" in secondary_types:
        risk_flags.append("amount_or_limit_must_be_clear_if_evidence_exists")
        required_checks.append("검색 근거에 한도 금액이 있으면 답변에 반드시 반영")

    if "document_requirement" in secondary_types:
        required_checks.append("제출 서류 및 확인 서류 목록 확인")

    if "exception_condition" in secondary_types:
        risk_flags.append("exception_condition_review_required")
        required_checks.append("예외 조건에 대한 외규/내규/Q&A 확인")

    if "policy_conflict_check" in secondary_types or "내규" in q:
        risk_flags.append("internal_policy_check_required")
        required_checks.append("외규와 내규가 다를 경우 내규 제한 조건 우선 확인")

    if "guarantee_agencies" in entities:
        required_checks.append("보증기관별 HUG/HF/SGI 세부 기준 확인")

    if "product_scope" in entities and len(entities["product_scope"]) > 1:
        required_checks.append("전세대출 가능 여부와 보증보험 가입 가능 여부를 분리해서 판단")

    # -----------------------------
    # 8. 검색 질의 힌트 생성
    # -----------------------------
    search_focus_terms = []

    if "home_count" in entities:
        search_focus_terms.append(entities["home_count"])
    if "region" in entities:
        search_focus_terms.append(entities["region"])
    if "regulation_area" in entities:
        search_focus_terms.append(entities["regulation_area"])
    if "requested_loan_amount_candidate" in entities:
        search_focus_terms.append(entities["requested_loan_amount_candidate"])
    if "special_party_condition" in entities:
        search_focus_terms.append(entities["special_party_condition"])
    if "product_scope" in entities:
        search_focus_terms.extend(entities["product_scope"])
    if "guarantee_agencies" in entities:
        search_focus_terms.extend(entities["guarantee_agencies"])

    if not search_focus_terms:
        search_focus_terms = [q[:80]]

    # -----------------------------
    # 9. reason 생성
    # -----------------------------
    if primary_type == "scenario_judgment":
        reason = "고객의 구체 조건과 가능 여부 또는 한도 판단이 포함된 사례형 질문으로 분류했습니다."
    elif primary_type == "regulation_lookup":
        reason = "특정 규정, 상품 기준 또는 한도 기준을 조회하는 규정형 질문으로 분류했습니다."
    elif primary_type == "document_requirement":
        reason = "상담원이 확인해야 할 제출 서류 또는 증빙 항목을 묻는 질문으로 분류했습니다."
    elif primary_type == "freshness_check":
        reason = "문서의 최신 기준, 개정일, 시행일 비교가 필요한 질문으로 분류했습니다."
    elif primary_type == "policy_conflict":
        reason = "외규, 내규, Q&A 간 충돌 또는 우선순위 판단이 필요한 질문으로 분류했습니다."
    elif primary_type == "process_guidance":
        reason = "상담 절차 또는 진행 순서를 안내해야 하는 질문으로 분류했습니다."
    else:
        reason = "일반 전세보증 상담 질문으로 분류했습니다."

    return {
        "primary_type": primary_type,
        "secondary_types": secondary_types,
        "entities": entities,
        "answer_mode": answer_mode,
        "response_policy": response_policy,
        "needs_search": True,
        "search_focus_terms": list(dict.fromkeys(search_focus_terms)),
        "required_checks": list(dict.fromkeys(required_checks)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "reason": reason,
        "classification_policy": "rule_based_jeonse_consultation_classifier_v0.3",
    }

# ver0.1
# def classify_consultation_question(question: str) -> dict:
#     """
#     전세보증 상담 질문을 업무 처리 방식 기준으로 분류합니다.

#     v0.2에서는 학습 모델 기반 분류가 아니라 rule-based 분류를 사용합니다.
#     목적은 질문을 완벽하게 분류하는 것이 아니라,
#     Agent가 답변 강도와 검색/검토 방향을 정하는 데 필요한 힌트를 제공하는 것입니다.
#     """
#     q = question.strip()
#     q_lower = q.lower()

#     secondary_types = []
#     risk_flags = []
#     entities = {}

#     # -----------------------------
#     # 1. 주요 엔티티 추출
#     # -----------------------------
#     home_count_patterns = [
#         ("무주택자", r"무주택"),
#         ("1주택자", r"1\s*주택|일\s*주택|한\s*채|1주택자"),
#         ("2주택자", r"2\s*주택|두\s*채|2주택자"),
#         ("다주택자", r"다주택|3\s*주택|세\s*채|복수\s*주택"),
#     ]

#     for label, pattern in home_count_patterns:
#         if re.search(pattern, q):
#             entities["home_count"] = label
#             break

#     if any(keyword in q for keyword in ["수도권", "규제지역", "투기과열", "조정대상", "비규제", "대전", "서울", "경기", "인천"]):
#         if "수도권" in q and "규제" in q:
#             entities["region"] = "수도권 또는 규제지역"
#         elif "투기과열" in q:
#             entities["region"] = "투기과열지구 관련"
#         elif "비규제" in q or "투기과열지구 외" in q:
#             entities["region"] = "비규제지역 또는 투기과열지구 외"
#         else:
#             entities["region"] = "지역 조건 포함"

#     amount_match = re.search(r"(\d+(?:\.\d+)?)\s*억", q)
#     if amount_match:
#         entities["requested_amount"] = f"{amount_match.group(1)}억원"

#     if "외국인" in q:
#         entities["lessor_or_party_condition"] = "외국인 관련"

#     if "임대인" in q:
#         entities["party"] = "임대인"

#     if "임차인" in q or "차주" in q or "고객" in q:
#         entities["borrower_context_present"] = True

#     if any(keyword in q for keyword in ["HUG", "HF", "SGI", "주택도시보증", "주택금융공사", "서울보증"]):
#         agencies = []
#         if "HUG" in q or "주택도시보증" in q:
#             agencies.append("HUG")
#         if "HF" in q or "주택금융공사" in q:
#             agencies.append("HF")
#         if "SGI" in q or "서울보증" in q:
#             agencies.append("SGI")
#         entities["guarantee_agencies"] = agencies or ["보증기관"]

#     # -----------------------------
#     # 2. secondary type 판정
#     # -----------------------------
#     if any(keyword in q for keyword in ["한도", "최대", "금액", "얼마", "몇 억", "대출금", "3억원", "2억원"]):
#         secondary_types.append("loan_limit_check")

#     if any(keyword in q for keyword in ["가입", "가능", "불가", "되나요", "가능한가요", "실행", "승인"]):
#         secondary_types.append("eligibility_check")

#     if any(keyword in q for keyword in ["보증보험", "전세보증", "보증 가입", "반환보증", "전세금보장"]):
#         secondary_types.append("guarantee_eligibility")

#     if any(keyword in q for keyword in ["전세대출", "전세자금대출", "대출 실행", "대출"]):
#         secondary_types.append("loan_execution")

#     if any(keyword in q for keyword in ["서류", "제출", "준비", "필요서류", "증빙", "등기부", "계약서"]):
#         secondary_types.append("document_requirement")

#     if any(keyword in q for keyword in ["최신", "개정", "시행", "기준일", "2024", "2025", "2026", "과거", "현재 기준"]):
#         secondary_types.append("freshness_check")

#     if any(keyword in q for keyword in ["내규", "외규", "충돌", "다르면", "우선", "상충", "규정상", "기준상"]):
#         secondary_types.append("policy_conflict_check")

#     if any(keyword in q for keyword in ["외국인", "임대인", "다주택", "2주택", "법인", "예외", "특례", "거소", "재외국민"]):
#         secondary_types.append("exception_condition")

#     # 중복 제거
#     secondary_types = list(dict.fromkeys(secondary_types))

#     # -----------------------------
#     # 3. primary type 판정
#     # -----------------------------
#     scenario_markers = [
#         "차주", "고객", "현재", "경우", "상황", "보유", "요청", "계약", "물건", "소득", "주택자",
#     ]

#     regulation_markers = [
#         "기준", "규정", "외규", "내규", "상품요약서", "약관", "업무지침", "최대 한도", "한도는 얼마",
#     ]

#     if "policy_conflict_check" in secondary_types and any(keyword in q for keyword in ["충돌", "다르면", "우선", "상충"]):
#         primary_type = "policy_conflict"
#     elif "freshness_check" in secondary_types and any(keyword in q for keyword in ["최신", "개정", "2025", "2026", "과거"]):
#         primary_type = "freshness_check"
#     elif any(marker in q for marker in scenario_markers) and (
#         "eligibility_check" in secondary_types
#         or "loan_limit_check" in secondary_types
#         or "loan_execution" in secondary_types
#         or "guarantee_eligibility" in secondary_types
#     ):
#         primary_type = "scenario_judgment"
#     elif "document_requirement" in secondary_types:
#         primary_type = "document_requirement"
#     elif any(marker in q for marker in regulation_markers):
#         primary_type = "regulation_lookup"
#     elif "exception_condition" in secondary_types:
#         primary_type = "exception_condition"
#     else:
#         primary_type = "general_consultation"

#     # -----------------------------
#     # 4. 답변 모드 결정
#     # -----------------------------
#     if primary_type == "scenario_judgment" and (
#         "loan_limit_check" in secondary_types
#         or "eligibility_check" in secondary_types
#     ):
#         answer_mode = "clear_if_evidence_exists"
#         reason = "차주 조건과 대출/보증 가능 여부 또는 한도 판단이 포함된 사례형 질문입니다."
#     elif primary_type == "regulation_lookup":
#         answer_mode = "cite_rule_and_summarize"
#         reason = "특정 규정, 한도, 상품 기준을 조회하는 규정형 질문입니다."
#     elif primary_type == "document_requirement":
#         answer_mode = "list_required_documents"
#         reason = "제출 서류 또는 확인 절차를 묻는 질문입니다."
#     elif primary_type == "freshness_check":
#         answer_mode = "prioritize_latest_document"
#         reason = "문서 기준일, 개정일, 최신 기준 확인이 필요한 질문입니다."
#     elif primary_type == "policy_conflict":
#         answer_mode = "compare_sources_and_warn"
#         reason = "외규, 내규, Q&A 간 우선순위 또는 충돌 가능성을 확인해야 하는 질문입니다."
#     else:
#         answer_mode = "standard_consultation_draft"
#         reason = "일반 상담 질문으로 분류했습니다."

#     # -----------------------------
#     # 5. 리스크 플래그
#     # -----------------------------
#     risk_flags.append("final_approval_not_allowed")

#     if "eligibility_check" in secondary_types or "loan_execution" in secondary_types:
#         risk_flags.append("do_not_confirm_final_execution")

#     if "policy_conflict_check" in secondary_types or "내규" in q:
#         risk_flags.append("internal_policy_check_required")

#     if "loan_limit_check" in secondary_types:
#         risk_flags.append("amount_or_limit_must_be_clear_if_evidence_exists")

#     if "guarantee_eligibility" in secondary_types:
#         risk_flags.append("guarantee_review_required")

#     # -----------------------------
#     # 6. 검색 필요 여부
#     # -----------------------------
#     needs_search = True

#     return {
#         "primary_type": primary_type,
#         "secondary_types": secondary_types,
#         "entities": entities,
#         "answer_mode": answer_mode,
#         "needs_search": needs_search,
#         "risk_flags": list(dict.fromkeys(risk_flags)),
#         "reason": reason,
#         "classification_policy": "rule_based_demo_classifier_v0.2",
#     }


# helper 함수
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


# 기능 3 : 문서 최신성 검사
# v0.2에서는 아래 함수들을 tools 목록에 넣지 않습니다.
# 최신성 판단과 충돌 후보 판단은 search_regulation_documents 내부에서 우선 처리합니다.
# 향후 Tool 간 입력 구조를 작게 줄일 수 있으면 별도 Tool로 다시 분리할 수 있습니다. 현재는 분리하지 않았습니다.
def check_document_freshness(search_results: dict) -> dict:
    """검색 결과의 최신성 판단 결과를 반환합니다."""
    return {
        "freshness_policy": "effective_date 기준 최신 문서를 우선합니다.",
        "warning": "문서 본문 기준일이 불명확한 경우 GCS 업로드일은 보조 기준으로만 사용합니다.",
    }

# 기능 4 : 데이터 간 충돌시 처리 방안
def resolve_policy_conflict(search_results: dict) -> dict:
    """외규와 내규 간 충돌 여부를 판단합니다."""
    return {
        "has_conflict": True,
        "conflict_summary": "외규상 가능성이 배제되지 않더라도, 내규상 제한 조건이 있으면 상담원 추가 확인이 필요합니다.",
        "priority": "내규 또는 심사 기준 확인 우선",
    }


root_agent = Agent(
    name="jeonse_guarantee_agent",
    model="gemini-2.5-flash",
    description="전세보증 상담원, 행원을 보조하는 ADK 기반 Agent입니다.",
    before_model_callback=before_model_capture_question,
    after_tool_callback=after_tool_capture_search,
    after_model_callback=after_model_log_qa,
    instruction=ROOT_AGENT_INSTRUCTION, tools=[
        classify_consultation_question,
        search_regulation_documents,
    ],
)