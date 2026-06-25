# Jeonse Guarantee Agent Orchestrator Refactor Handoff

## Current branch
feature/jeonse-orchestrator-subagents

## Stable runtime
Existing Reasoning Engine ID:
4496904151313154048

Existing resource path:
projects/684756448782/locations/us-central1/reasoningEngines/4496904151313154048

## Current architecture
Gemini Enterprise Web App
→ Agent Runtime
→ JeonseOrchestrator
→ question_classifier_agent
→ search_regulation_documents
→ evidence_reviewer_agent
→ consultation_finalizer_agent
→ BigQuery masked audit log

## Feature flag
USE_ORCHESTRATOR_AGENT=TRUE
- Uses JeonseOrchestrator + sub-agents
- BigQuery runtime value: adk_orchestrator

USE_ORCHESTRATOR_AGENT=FALSE
- Uses legacy root agent
- Tools: classify_consultation_question, search_regulation_documents
- Callback-based BigQuery logging

## Current validated state
- TRUE mode ADK Web graph shows jeonse_orchestrator with 3 sub-agents.
- TRUE mode answers correctly in GE.
- TRUE mode BigQuery logging works.
- BigQuery stores masked question/answer only.
- Runtime path should remain the existing Reasoning Engine ID.

## Current issue to fix
- On greeting or some generic responses, final answer may say "KB국민은행 상담원입니다".
- Cause: search result title/source such as "KB의 생각" can be confused with the answer identity.
- Required fix:
  - Always answer as GS Bank 전세대출 및 보증 상담 보조 Agent.
  - Never claim to be KB국민은행, 국민은행, KB Bank, or another bank.
  - KB/other bank documents may be referenced only as external public reference materials, never as the speaker identity.
  - Continue logging all conversations. Do not implement greeting/search skip for now.

## Deployment direction
- Final direction: deploy TRUE orchestrator version to existing Agent Runtime ID.
- Before redeploy, fix GS Bank identity guard and test locally.
