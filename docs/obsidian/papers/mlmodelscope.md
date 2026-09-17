# MLModelScope

## 메타데이터
- categories: DL Benchmarking, Execution Profile, Reproducibility
- domain: [[엣지 실행·자원]]
- source: Li et al. "The Design and Implementation of a Scalable DL Benchmarking Platform."
- url: https://arxiv.org/abs/1911.08031
- year: 2020
- authors: Cheng Li, Abdul Dakkak, Jinjun Xiong, Wen-mei Hwu
- venue: IEEE CLOUD 2020, 414–425

## 1. 핵심 요약
- framework·hardware에 독립적인 분산 DL benchmarking platform을 제안한다.
- 평가 specification, workflow provisioning, scheduling, framework abstraction, cross-stack tracing, automated analysis를 제공한다.
- 37개 model과 4개 system의 사례로 model·hardware·framework 선택이 정확도와 성능에 영향을 줌을 보였다.

## 2. 연구 목적
비균질 model과 HW/SW stack을 일관되고 재현 가능하며 확장 가능한 방식으로 평가하기 어려운 문제를 해결한다.

## 3. 핵심 개념 상세
- **Evaluation specification:** model, dataset, framework, system 조건을 명시한다.
- **Agent:** 지정된 system에서 preprocessing, inference, postprocessing을 수행한다.
- **Framework predictor:** framework별 차이를 공통 API로 감싼다.
- **Across-stack tracing:** HW/SW 추상화 계층의 실행을 관찰한다.

## 4. 구조 및 흐름
client 요청을 server가 evaluation task로 만들고 적합한 agent에 배정한다. agent는 framework predictor로 workload를 실행하고 결과와 trace를 분석 pipeline에 전달한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 동일 model도 HW/SW 선택에 따라 결과가 달라진다 | 논문의 37 model×4 system case study |
| 평가 조건을 specification으로 고정한다 | 논문 초록과 공식 문서가 evaluation specification을 핵심 기능으로 명시 |

## 6. 한계 및 부족한 점
- benchmarking platform이며 runtime task selector나 안전 제어 protocol은 아니다.
- 내장 framework와 system 지원 범위는 구현 시점에 따라 달라질 수 있다.

## 7. 원문 기반 핵심 문장
> “MLModelScope proposes a specification to define DL model evaluations.”
