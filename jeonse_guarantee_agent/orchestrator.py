# -*- coding: utf-8 -*-
"""
Jeonse Guarantee Advisory Agent Orchestrator.

이 파일은 향후 root_agent를 오케스트레이션 전용 Agent로 전환하기 위한 준비 파일입니다.

현재 단계에서는 이 클래스를 agent.py에 연결하지 않습니다.
즉, 기존 GE 진입점과 기존 root_agent 동작에는 영향을 주지 않습니다.

향후 목표 흐름:
1. 사용자 질문 수신
2. question_classifier_agent 실행
3. Gemini Enterprise Data Store 검색
4. evidence_reviewer_agent 실행
5. consultation_finalizer_agent 실행
6. BigQuery masked audit log 1회 저장
7. 최종 답변 반환
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

logger = logging.getLogger(__name__)


class JeonseOrchestrator(BaseAgent):
    """
    전세보증 상담 보조 Agent의 오케스트레이션 전용 root agent 후보입니다.

    역할:
    - 사용자의 질문을 직접 모두 처리하지 않고, 단계별 sub-agent와 tool을 호출합니다.
    - 질문분류, 근거검토, 최종답변 생성을 분리합니다.
    - BigQuery audit log가 중복 저장되지 않도록 최종 단계에서 1회만 기록하는 구조를 목표로 합니다.

    주의:
    - 현재 1차 skeleton 단계에서는 실제 실행에 연결하지 않습니다.
    - _run_async_impl 역시 아직 실제 orchestration flow를 구현하지 않습니다.
    """

    question_classifier_agent: Any
    evidence_reviewer_agent: Any
    consultation_finalizer_agent: Any

    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        name: str,
        question_classifier_agent: Any,
        evidence_reviewer_agent: Any,
        consultation_finalizer_agent: Any,
        description: Optional[str] = None,
    ) -> None:
        sub_agents_list = [
            question_classifier_agent,
            evidence_reviewer_agent,
            consultation_finalizer_agent,
        ]

        super().__init__(
            name=name,
            description=description
            or "전세보증 상담 흐름을 질문분류, 근거검토, 최종답변 단계로 오케스트레이션하는 Agent입니다.",
            question_classifier_agent=question_classifier_agent,
            evidence_reviewer_agent=evidence_reviewer_agent,
            consultation_finalizer_agent=consultation_finalizer_agent,
            sub_agents=sub_agents_list,
        )

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        """
        향후 구현 예정인 실제 orchestration flow입니다.

        예상 구현 순서:
        1. question_classifier_agent.run_async(ctx)
        2. ctx.session.state["question_classification"] 확인
        3. search_regulation_documents 실행 또는 검색 helper 호출
        4. ctx.session.state에 검색 결과 저장
        5. evidence_reviewer_agent.run_async(ctx)
        6. consultation_finalizer_agent.run_async(ctx)
        7. audit_logger.log_qa_event(...) 1회 호출
        8. finalizer event yield

        현재는 안전을 위해 실제 root_agent에 연결하지 않습니다.
        """
        logger.info("[%s] JeonseOrchestrator skeleton called.", self.name)

        raise NotImplementedError(
            "JeonseOrchestrator is a skeleton and is not wired as root_agent yet."
        )

        # 이 yield는 type checker와 async generator 형태 유지를 위한 unreachable code입니다.
        # 실제 실행되지 않습니다.
        if False:
            yield Event(author=self.name)
