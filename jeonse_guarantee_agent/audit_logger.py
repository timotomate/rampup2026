"""
Audit logging utilities for the Jeonse Guarantee Advisory Agent.

목적:
- ADK callback에서 사용자 질문과 최종 AI 답변을 BigQuery에 저장합니다.
- 로그에는 원문(raw)을 저장하지 않고, Sensitive Data Protection(DLP) 또는 regex fallback으로
  마스킹된 question/answer만 저장합니다.

환경 변수:
- QA_LOGGING_ENABLED: TRUE/FALSE (default: TRUE)
- BQ_LOG_PROJECT_ID: BigQuery 로그 저장 프로젝트 (default: GOOGLE_CLOUD_PROJECT)
- BQ_LOG_DATASET: BigQuery dataset (default: jeonse_agent_logs)
- BQ_LOG_TABLE: BigQuery table (default: qa_audit_log)
- QA_MASKING_MODE: DLP / REGEX / NONE (default: DLP)
- DLP_LOCATION: Sensitive Data Protection location (default: global)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


PROJECT_ID = os.getenv("BQ_LOG_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "min-sung-jae-cloud"
DATASET_ID = os.getenv("BQ_LOG_DATASET", "jeonse_agent_logs")
TABLE_ID = os.getenv("BQ_LOG_TABLE", "qa_audit_log")
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
DLP_LOCATION = os.getenv("DLP_LOCATION", "global")

# DLP가 실패할 때도 데모가 중단되지 않게 regex fallback을 둡니다.
DEFAULT_MASKING_MODE = os.getenv("QA_MASKING_MODE", "DLP").upper()


# 한국 금융/상담 로그에서 데모로 보여주기 좋은 민감정보 후보입니다.
DLP_INFO_TYPES = [
    # 데모 안정성을 위해 우선 필요한 최소 InfoType만 사용합니다.
    # 주민번호/전화번호는 아래 regex 정책으로 먼저 마스킹하고,
    # DLP는 이름/이메일/카드/IP 등 추가 탐지 보조용으로 사용합니다.
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON_NAME",
    "KOREA_RRN",
    "CREDIT_CARD_NUMBER",
    "IP_ADDRESS",
]


REGEX_PATTERNS: List[Tuple[str, Any]] = [
    # 주민등록번호: 업무 정책상 앞 6자리는 유지하고 뒤 7자리를 마스킹합니다.
    # 예: 900101-1234567 -> 900101-*******
    (r"(?<!\d)(\d{6})[-\s]?([1-4]\d{6})(?!\d)", lambda m: f"{m.group(1)}-*******"),
    # 휴대폰 번호: 예: 010-1234-5678 -> 010-****-5678
    (r"(?<!\d)(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)", lambda m: f"{m.group(1)}-****-{m.group(3)}"),
    # 일반 유선전화: 예: 02-123-4567 -> 02-***-4567
    (r"(?<!\d)(02|0[3-6][1-5])[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)", lambda m: f"{m.group(1)}-***-{m.group(3)}"),
    # 이메일
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL_ADDRESS]"),
    # 데모 문장용 이름 후보: '홍길동 고객' 같은 형태만 제한적으로 마스킹합니다.
    (r"(?<![가-힣])([가-힣]{2,4})(?=\s*고객)", "[PERSON_NAME]"),
]



def _enabled() -> bool:
    return os.getenv("QA_LOGGING_ENABLED", "TRUE").upper() not in {"FALSE", "0", "NO", "N"}


def _sha256(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_json(value: Any, max_len: int = 20000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


def _state_to_dict(state: Any) -> Dict[str, Any]:
    if state is None:
        return {}
    if hasattr(state, "to_dict"):
        try:
            return state.to_dict()
        except Exception:
            pass
    try:
        return dict(state)
    except Exception:
        return {}


def _set_state(state: Any, key: str, value: Any) -> None:
    if state is None:
        return
    try:
        state[key] = value
        return
    except Exception:
        pass
    try:
        setattr(state, key, value)
    except Exception:
        pass


def _get_state_value(state: Any, key: str, default: Any = None) -> Any:
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:
        pass
    try:
        return state[key]
    except Exception:
        pass
    return getattr(state, key, default)


def _extract_text_from_content(content: Any) -> str:
    """google.genai.types.Content 또는 유사 객체에서 text part를 안전하게 추출합니다."""
    if not content:
        return ""
    parts = getattr(content, "parts", None) or []
    texts: List[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            texts.append(str(text))
    return "\n".join(texts).strip()


def _extract_last_user_text(llm_request: Any) -> str:
    contents = getattr(llm_request, "contents", None) or []
    for content in reversed(contents):
        role = getattr(content, "role", None)
        if role != "user":
            continue
        text = _extract_text_from_content(content)
        if _looks_like_real_user_question(text):
            return text
    return ""


def _looks_like_real_user_question(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    # Tool response나 긴 JSON 덩어리를 질문으로 오인하지 않기 위한 방어 로직입니다.
    if stripped.startswith("{") or stripped.startswith("["):
        return False
    if len(stripped) > 3000:
        return False
    return True


def _extract_response_text(llm_response: Any) -> str:
    if not llm_response:
        return ""
    content = getattr(llm_response, "content", None)
    if not content:
        return ""
    # Function call 응답은 최종 답변이 아니므로 제외합니다.
    parts = getattr(content, "parts", None) or []
    for part in parts:
        if getattr(part, "function_call", None):
            return ""
    return _extract_text_from_content(content)


def _detected_label(replacement: Any) -> str:
    if callable(replacement):
        # callable은 주민번호/전화번호처럼 부분 마스킹을 위한 규칙입니다.
        return ""
    return str(replacement).strip("[]")


def _regex_mask(text: str) -> Tuple[str, List[str]]:
    if not text:
        return "", []
    masked = text
    detected: List[str] = []
    for pattern, replacement in REGEX_PATTERNS:
        if re.search(pattern, masked):
            if "\\d{6}" in pattern:
                detected.append("KOREA_RRN")
            elif "01[016789]" in pattern or "0[3-6][1-5]" in pattern:
                detected.append("PHONE_NUMBER")
            else:
                label = _detected_label(replacement)
                if label:
                    detected.append(label)
            masked = re.sub(pattern, replacement, masked)
    return masked, sorted(set(detected))


def _dlp_mask(text: str) -> Tuple[str, List[str], str]:
    """
    Sensitive Data Protection API로 text를 de-identify합니다.
    실패 시 regex fallback을 사용합니다.
    """
    if not text:
        return "", [], "empty"

    # 업무 정책상 반드시 지켜야 하는 주민번호/전화번호 마스킹은 DLP 호출 전 regex로 먼저 적용합니다.
    # 이렇게 해야 DLP가 주민번호 전체를 [KOREA_RRN]으로 바꾸더라도
    # 데모 요구사항인 "앞 6자리 유지 + 뒤 7자리 마스킹"을 보장할 수 있습니다.
    policy_masked, policy_detected = _regex_mask(text)

    try:
        from google.cloud import dlp_v2

        parent = f"projects/{PROJECT_ID}/locations/{DLP_LOCATION}"
        client = dlp_v2.DlpServiceClient()

        inspect_config = {
            "info_types": [{"name": name} for name in DLP_INFO_TYPES],
            "include_quote": True,
            "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
        }

        # 어떤 infoType이 잡혔는지 별도 기록용으로 확인합니다.
        inspect_response = client.inspect_content(
            request={
                "parent": parent,
                "inspect_config": inspect_config,
                "item": {"value": policy_masked},
            }
        )
        detected = sorted({finding.info_type.name for finding in inspect_response.result.findings})

        deidentify_config = {
            "info_type_transformations": {
                "transformations": [
                    {
                        "primitive_transformation": {
                            "replace_with_info_type_config": {}
                        }
                    }
                ]
            }
        }

        deid_response = client.deidentify_content(
            request={
                "parent": parent,
                "inspect_config": inspect_config,
                "deidentify_config": deidentify_config,
                "item": {"value": policy_masked},
            }
        )
        masked = deid_response.item.value

        return masked, sorted(set(policy_detected + detected)), "dlp_with_policy_regex"

    except Exception as exc:
        # 원인 분석을 위해 예외 메시지를 BigQuery/Cloud Logging에서 볼 수 있게 남깁니다.
        err_msg = str(exc).replace("\n", " ")[:700]
        print(f"[qa-audit-log] DLP masking failed: {type(exc).__name__}: {err_msg}")
        detected = list(policy_detected)
        detected.append(f"DLP_FALLBACK_USED:{type(exc).__name__}:{err_msg}")
        return policy_masked, sorted(set(detected)), "regex_fallback"


def mask_text(text: str) -> Tuple[str, List[str], str]:
    mode = DEFAULT_MASKING_MODE
    if mode == "NONE":
        return text or "", [], "none"
    if mode == "REGEX":
        masked, detected = _regex_mask(text or "")
        return masked, detected, "regex"
    return _dlp_mask(text or "")


def _context_id(callback_context: Any, name: str) -> str:
    # ADK 버전/런타임에 따라 노출 필드가 다를 수 있어 방어적으로 추출합니다.
    direct = getattr(callback_context, name, None)
    if direct:
        return str(direct)
    for parent_name in ("invocation_context", "_invocation_context"):
        parent = getattr(callback_context, parent_name, None)
        if parent:
            value = getattr(parent, name, None)
            if value:
                return str(value)
    return "unknown"


def _append_state_list(state: Any, key: str, value: Any, max_items: int = 20) -> None:
    current = _get_state_value(state, key, [])
    if not isinstance(current, list):
        current = []
    current.append(value)
    _set_state(state, key, current[-max_items:])


def before_model_capture_question(callback_context: Any, llm_request: Any) -> None:
    """LLM 호출 직전 사용자 질문을 session state에 저장합니다."""
    question = _extract_last_user_text(llm_request)
    if question:
        _set_state(callback_context.state, "qa_current_question", question)
    return None


def after_tool_capture_search(tool: Any, args: Dict[str, Any], tool_context: Any, tool_response: Dict[str, Any]) -> None:
    """Tool 호출 결과에서 근거 문서/Tool 호출명을 session state에 저장합니다."""
    tool_name = getattr(tool, "name", "unknown_tool")
    _append_state_list(tool_context.state, "qa_tool_called", tool_name)

    # search_regulation_documents 결과에서 문서 근거만 요약해 저장합니다.
    if tool_name == "search_regulation_documents" and isinstance(tool_response, dict):
        result_value = tool_response.get("result", tool_response)
        if isinstance(result_value, dict):
            docs = []
            for item in result_value.get("results", [])[:5]:
                docs.append(
                    {
                        "title": item.get("title", ""),
                        "document_type": item.get("document_type", ""),
                        "effective_date_candidate": item.get("effective_date_candidate", ""),
                        "evidence": (item.get("evidence", "") or "")[:300],
                    }
                )
            _set_state(tool_context.state, "qa_source_documents", docs)
    return None


def after_model_log_qa(callback_context: Any, llm_response: Any) -> None:
    """최종 텍스트 답변 후보를 BigQuery에 저장합니다."""
    if not _enabled():
        return None

    answer = _extract_response_text(llm_response)
    if not answer:
        return None

    # 상담 답변 초안 형식이거나, 일반 답변이라도 text final response로 보이면 로그 대상으로 봅니다.
    question = _get_state_value(callback_context.state, "qa_current_question", "")
    if not question:
        return None

    invocation_id = getattr(callback_context, "invocation_id", "unknown") or "unknown"
    logged_ids = _get_state_value(callback_context.state, "qa_logged_invocation_ids", [])
    if isinstance(logged_ids, list) and invocation_id in logged_ids:
        return None

    question_masked, q_types, q_masking_mode = mask_text(question)
    answer_masked, a_types, a_masking_mode = mask_text(answer)

    row = {
        "event_time": datetime.now(timezone.utc).isoformat(),
        "invocation_id": str(invocation_id),
        "user_id": _context_id(callback_context, "user_id"),
        "session_id": _context_id(callback_context, "session_id"),
        "agent_name": getattr(callback_context, "agent_name", "jeonse_guarantee_agent"),
        "question_masked": question_masked,
        "answer_masked": answer_masked,
        "question_sha256": _sha256(question),
        "answer_sha256": _sha256(answer),
        "pii_detected_types": _safe_json(sorted(set(q_types + a_types)), max_len=5000),
        "tool_called": _safe_json(_get_state_value(callback_context.state, "qa_tool_called", []), max_len=5000),
        "source_documents": _safe_json(_get_state_value(callback_context.state, "qa_source_documents", []), max_len=20000),
        "masking_mode": f"question={q_masking_mode};answer={a_masking_mode}",
        "runtime": "adk_agent_runtime",
        "feedback": None,
        "feedback_reason": None,
    }

    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=PROJECT_ID)
        errors = client.insert_rows_json(
            FULL_TABLE_ID,
            [row],
            row_ids=[str(invocation_id)],
        )
        if errors:
            print(f"[qa-audit-log] BigQuery insert errors: {errors}")
        else:
            print(f"[qa-audit-log] inserted row into {FULL_TABLE_ID}, invocation_id={invocation_id}")
            if isinstance(logged_ids, list):
                logged_ids.append(invocation_id)
                _set_state(callback_context.state, "qa_logged_invocation_ids", logged_ids[-20:])
    except Exception as exc:
        # 로그 저장 실패 때문에 상담 Agent 답변 자체가 실패하지 않도록 삼킵니다.
        print(f"[qa-audit-log] failed to insert BigQuery row: {type(exc).__name__}: {exc}")

    return None
