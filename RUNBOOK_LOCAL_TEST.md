# Jeonse Guarantee Agent - Local Test Runbook

## 1. 가상환경 활성화

cd ~/Desktop/jeonse_ver0.2
source .venv/bin/activate

## 2. 단독 검색 테스트

python jeonse_guarantee_agent/ge_search.py "무주택자 기준, HUG HF SGI 중에서 전세보증보험 보증한도가 가장 높은 기관은 어디인가요?"

python jeonse_guarantee_agent/ge_search.py "차주가 현재 1주택자이고 수도권 또는 규제지역에서 전세대출 3억원을 요청하는데 가능한가요?"

python jeonse_guarantee_agent/ge_search.py "차주가 2주택자 이상인 경우 전세자금대출이나 전세대출보증이 가능한가요?"

python jeonse_guarantee_agent/ge_search.py "임대인이 외국인인 경우 전세자금대출이나 보증보험 실행이 가능한가요?"

python jeonse_guarantee_agent/ge_search.py "SGI 전세금보장신용보험의 가입금액은 어떻게 정해지나요?"

python jeonse_guarantee_agent/ge_search.py "HUG HF SGI 전세보증보험은 각각 어떤 차이가 있나요?"

## 3. ADK Web 실행

adk web

## 4. 필수 통과 질문

1. 무주택자 기준 HUG/HF/SGI 중 전세보증보험 보증한도가 가장 높은 기관은?
- 기대 답변: SGI서울보증

2. 1주택자 수도권/규제지역 전세대출 3억원 가능 여부
- 기대 답변: 무조건 불가. 공통 외규 기준상 2억원 한도

3. 2주택자 이상 전세대출보증 가능 여부
- 기대 답변: 무조건 불가. 공통 외규 기준상 제한 또는 거절 대상

4. 외국인 임대인 전세대출/보증보험 실행 가능 여부
- 기대 답변: GS Bank 내규상 불가(외규 및 국내법상 가능하나 내규상 불가. 당행에선 처리 불가)

## 5. 실패 판정 기준

Python 검색 결과에 정답 근거 문서가 안 잡히면:
- Data Store / GCS / 문서 품질 / 검색 쿼리 문제

Python 검색 결과는 정상인데 ADK Web 답변이 틀리면:
- instruction / classifier / Agent 최종 답변 생성 문제