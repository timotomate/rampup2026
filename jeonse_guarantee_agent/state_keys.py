# -*- coding: utf-8 -*-
"""
Shared session.state keys for Jeonse Guarantee Advisory Agent orchestration.

ADK custom agent와 sub-agent들은 ctx.session.state를 통해 중간 결과를 공유합니다.
이 파일은 오케스트레이터와 sub-agent가 사용할 공용 key 이름을 한 곳에서 관리합니다.
"""

# 사용자 질문 원문 또는 현재 턴 질문
USER_QUESTION = "jeonse_user_question"

# question_classifier_agent의 output_key
QUESTION_CLASSIFICATION = "question_classification"

# Gemini Enterprise Data Store 검색 결과
SEARCH_RESULTS = "jeonse_search_results"

# 검색에 사용한 query / data store / tool 호출 정보
SEARCH_METADATA = "jeonse_search_metadata"

# evidence_reviewer_agent의 output_key
EVIDENCE_REVIEW = "evidence_review"

# consultation_finalizer_agent의 output_key
CONSULTATION_DRAFT = "consultation_draft"

# 최종 사용자 표시 답변
FINAL_ANSWER = "jeonse_final_answer"

# BigQuery audit log 중복 저장 방지 플래그
AUDIT_LOG_WRITTEN = "jeonse_audit_log_written"

# audit log에 들어갈 tool/source 정보
TOOL_CALLED = "tool_called"
SOURCE_DOCUMENTS = "source_documents"
