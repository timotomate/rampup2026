# -*- coding: utf-8 -*-
"""
Sub-agent definitions for the Jeonse Guarantee Advisory Agent.

1차 리팩토링에서는 이 파일을 추가만 하고, 기존 root_agent 동작에는 연결하지 않습니다.
2차 리팩토링에서 JeonseOrchestrator(BaseAgent) 또는 SequentialAgent 구조에 연결합니다.
"""

from google.adk.agents import Agent

from .prompts import (
    QUESTION_CLASSIFIER_INSTRUCTION,
    EVIDENCE_REVIEWER_INSTRUCTION,
    CONSULTATION_FINALIZER_INSTRUCTION,
)
from .schemas import (
    JeonseQuestionClassification,
    EvidenceReviewResult,
    ConsultationDraft,
)


def build_question_classifier_agent() -> Agent:
    """
    질문 분류 sub-agent.

    향후 역할:
    - 전세자금대출 / 전세대출보증 / 전세보증보험 영역 구분
    - 고객 조건 추출
    - 검색 키워드 후보 생성
    - output_key='question_classification'로 session state에 저장
    """
    return Agent(
        name="question_classifier_agent",
        model="gemini-2.5-flash",
        description="전세보증 상담 질문을 구조화하고 검색 방향을 결정하는 sub-agent입니다.",
        instruction=QUESTION_CLASSIFIER_INSTRUCTION,
        output_schema=JeonseQuestionClassification,
        output_key="question_classification",
    )


def build_evidence_reviewer_agent() -> Agent:
    """
    근거 검토 sub-agent.

    향후 역할:
    - Gemini Enterprise 검색 결과 검토
    - external_regulation / internal_policy / qa 우선순위 판단
    - 충돌 가능성 및 최신성 검토
    """
    return Agent(
        name="evidence_reviewer_agent",
        model="gemini-2.5-flash",
        description="검색된 외규/내규/Q&A 근거를 검토하고 충돌 가능성을 정리하는 sub-agent입니다.",
        instruction=EVIDENCE_REVIEWER_INSTRUCTION,
        output_schema=EvidenceReviewResult,
        output_key="evidence_review",
    )


def build_consultation_finalizer_agent() -> Agent:
    """
    최종 상담 초안 작성 sub-agent.

    향후 역할:
    - 분류 결과와 근거 검토 결과를 바탕으로 상담원용 답변 초안 생성
    - 기존 답변 형식 유지
    """
    return Agent(
        name="consultation_finalizer_agent",
        model="gemini-2.5-flash",
        description="상담원용 최종 답변 초안을 작성하는 sub-agent입니다.",
        instruction=CONSULTATION_FINALIZER_INSTRUCTION,
        output_schema=ConsultationDraft,
        output_key="consultation_draft",
    )
