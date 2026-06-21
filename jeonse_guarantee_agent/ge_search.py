import calendar
import html
import json
import re
from typing import Any, Dict, List, Optional

import google.auth
from google.auth.transport.requests import Request
import requests


PROJECT_ID = "min-sung-jae-cloud"
PROJECT_NUMBER = "684756448782"
LOCATION = "global"

# Raw Search API 응답 기준 실제 Engine ID
APP_ID = "app-banking-advisory-app_1781761252022"

SERVING_CONFIG = (
    f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
    f"engines/{APP_ID}/servingConfigs/default_search"
)

SEARCH_URL = f"https://discoveryengine.googleapis.com/v1/{SERVING_CONFIG}:search"


def _get_access_token() -> str:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return credentials.token


def _strip_html(text: Any) -> str:
    """HTML 태그와 entity를 제거합니다."""
    if text is None:
        return ""

    text = str(text)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _guess_doc_type(link: str, title: str, document_name: str = "") -> str:
    """GCS 경로, 제목, Data Store resource name을 기반으로 문서 유형을 추정합니다."""
    combined = f"{link} {title} {document_name}".lower()

    if "external_regulation" in combined or "external-regulation" in combined:
        return "external_regulation"
    if "internal_policy" in combined or "internal-policy" in combined:
        return "internal_policy"
    if "/qa/" in combined or "qa_" in combined or "jeonse-qa" in combined:
        return "qa"

    return "unknown"


def _normalize_two_digit_year(year: str) -> str:
    """'26' 같은 연도를 2026으로 보정합니다."""
    if len(year) == 2:
        return f"20{year}"
    return year


def _month_end_date(year: int, month: int) -> str:
    """YYYY년 M월말 표현을 YYYY-MM-DD로 정규화합니다."""
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def _find_dates_with_context(text: str, source: str, priority: int) -> List[Dict[str, Any]]:
    """
    텍스트에서 날짜 후보를 찾고, 날짜 주변 문맥까지 함께 저장합니다.
    날짜 자체보다 '기준', '작성', '개정', '시행', '까지' 같은 주변 단어가 중요합니다.
    """
    if not text:
        return []

    candidates: List[Dict[str, Any]] = []

    patterns = [
        # 2025년 8월말 기준
        r"(?P<year>20\d{2})\s*년\s*(?P<month>\d{1,2})\s*월\s*말\s*(?P<label>기준|작성|현재)?",

        # 2026년 7월 1일
        r"(?P<year>20\d{2})\s*년\s*(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일",

        # 2026-07-01 / 2026.07.01 / 2026_07_01 / 26.6.30
        r"(?P<year>20\d{2}|\d{2})[-_.](?P<month>0?[1-9]|1[0-2])[-_.](?P<day>0?[1-9]|[12]\d|3[01])",

        # 20260701
        r"(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            year = int(_normalize_two_digit_year(match.group("year")))
            month = int(match.group("month"))
            day_group = match.groupdict().get("day")

            if day_group:
                day = int(day_group)
                date_value = f"{year:04d}-{month:02d}-{day:02d}"
                has_full_date = True
            else:
                date_value = _month_end_date(year, month)
                has_full_date = True

            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            context = text[start:end]

            if source == "title_or_filename" and has_full_date:
                semantic_type = "filename_full_date"
            elif any(k in context for k in ["기준", "작성", "개정", "시행", "적용"]):
                semantic_type = "document_or_rule_base_date"
            elif any(k in context for k in ["까지", "한시", "유효", "만료"]):
                semantic_type = "valid_until_or_deadline"
            elif any(k in context for k in ["연혁", "출시", "설립", "개시"]):
                semantic_type = "history_or_incidental"
            else:
                semantic_type = "unknown_date"

            candidates.append(
                {
                    "date": date_value,
                    "source": source,
                    "priority": priority,
                    "semantic_type": semantic_type,
                    "context": context,
                }
            )

    # khug_2025 같은 파일명 연도 보조 처리
    for match in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", text):
        year = match.group(1)

        # 이미 같은 연도의 더 구체적인 날짜가 있으면 생략
        if any(c["date"].startswith(year) for c in candidates):
            continue

        start = max(0, match.start() - 30)
        end = min(len(text), match.end() + 30)
        context = text[start:end]

        candidates.append(
            {
                "date": f"{year}-01-01",
                "source": source,
                "priority": priority,
                "semantic_type": "filename_year_only" if source == "title_or_filename" else "unknown_date",
                "context": context,
            }
        )

    return candidates


def _build_date_candidates(
    title: str,
    link: str,
    evidence: str,
    snippets: List[str],
    extractive_answers: List[str],
    extractive_segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    날짜 후보를 출처별로 수집합니다.
    최신성 기준으로는 문서 기준일/파일명 날짜를 우선하고,
    evidence나 segment 내부 날짜는 문맥을 보고 보조 판단합니다.
    """
    candidates: List[Dict[str, Any]] = []

    title_link_text = f"{title} {link}"
    evidence_text = evidence or ""
    snippet_answer_text = " ".join(snippets + extractive_answers)
    segment_text = " ".join(
        seg.get("content", "")
        for seg in extractive_segments
        if isinstance(seg, dict)
    )

    candidates.extend(_find_dates_with_context(title_link_text, "title_or_filename", 1))
    candidates.extend(_find_dates_with_context(evidence_text, "evidence", 3))
    candidates.extend(_find_dates_with_context(snippet_answer_text, "snippet_or_extractive_answer", 4))
    candidates.extend(_find_dates_with_context(segment_text, "extractive_segment", 5))

    # 같은 date/source/semantic_type 중복 제거
    dedup: List[Dict[str, Any]] = []
    seen = set()

    for candidate in candidates:
        key = (
            candidate.get("date"),
            candidate.get("source"),
            candidate.get("semantic_type"),
        )

        if key not in seen:
            seen.add(key)
            dedup.append(candidate)

    return dedup


def _choose_effective_date(date_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    최신성 판단용 대표 날짜를 선택합니다.
    단순히 가장 최신 날짜를 고르지 않고, 날짜의 의미를 우선합니다.
    """
    if not date_candidates:
        return {
            "effective_date_candidate": "",
            "effective_date_source": "none",
            "date_confidence": "none",
            "freshness_basis": "no_date_found",
        }

    semantic_weight = {
        "document_or_rule_base_date": 0,
        "filename_full_date": 1,
        "filename_year_only": 2,
        "valid_until_or_deadline": 3,
        "unknown_date": 4,
        "history_or_incidental": 9,
    }

    sorted_candidates = sorted(
        date_candidates,
        key=lambda candidate: (
            semantic_weight.get(candidate.get("semantic_type", "unknown_date"), 5),
            candidate.get("priority", 99),
            candidate.get("date", ""),
        ),
    )

    best_semantic_weight = semantic_weight.get(
        sorted_candidates[0].get("semantic_type", "unknown_date"),
        5,
    )
    best_priority = sorted_candidates[0].get("priority", 99)

    same_best_group = [
        candidate for candidate in sorted_candidates
        if semantic_weight.get(candidate.get("semantic_type", "unknown_date"), 5) == best_semantic_weight
        and candidate.get("priority", 99) == best_priority
    ]

    # 같은 의미/같은 우선순위 안에서는 최신 날짜 선택
    best = sorted(
        same_best_group,
        key=lambda candidate: candidate.get("date", ""),
        reverse=True,
    )[0]

    semantic_type = best.get("semantic_type", "unknown_date")
    source = best.get("source", "unknown")

    if semantic_type in ["document_or_rule_base_date", "filename_full_date"]:
        confidence = "high"
    elif semantic_type in ["filename_year_only", "valid_until_or_deadline"]:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "effective_date_candidate": best.get("date", ""),
        "effective_date_source": source,
        "date_confidence": confidence,
        "freshness_basis": semantic_type,
    }


def _freshness_warning(date_info: Dict[str, Any]) -> str:
    """날짜 후보의 의미와 신뢰도에 따른 상담원 주의 문구를 생성합니다."""
    basis = date_info.get("freshness_basis", "no_date_found")
    source = date_info.get("effective_date_source", "none")

    if basis == "document_or_rule_base_date":
        return f"{source}에서 기준일/작성일/개정일 성격의 날짜를 추출했습니다."
    if basis == "filename_full_date":
        return "파일명 또는 제목의 명확한 날짜를 기준일 후보로 사용했습니다."
    if basis == "filename_year_only":
        return "파일명 또는 제목의 연도만 기준일 후보로 사용했습니다. 실제 시행일/개정일 확인이 필요합니다."
    if basis == "valid_until_or_deadline":
        return "날짜가 유효기한 또는 한시 적용 기한일 수 있습니다. 문서 기준일과 구분해서 확인해야 합니다."
    if basis == "history_or_incidental":
        return "연혁 또는 부수적 날짜가 기준일 후보로 잡혔을 수 있습니다. 최신성 판단에 주의가 필요합니다."

    return "기준일 후보를 찾지 못했습니다. 문서의 시행일, 개정일 또는 업로드일 확인이 필요합니다."


def _extract_list_texts(
    data: Dict[str, Any],
    key: str,
    text_key_candidates: List[str],
) -> List[str]:
    """snippets 또는 extractive_answers에서 텍스트를 추출합니다."""
    items = data.get(key, [])

    if not isinstance(items, list):
        return []

    texts: List[str] = []

    for item in items:
        if isinstance(item, dict):
            value = ""
            for text_key in text_key_candidates:
                if item.get(text_key):
                    value = item.get(text_key)
                    break
        else:
            value = item

        cleaned = _strip_html(value)
        if cleaned:
            texts.append(cleaned)

    return texts


def _extract_segment_texts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """extractive_segments에서 content와 score를 추출합니다."""
    items = data.get("extractive_segments", [])

    if not isinstance(items, list):
        return []

    segments: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        content = _strip_html(item.get("content", ""))
        if not content:
            continue

        segments.append(
            {
                "content": content,
                "relevance_score": item.get("relevanceScore"),
                "id": item.get("id", ""),
                "page_span": item.get("page_span") or item.get("pageSpan", {}),
            }
        )

    return segments


def _choose_evidence(
    extractive_answers: List[str],
    snippets: List[str],
    extractive_segments: List[Dict[str, Any]],
) -> str:
    """
    evidence 우선순위:
    1. extractive answer: 질문에 직접 답하는 짧은 원문
    2. snippet: 검색 결과 미리보기
    3. extractive segment: 긴 원문 구간
    """
    if extractive_answers:
        return extractive_answers[0][:500]

    if snippets:
        return snippets[0][:500]

    if extractive_segments:
        return extractive_segments[0]["content"][:700]

    return ""


def search_gemini_enterprise(
    query: str,
    page_size: int = 5,
    data_store_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gemini Enterprise App 기준으로 연결된 Data Store를 검색합니다.
    REST API 원본 JSON을 직접 파싱하여 snippets / extractive_answers / extractive_segments를 안정적으로 추출합니다.
    """
    token = _get_access_token()

    payload: Dict[str, Any] = {
        "servingConfig": SERVING_CONFIG,
        "query": query,
        "pageSize": page_size,
        "userPseudoId": "adk-local-test",
        "relevanceScoreSpec": {
            "returnRelevanceScore": True,
        },
        "contentSearchSpec": {
            "snippetSpec": {
                "returnSnippet": True,
            },
            "extractiveContentSpec": {
                "maxExtractiveAnswerCount": 5,
                "maxExtractiveSegmentCount": 3,
                "returnExtractiveSegmentScore": True,
                "numPreviousSegments": 1,
                "numNextSegments": 1,
            },
        },
    }

    if data_store_path:
        payload["dataStoreSpecs"] = [
            {
                "dataStore": data_store_path,
            }
        ]

    response = requests.post(
        SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    if response.status_code >= 400:
        return {
            "query": query,
            "serving_config": SERVING_CONFIG,
            "result_count": 0,
            "error": {
                "status_code": response.status_code,
                "body": response.text,
            },
            "results": [],
        }

    raw = response.json()
    results: List[Dict[str, Any]] = []

    for item in raw.get("results", []):
        doc = item.get("document", {})
        data = doc.get("derivedStructData", {})

        document_name = doc.get("name", "")
        document_id = doc.get("id", item.get("id", ""))

        title = data.get("title", document_id)
        link = data.get("link", "")

        snippets = _extract_list_texts(
            data,
            "snippets",
            ["snippet", "content", "text"],
        )
        extractive_answers = _extract_list_texts(
            data,
            "extractive_answers",
            ["content", "answer", "text"],
        )
        extractive_segments = _extract_segment_texts(data)

        evidence = _choose_evidence(
            extractive_answers=extractive_answers,
            snippets=snippets,
            extractive_segments=extractive_segments,
        )

        doc_type = _guess_doc_type(link, title, document_name)

        date_candidates = _build_date_candidates(
            title=title,
            link=link,
            evidence=evidence,
            snippets=snippets,
            extractive_answers=extractive_answers,
            extractive_segments=extractive_segments,
        )

        date_info = _choose_effective_date(date_candidates)
        effective_date = date_info.get("effective_date_candidate", "")

        relevance_score = None
        try:
            relevance_score = (
                item.get("modelScores", {})
                .get("relevance_score", {})
                .get("values", [None])[0]
            )
        except Exception:
            relevance_score = None

        results.append(
            {
                "document_id": document_id,
                "title": title,
                "link": link,
                "document_name": document_name,
                "document_type": doc_type,
                "effective_date_candidate": effective_date,
                "effective_date_source": date_info.get("effective_date_source", "none"),
                "date_confidence": date_info.get("date_confidence", "none"),
                "freshness_basis": date_info.get("freshness_basis", "no_date_found"),
                "date_candidates": date_candidates[:10],
                "freshness_warning": _freshness_warning(date_info),
                "relevance_score": relevance_score,
                "snippets": snippets[:2],
                "extractive_answers": extractive_answers[:2],
                "extractive_segments": extractive_segments[:2],
                "evidence": evidence,
            }
        )

    return {
        "query": query,
        "serving_config": SERVING_CONFIG,
        "result_count": len(results),
        "results": results,
    }


if __name__ == "__main__":
    import sys

    q = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "임대인이 외국인인 경우 HUG HF SGI 전세보증보험 가입 가능 여부"
    )
    print(json.dumps(search_gemini_enterprise(q), ensure_ascii=False, indent=2))