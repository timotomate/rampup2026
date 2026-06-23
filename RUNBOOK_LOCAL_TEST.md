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




# BigQuery Q/A Audit Log Setup

## 1. API 활성화
```bash
gcloud services enable bigquery.googleapis.com dlp.googleapis.com --project=min-sung-jae-cloud
```

## 2. BigQuery Dataset/Table 생성
금융 도메인 데모 관점에서는 Seoul 리전(`asia-northeast3`)을 권장합니다. 리전 제약/권한 문제가 있으면 `US`로 바꾸어도 됩니다.

```bash
PROJECT_ID="min-sung-jae-cloud"
DATASET="jeonse_agent_logs"
TABLE="qa_audit_log"
LOCATION="asia-northeast3"

bq --location=${LOCATION} mk -d --description "Jeonse Agent masked Q/A audit logs" ${PROJECT_ID}:${DATASET}

bq mk --table ${PROJECT_ID}:${DATASET}.${TABLE} \
event_time:TIMESTAMP,invocation_id:STRING,user_id:STRING,session_id:STRING,agent_name:STRING,question_masked:STRING,answer_masked:STRING,question_sha256:STRING,answer_sha256:STRING,pii_detected_types:STRING,tool_called:STRING,source_documents:STRING,masking_mode:STRING,runtime:STRING,feedback:STRING,feedback_reason:STRING
```

## 3. Agent Runtime 서비스 계정에 권한 부여
배포 시 custom service account를 지정하지 않았다면 기본적으로 AI Platform Reasoning Engine Service Agent를 사용합니다. 정확한 서비스 계정은 Console의 Agent Runtime/보안 탭에서 확인하세요.

예시:
```bash
PROJECT_ID="min-sung-jae-cloud"
PROJECT_NUMBER="684756448782"
AGENT_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

# BigQuery 로그 insert 권한
bq add-iam-policy-binding ${PROJECT_ID}:jeonse_agent_logs \
  --member="serviceAccount:${AGENT_SA}" \
  --role="roles/bigquery.dataEditor"

# BigQuery job 생성 권한이 필요할 수 있음
# dataset 단위 권한만으로 실패하면 프로젝트 단위로 jobUser 부여
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${AGENT_SA}" \
  --role="roles/bigquery.jobUser"

# Sensitive Data Protection 호출 권한
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${AGENT_SA}" \
  --role="roles/dlp.user"
```

## 4. Agent 재배포
기존에 사용한 `adk deploy agent_engine ...` 명령으로 재배포합니다.

## 5. 로그 확인 쿼리
```sql
SELECT
  event_time,
  user_id,
  session_id,
  agent_name,
  question_masked,
  answer_masked,
  pii_detected_types,
  tool_called,
  source_documents,
  masking_mode
FROM `min-sung-jae-cloud.jeonse_agent_logs.qa_audit_log`
ORDER BY event_time DESC
LIMIT 20;
```
