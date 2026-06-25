# -*- coding: utf-8 -*-
"""
Jeonse Guarantee Advisory Agent Orchestrator.

이 파일은 향후 root_agent를 오케스트레이션 전용 Agent로 전환하기 위한 준비 파일입니다.

현재 단계:
- JeonseOrchestrator 내부에 실제 실행 흐름 초안을 구현합니다.
- 하지만 아직 agent.py의 root_agent로 연결하지 않습니다.
- 따라서 기존 GE 진입점과 기존 root_agent 동작에는 영향을 주지 않습니다.

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

import json
import logging
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from .search_tools import search_regulation_documents
from .audit_logger import log_orchestrated_qa_event
from .state_keys import (
    USER_QUESTION,
    QUESTION_CLASSIFICATION,
    SEARCH_RESULTS,
    SEARCH_METADATA,
    EVIDENCE_REVIEW,
    CONSULTATION_DRAFT,
    FINAL_ANSWER,
    AUDIT_LOG_WRITTEN,
)

logger = logging.getLogger(__name__)


class JeonseOrchestrator(BaseAgent):
    """
    전세보증 상담 보조 Agent의 오케스트레이션 전용 root agent 후보입니다.

    역할:
    - 사용자의 질문을 직접 모두 처리하지 않고, 단계별 sub-agent와 tool을 호출합니다.
    - 질문분류, 근거검토, 최종답변 생성을 분리합니다.
    - BigQuery audit log가 중복 저장되지 않도록 최종 단계에서 1회만 기록하는 구조를 목표로 합니다.

    주의:
    - 현재 단계에서는 아직 agent.py의 root_agent에 연결하지 않습니다.
    - 검색 tool도 아직 직접 호출하지 않습니다.
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
        전세보증 상담 오케스트레이션 실행 흐름 초안입니다.

        현재 구현:
        1. 사용자 질문을 state에 저장
        2. question_classifier_agent 실행
        3. 검색 결과 placeholder 저장
        4. evidence_reviewer_agent 실행
        5. consultation_finalizer_agent 실행
        6. final answer를 state에 저장

        아직 구현하지 않은 것:
        - 실제 Gemini Enterprise Search tool 호출
        - audit_logger의 명시적 1회 호출
        - agent.py root_agent 교체
        """
        tag = self._log_ctx(ctx)
        user_question = self._get_last_user_message(ctx)

        logger.info("%s ── JeonseOrchestrator turn 시작 ──", tag)
        logger.info("%s 사용자 질문: %r", tag, user_question[:200])

        # 현재 turn에서 공유할 기본 state 초기화
        ctx.session.state[USER_QUESTION] = user_question
        ctx.session.state[AUDIT_LOG_WRITTEN] = False

        # 1. 질문 분류 sub-agent 실행
        logger.info("%s [1/4] question_classifier_agent 호출", tag)
        async for event in self.question_classifier_agent.run_async(ctx):
            # classifier의 중간 JSON/텍스트가 사용자에게 그대로 노출되지 않도록 content를 비웁니다.
            self._suppress_event_content(event)
            yield event

        classification = self._read_state_json(ctx, QUESTION_CLASSIFICATION, default={})
        logger.info("%s [1/4] 질문 분류 결과: %s", tag, classification)

        # 2. Gemini Enterprise Data Store 검색
        search_query = self._build_search_query(
            user_question=user_question,
            classification=classification,
        )
        logger.info("%s [2/4] search_regulation_documents 호출 query=%r", tag, search_query[:300])

        search_result = self._run_regulation_search(search_query)

        ctx.session.state[SEARCH_RESULTS] = search_result
        ctx.session.state[SEARCH_METADATA] = {
            "search_connected": True,
            "search_step": "search_regulation_documents",
            "query": search_query,
        }

        logger.info("%s [2/4] 검색 결과 state 저장 완료", tag)

        # 3. 근거 검토 sub-agent 실행
        logger.info("%s [3/4] evidence_reviewer_agent 호출", tag)
        async for event in self.evidence_reviewer_agent.run_async(ctx):
            # 근거 검토 중간 산출물은 사용자에게 바로 노출하지 않습니다.
            self._suppress_event_content(event)
            yield event

        evidence_review = self._read_state_json(ctx, EVIDENCE_REVIEW, default={})
        logger.info("%s [3/4] 근거 검토 결과: %s", tag, evidence_review)

        # 4. 최종 상담 답변 sub-agent 실행
        logger.info("%s [4/4] consultation_finalizer_agent 호출", tag)
        finalizer_events = []

        async for event in self.consultation_finalizer_agent.run_async(ctx):
            final_text = self._extract_event_text(event)
            if final_text:
                guarded_text = self._apply_identity_guard(final_text)
                if guarded_text != final_text:
                    self._replace_event_text(event, guarded_text)
                    logger.warning("%s [4/4] identity guard sanitized final answer", tag)
                ctx.session.state[FINAL_ANSWER] = guarded_text

            # 중요:
            # Agent Runtime Playground에서 답변이 잠깐 보였다가 사라지는 현상을 막기 위해,
            # finalizer의 표준 LlmAgent Event를 즉시 yield하지 않습니다.
            # 먼저 BigQuery audit logging까지 끝낸 뒤,
            # finalizer가 만든 표준 Event를 마지막에 yield합니다.
            finalizer_events.append(event)

        final_answer = ctx.session.state.get(FINAL_ANSWER, "")
        logger.info("%s [4/4] 최종 답변 state preview: %r", tag, str(final_answer)[:500])

        # 5. 오케스트레이터 경로의 BigQuery audit log 저장
        #
        # legacy_root_agent에서는 ADK callback으로 Q/A 로그를 저장했지만,
        # JeonseOrchestrator는 BaseAgent 기반 custom agent이므로 마지막 단계에서 명시적으로 1회 저장합니다.
        audit_written = log_orchestrated_qa_event(
            question=ctx.session.state.get(USER_QUESTION, user_question),
            answer=str(final_answer or ""),
            state=ctx.session.state,
            invocation_id=str(getattr(ctx, "invocation_id", "") or "unknown"),
            user_id=str(getattr(ctx.session, "user_id", "") or "unknown"),
            session_id=str(getattr(ctx.session, "id", "") or "unknown"),
            agent_name=self.name,
        )
        logger.info("%s [5/5] BigQuery audit log written=%s", tag, audit_written)

        final_answer_for_user = str(ctx.session.state.get(FINAL_ANSWER, final_answer) or "").strip()

        if finalizer_events:
            logger.info("%s [5/5] finalizer response event yield after audit logging", tag)
            for event in finalizer_events:
                yield event
        elif final_answer_for_user:
            # 방어적 fallback: 정상 상황에서는 finalizer_events가 존재해야 합니다.
            logger.warning("%s [5/5] no finalizer event; yielding fallback root final response", tag)
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=final_answer_for_user)],
                ),
            )

        logger.info("%s ── JeonseOrchestrator turn 종료 ──", tag)

    def _build_search_query(
        self,
        user_question: str,
        classification: Any,
    ) -> str:
        """
        질문분류 결과와 사용자 질문을 바탕으로 검색 query를 구성합니다.

        현재 단계에서는 과도한 query rewriting을 하지 않습니다.
        이유:
        - 기존 root_agent에서 잘 동작하던 검색 흐름을 최대한 유지하기 위해서입니다.
        - classification이 dict 형태이면 search_focus_terms/entities 정도만 보강합니다.
        """
        terms = []

        if isinstance(classification, dict):
            search_focus_terms = classification.get("search_focus_terms") or []
            if isinstance(search_focus_terms, list):
                terms.extend(str(term) for term in search_focus_terms if term)

            entities = classification.get("entities") or {}
            if isinstance(entities, dict):
                for value in entities.values():
                    if isinstance(value, (str, int, float)) and value:
                        terms.append(str(value))
                    elif isinstance(value, list):
                        terms.extend(str(item) for item in value if item)

        # 중복 제거: 순서 유지
        deduped_terms = []
        seen = set()
        for term in terms:
            cleaned = str(term).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped_terms.append(cleaned)

        if deduped_terms:
            return f"{user_question}\n\n검색 보강 키워드: {' '.join(deduped_terms[:12])}".strip()

        return user_question.strip()

    def _run_regulation_search(
        self,
        query: str,
    ) -> Any:
        """
        Gemini Enterprise Data Store 검색 Tool을 실행합니다.

        search_regulation_documents는 기존 root_agent에서도 사용하는 동일 Tool입니다.
        여기서는 향후 JeonseOrchestrator가 같은 Tool을 재사용할 수 있도록 연결합니다.
        """
        if not query:
            return {
                "status": "skipped",
                "reason": "empty query",
                "results": [],
            }

        try:
            return search_regulation_documents(query)
        except Exception as exc:
            logger.exception("search_regulation_documents failed in orchestrator")
            return {
                "status": "error",
                "error": str(exc),
                "results": [],
            }

    def _log_ctx(self, ctx: InvocationContext) -> str:
        """로깅에 사용할 세션 컨텍스트 prefix를 생성합니다."""
        session_id = getattr(ctx.session, "id", "") or "?"
        user_id = getattr(ctx.session, "user_id", "") or "?"
        return f"[session={session_id[:8]} user={str(user_id)[:20]}]"

    def _get_last_user_message(self, ctx: InvocationContext) -> str:
        """세션 이벤트에서 마지막 사용자 메시지 텍스트를 추출합니다."""
        for event in reversed(ctx.session.events or []):
            content = getattr(event, "content", None)
            if not content:
                continue

            if getattr(content, "role", None) != "user":
                continue

            parts = getattr(content, "parts", None) or []
            texts = []
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)

            if texts:
                return "\n".join(texts).strip()

        return ""

    def _read_state_json(
        self,
        ctx: InvocationContext,
        key: str,
        default: Any,
    ) -> Any:
        """
        session.state에서 값을 읽고, JSON 문자열이면 dict/list로 파싱합니다.

        ADK output_key는 agent 응답을 state에 저장합니다.
        output_schema를 쓰더라도 환경/버전에 따라 문자열 JSON 형태로 들어올 수 있으므로
        안전하게 처리합니다.
        """
        raw = ctx.session.state.get(key, default)

        if raw is None:
            return default

        if isinstance(raw, (dict, list)):
            return raw

        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return default

            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return raw

        return raw

    def _suppress_event_content(self, event: Event) -> None:
        """
        classifier/reviewer 같은 중간 sub-agent 응답이 사용자에게 그대로 보이지 않도록 합니다.

        Dooray 예시 프로젝트와 같은 패턴입니다.
        event는 yield하되 content.parts를 비워 ADK 내부 state/action 처리는 유지하고,
        사용자 화면에는 중간 JSON이 노출되지 않게 합니다.
        """
        content = getattr(event, "content", None)
        if not content:
            return

        parts = getattr(content, "parts", None)
        if parts:
            content.parts = []

    def _apply_identity_guard(self, text: str) -> str:
        """
        최종 답변이 타 은행 상담원 정체성을 갖는 것을 방지합니다.

        주의:
        - "KB의 생각" 같은 참고 근거 제목은 그대로 둘 수 있습니다.
        - "KB국민은행 상담원입니다"처럼 답변 주체를 잘못 말하는 문구만 교정합니다.
        """
        if not text:
            return text

        replacements = {
            "KB국민은행 상담원입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "국민은행 상담원입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "KB Bank 상담원입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "KB국민은행입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "국민은행입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "KB Bank입니다": "GS Bank 전세대출 및 보증 상담 보조 Agent입니다",
            "KB국민은행 상담 보조 Agent": "GS Bank 전세대출 및 보증 상담 보조 Agent",
            "국민은행 상담 보조 Agent": "GS Bank 전세대출 및 보증 상담 보조 Agent",
        }

        guarded = text
        for source, target in replacements.items():
            guarded = guarded.replace(source, target)

        return guarded

    def _replace_event_text(self, event: Event, new_text: str) -> None:
        """
        사용자 화면에 표시될 finalizer event text를 교체합니다.

        Event/Part 구현이 환경에 따라 immutable일 가능성도 있으므로,
        실패해도 state와 BigQuery 저장은 guarded_text 기준으로 계속 진행합니다.
        """
        content = getattr(event, "content", None)
        if not content:
            return

        parts = getattr(content, "parts", None) or []
        for part in parts:
            if getattr(part, "text", None):
                try:
                    part.text = new_text
                except Exception:
                    logger.warning("failed to replace event text for identity guard", exc_info=True)
                return

    def _extract_event_text(self, event: Event) -> str:
        """Event content에서 텍스트를 추출합니다."""
        content = getattr(event, "content", None)
        if not content:
            return ""

        parts = getattr(content, "parts", None) or []
        texts = []

        for part in parts:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)

        return "\n".join(texts).strip()
