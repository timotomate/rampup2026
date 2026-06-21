#!/bin/bash

set -e

PROJECT_ID="min-sung-jae-cloud"
LOCATION="global"
APP_ID="app-banking-advisory-app_1781761252022"
DATA_STORE_ID="ds02-gpt-jeonse-qa"
QUERY="${1:-임대인이 외국인인 경우 HUG HF SGI 전세보증보험 가입 가능 여부}"
OUT="${2:-raw_search_qa_only.json}"

SERVING_CONFIG="projects/${PROJECT_ID}/locations/${LOCATION}/collections/default_collection/engines/${APP_ID}/servingConfigs/default_search"
DATA_STORE_PATH="projects/${PROJECT_ID}/locations/${LOCATION}/collections/default_collection/dataStores/${DATA_STORE_ID}"

curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1/${SERVING_CONFIG}:search" \
  -d '{
    "servingConfig": "'"${SERVING_CONFIG}"'",
    "query": "'"${QUERY}"'",
    "pageSize": 5,
    "userPseudoId": "raw-dump-qa-only-test",
    "dataStoreSpecs": [
      {
        "dataStore": "'"${DATA_STORE_PATH}"'"
      }
    ],
    "relevanceScoreSpec": {
      "returnRelevanceScore": true
    },
    "contentSearchSpec": {
      "snippetSpec": {
        "returnSnippet": true
      },
      "extractiveContentSpec": {
        "maxExtractiveAnswerCount": 5,
        "maxExtractiveSegmentCount": 3,
        "returnExtractiveSegmentScore": true,
        "numPreviousSegments": 1,
        "numNextSegments": 1
      }
    }
  }' | python -m json.tool > "${OUT}"

echo "saved to ${OUT}"
