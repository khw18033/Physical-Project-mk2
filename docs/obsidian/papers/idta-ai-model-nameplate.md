# IDTA Artificial Intelligence Model Nameplate 1.0

## 메타데이터
- categories: AI Model Documentation, [[Asset Administration Shell]], [[AI Lifecycle]]
- domain: [[디지털트윈·상호운용]]
- source: IDTA. "Artificial Intelligence Model Nameplate Version 1.0." IDTA 02060-1-0.
- url: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Artificial%20Intelligence%20Model%20Nameplate/1/0
- year: 2025
- authors: Industrial Digital Twin Association
- venue: IDTA Submodel Template Specification

## 1. 핵심 요약
- AI model 자체의 정보를 상호운용 가능한 AAS property 구조로 문서화한다.
- 모델 lifecycle 관리와 이미 학습된 모델의 재사용을 지원하는 것이 목적이다.
- 공식 template은 모델 정보, 학습 방식, input·input data·dimension·preprocessing·output 등의 구역을 둔다.

## 2. 문서 목적
가치 네트워크의 파트너가 AI model 정보를 의미 있게 교환하고, 모델 문서화·lifecycle 관리·재사용을 돕는다.

## 3. 핵심 개념 상세
- **Model information:** 모델 식별과 설명 정보를 제공한다.
- **Learning:** 모델의 학습 관련 정보를 기술한다.
- **Inputs/Outputs:** 입력 종류와 차원, preprocessing 및 출력 정보를 구조화한다.
- **Responsible person:** 모델 책임자와 추가 정보 획득 경로를 제공한다.

## 4. 구조 및 흐름
model nameplate가 모델의 비교적 안정적인 정보를 보유하고, deployment 정보는 별도 AI Deployment submodel에서 관리한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 모델 문서화는 배포와 독립된 lifecycle 대상이다 | 독립된 Model Nameplate와 Deployment submodel이 각각 발행됨 |
| 재사용이 명시적 목표다 | scope가 already trained models의 reuse를 지원한다고 명시 |

## 6. 한계 및 부족한 점
- 현재 실행 인스턴스의 health나 자원 부하는 model nameplate의 책임이 아니다.
- 모델 성능의 공정한 측정 절차나 serving API를 정의하지 않는다.

## 7. 원문 기반 핵심 문장
> “It targets to assist the AI model documentation and helps to manage an AI lifecycle.”
