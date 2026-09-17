# IDTA Artificial Intelligence Deployment 1.0

## 메타데이터
- categories: AI Deployment, [[Asset Administration Shell]], [[AI Lifecycle]]
- domain: [[디지털트윈·상호운용]]
- source: IDTA. "Artificial Intelligence Deployment Version 1.0." IDTA 02059-1-0.
- url: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Artificial%20Intelligence%20Deployment/1/0
- year: 2025
- authors: Industrial Digital Twin Association
- venue: IDTA Submodel Template Specification

## 1. 핵심 요약
- 산업 환경에서 AI model deployment 정보를 상호운용 가능한 property 구조로 제공한다.
- AI Dataset 및 AI Model Nameplate submodel과 함께 AI lifecycle 정보를 나누어 표현한다.
- 공식 template은 model reference, storage, input/output, software·hardware requirement, performance, monitoring과 risk 관련 항목을 구조화한다.

## 2. 문서 목적
가치 네트워크 참여자 사이에서 AI deployment 정보를 의미 있게 교환하고 산업 현장의 AI 배치를 쉽게 관리하도록 하는 것이다.

## 3. 핵심 개념 상세
- **Deployment information:** 배포 버전과 연결된 모델·저장 위치를 기술한다.
- **Requirements:** 실행에 필요한 software 및 hardware 조건을 표현한다.
- **Performance information:** hardware 조건과 연결된 inference 성능 정보를 기록한다.
- **Live monitoring:** workload와 drift 등 운용 중 관측 정보를 다룬다.

## 4. 구조 및 흐름
모델 자체 정보는 Model Nameplate에 두고, deployment submodel이 실행 조건·성능·운용 정보를 참조하여 AI lifecycle의 배포 단계를 기술한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| model과 deployment는 별도 정보 구조다 | 공식 scope가 두 AI submodel과 함께 lifecycle을 구성한다고 설명 |
| 산업 AI 배포의 표준 property 구조를 목표로 한다 | intended use-case에 standardized property structure for deploying AI를 명시 |

## 6. 한계 및 부족한 점
- 초점은 산업 환경이며 provider 선택 알고리즘이나 task intent 의미는 규정하지 않는다.
- AAS submodel 구조이지 inference 전송 protocol은 아니다.

## 7. 원문 기반 핵심 문장
> “It targets the assistance of deployment of AI models in a standardized way.”
