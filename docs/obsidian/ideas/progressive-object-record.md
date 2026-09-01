# Progressive On-Device Object Records from Heterogeneous Models for Digital Twin Construction

## 상태

이 문서는 **내 연구 논문/아이디어**이며, KCI 확장 연구가 재현해야 하는 외부 기존 연구(baseline)가 아니다.

`kci-reference-plan.md`의 기술 문서 목록에서 제외했다. 원문 PDF: [progressive-object-record.pdf](progressive-object-record.pdf)

## 역할

먼저 외부 기존 연구(Reference Baseline)들을 원 저자 설정 그대로 재현해 기능별 기준선을 확보한 뒤, 그 기준선 위에서 **실험을 통해 이득이 확인되는 경우에만** 아래 아이디어를 적용 여부를 판단한다. 자동으로 시스템 기반 구조로 채택되는 것이 아니라, 채택 여부는 실험 결과를 본 뒤 내가 직접 결정한다.

## 핵심 특징

- 수행 task와 출력 형식이 다른 heterogeneous perception 결과를 공통 Evidence 형태로 정규화한다.
- 개별 frame 결과가 아니라 동일 물리 객체에 대응하는 persistent object record를 유지한다.
- Observation, Evidence, Object 관계를 분리한다.
- 서로 다른 시점에 완료되는 결과를 하나의 객체 record에 점진적으로 통합한다.
- geometry, semantic class, lifecycle, time 정보를 지속 상태로 관리한다.
- source group 기반 semantic support를 사용하여 단순 Last-Writer-Wins보다 반복적인 class update를 줄인다.
- visible state가 실제로 변화한 경우에만 외부 object update를 노출한다.
- 기존 평가에서는 cached heterogeneous model outputs를 같은 coordinator에 replay하여 resolver 차이를 통제하였다.

## 실험해볼 구성요소 (적용 확정 아님)

- Observation schema
- Evidence schema
- Persistent Object ID
- Object lifecycle
- Heterogeneous provider result normalization
- Cached result replay 실험 방식
- State-change 기반 record update 구조
- Provider provenance와 completion time 기록 방식

## 실험해볼 확장 방향 (적용 확정 아님)

새 KCI 연구에서 시도해볼 수 있는 방향은 이 구조를 특정 detector 조합에 고정하지 않고 Provider-Agnostic Object Record로 여는 것이다.

새로운 Provider가 다음과 같은 정보를 제공할 수 있도록 Evidence 종류를 확장하는 실험을 해볼 수 있다.

- unknown object evidence
- open-vocabulary semantic evidence
- attribute evidence
- OCR evidence
- segmentation evidence
- depth evidence
- tracking evidence
- infrastructure evidence
- Provider performance prediction result

원 논문의 resolver 자체를 정답으로 고정하지 않고, 다른 association, tracking, semantic inference 또는 execution policy와 교체 가능한 형태로 실험해볼 수 있다.

## 검증해볼 가설 (적용 확정 아님)

- frame 단위 처리와 persistent object 단위 처리의 차이가 실제로 있는가
- 같은 객체에서 Provider 결과를 재사용했을 때 무엇이 달라지는가
- 여러 Provider 결과가 object record에 누적될 때 비용이 어떻게 변하는가
- Provider 선택 policy가 object record의 누적 정보를 사용하는 경우와 사용하지 않는 경우에 차이가 있는가

각 항목은 baseline 재현 이후, 동일 조건 비교 실험에서 실제 이득이 확인된 경우에만 KCI 제안 방법 후보로 남긴다. 이득이 없으면 채택하지 않는다.
