# -*- coding: utf-8 -*-
"""
Factory for building the JeonseOrchestrator candidate.

현재 단계에서는 이 factory가 만든 오케스트레이터를 agent.py의 root_agent로 연결하지 않습니다.
목적은 sub-agent들과 JeonseOrchestrator가 정상적으로 조립되는지 확인하는 것입니다.
"""

from .orchestrator import JeonseOrchestrator
from .sub_agents import (
    build_question_classifier_agent,
    build_evidence_reviewer_agent,
    build_consultation_finalizer_agent,
)


def build_jeonse_orchestrator_candidate() -> JeonseOrchestrator:
    """
    향후 root_agent 후보가 될 JeonseOrchestrator를 생성합니다.

    현재는 조립/검증 전용입니다.
    실제 GE 진입점은 agent.py의 기존 root_agent를 계속 사용합니다.
    """
    question_classifier_agent = build_question_classifier_agent()
    evidence_reviewer_agent = build_evidence_reviewer_agent()
    consultation_finalizer_agent = build_consultation_finalizer_agent()

    return JeonseOrchestrator(
        name="jeonse_orchestrator",
        question_classifier_agent=question_classifier_agent,
        evidence_reviewer_agent=evidence_reviewer_agent,
        consultation_finalizer_agent=consultation_finalizer_agent,
        description=(
            "전세보증 상담 흐름을 질문분류, 근거검토, 최종답변 단계로 "
            "오케스트레이션하는 root agent 후보입니다."
        ),
    )
