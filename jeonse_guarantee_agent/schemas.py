# -*- coding: utf-8 -*-
"""
Schema definitions for the Jeonse Guarantee Advisory Agent.

이 파일은 향후 question classifier / evidence reviewer / finalizer sub-agent가
구조화된 데이터를 주고받기 위한 모델 정의를 담습니다.

현재 1차 리팩토링에서는 기존 동작을 깨지 않기 위해 agent.py에서 직접 사용하지 않습니다.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JeonseQuestionClassification(BaseModel):
    """전세보증 상담 질문 분류 결과."""

    primary_type: str = Field(
        default="general_consultation",
        description="질문의 1차 유형. 예: scenario_judgment, regulation_lookup, document_requirement, policy_conflict",
    )
    secondary_types: List[str] = Field(
        default_factory=list,
        description="보조 질문 유형 목록",
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="질문에서 추출한 주요 조건. 예: 주택 수, 지역, 금액, 보증기관, 임대인 조건",
    )
    answer_mode: str = Field(
        default="standard_consultation_draft",
        description="답변 생성 모드",
    )
    needs_search: bool = Field(
        default=True,
        description="Gemini Enterprise Data Store 검색 필요 여부",
    )
    search_focus_terms: List[str] = Field(
        default_factory=list,
        description="검색에 사용할 핵심 키워드",
    )
    required_checks: List[str] = Field(
        default_factory=list,
        description="상담원이 추가로 확인해야 할 항목",
    )
    risk_flags: List[str] = Field(
        default_factory=list,
        description="최종 승인 금지, 내규 확인 필요 등 위험 플래그",
    )
    reason: str = Field(
        default="",
        description="분류 이유",
    )


class EvidenceReviewResult(BaseModel):
    """검색 근거 검토 결과."""

    source_priority: List[str] = Field(
        default_factory=lambda: ["internal_policy", "external_regulation", "qa"],
        description="문서 유형 우선순위",
    )
    risk_level: str = Field(
        default="medium",
        description="근거 충돌 또는 추가 확인 필요 수준",
    )
    conflict_summary: str = Field(
        default="",
        description="외규/내규/Q&A 간 충돌 가능성 요약",
    )
    recommended_handling: List[str] = Field(
        default_factory=list,
        description="상담원이 취해야 할 처리 방향",
    )
    confidence_note: str = Field(
        default="",
        description="근거 신뢰도 및 한계",
    )


class ConsultationDraft(BaseModel):
    """상담원용 최종 답변 초안 구조."""

    consultation_answer: str = Field(
        default="",
        description="[상담 답변 초안]에 해당하는 내용",
    )
    additional_checks: List[str] = Field(
        default_factory=list,
        description="[추가 확인 항목]",
    )
    references: List[str] = Field(
        default_factory=list,
        description="[참고 근거]",
    )
    caution: str = Field(
        default="",
        description="[주의 문구]",
    )
