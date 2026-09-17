# ASDMR: Adaptive Scheduling of DNN Models and Resources for Collaborative Edge-Cloud Video Analytics

## 메타데이터
- categories: DNN 모델·해상도·오프로딩 공동 스케줄링, Edge-Cloud Video Analytics, Lyapunov 최적화 기반 온라인 스케줄링
- domain: [[엣지 실행·자원]]
- source: Liang, Yanfen, Gao, Guanyu. "ASDMR: Adaptive Scheduling of DNN Models and Resources for Collaborative Edge-Cloud Video Analytics." 2025 IEEE 31st International Conference on Parallel and Distributed Systems (ICPADS), 2025.
- url: https://doi.org/10.1109/ICPADS67057.2025.11323168
- year: 2025
- authors: Yanfen Liang, Guanyu Gao (Nanjing University of Science and Technology, China)
- venue: IEEE 31st International Conference on Parallel and Distributed Systems (ICPADS), Hefei, China (2025-12-14)

## 1. 핵심 요약
- 이 문서는 논문 원문(abstract 포함)에 직접 접근하지 못한 상태에서 작성되었다. IEEE Xplore 페이지는 JS 렌더링 콘텐츠만 반환해 본문을 확보할 수 없었고, Semantic Scholar API는 요청 제한(HTTP 429)으로 실패했다. 아래 요약은 Crossref/OpenAlex로 확인한 서지 메타데이터와, 검색엔진(WebSearch)이 색인된 스니펫으로부터 재구성한 설명에 근거한다 — 논문 원문의 정확한 문장과 일치한다는 보장이 없으므로 직접 인용으로 취급하지 않는다.
- 검색엔진 기반 설명에 따르면, edge-cloud 협업 비디오 분석은 정확도·지연·자원 비용 사이의 트레이드오프를 가진다는 문제의식에서 출발한다(클라우드 중심 처리는 대역폭·지연 부담이 크고, 엣지 단독 처리는 연산력이 제한적).
- ASDMR은 이종 엣지 노드에서의 모델 선택, 로컬/엣지-엣지/클라우드 중 실행 위치 결정, 해상도 스케일링, 콘텐츠 인지 기반 결과 재사용, 부하 기반 프레임 필터링을 함께 온라인으로 조정한다고 알려져 있다.
- 장기 시스템 유틸리티 극대화를 위한 다목적 최적화 문제로 정식화하고, Lyapunov 최적화로 장기 확률적 문제를 시간슬롯 단위 결정적 부분문제로 분해해 온라인으로 푸는 접근을 취한다고 알려져 있다.
- 서지 메타데이터(Crossref/OpenAlex)로 확인된 사실: 저자는 난징이공대학(Nanjing University of Science and Technology, China) 소속 Yanfen Liang(1저자), Guanyu Gao(교신·2저자)이며, 논문은 10페이지(pp.1-10), ICPADS 2025(2025-12-14, Hefei 개최)에 게재되었다.

## 2. 문서 목적
- 해결하려는 문제(검색엔진 기반 재구성): edge-cloud 협업 비디오 분석에서 accuracy-latency-resource cost 간 트레이드오프를 정적 설정이 아니라 실시간으로 함께 조정하는 문제.
- 기술적 목표(검색엔진 기반 재구성): DNN model selection, execution location(local/edge-to-edge/cloud), resolution, frame filtering 등 여러 노브를 하나의 온라인 스케줄링 문제로 통합해 장기 유틸리티를 최적화하는 프레임워크를 설계하는 것.
- 다루는 범위: 확인 가능한 수준은 다목적 최적화 문제 정식화와 Lyapunov 기반 온라인 분해 기법 적용이라는 것뿐이다. abstract 이상의 본문 상세(구체적 실험 설정, 수치 결과, 관련 연구 비교, 알고리즘 의사코드)는 확인하지 못했다.

## 3. 핵심 개념 상세

### Joint Model-Location-Resolution-Filtering 스케줄링
- 원문 표현: 원문 확인 안 됨 (IEEE Xplore 원문 접근 불가로 abstract 원문 직접 인용 불가)
- 정의(검색엔진 기반 재구성, 검증 신뢰도 낮음): 모델 선택, 실행 위치(로컬/엣지-엣지/클라우드), 해상도, 프레임 필터링 등 서로 다른 계층의 조정 노브를 단일 온라인 의사결정으로 묶어 조정하는 방식.
- 역할: 모델만, 또는 오프로딩 위치만 조정하는 단일 노브 접근과 달리, 여러 노브를 동시에 조정해 정확도-지연-비용 트레이드오프 공간을 더 넓게 탐색하는 적응형 비디오 분석 설계 패턴 일반에 해당한다.

### Lyapunov 최적화 기반 온라인 분해
- 원문 표현: 원문 확인 안 됨
- 정의(검색엔진 기반 재구성, 검증 신뢰도 낮음): 장기간에 걸친 확률적 최적화 문제를 매 시간슬롯 단위의 결정적 부분문제로 분해해 온라인으로 순차적으로 푸는 기법.
- 역할: 미래 정보 없이도 장기 목표(예: 누적 유틸리티)를 안정적으로 최적화할 수 있게 해주는, 네트워크·자원 스케줄링 분야에서 널리 쓰이는 온라인 제어 기법이다.

### 부하 기반 프레임 필터링·콘텐츠 인지 결과 재사용
- 원문 표현: 원문 확인 안 됨
- 정의(검색엔진 기반 재구성, 검증 신뢰도 낮음): 시스템 부하가 높을 때 처리할 프레임 수를 줄이고, 콘텐츠가 유사한 경우 이전 인지 결과를 재사용하는 기법.
- 역할: 모든 프레임을 동일하게 처리하는 대신 부하·콘텐츠 변화에 따라 처리량을 조절해 자원을 절약하는, 비디오 분석 시스템에서 흔히 쓰이는 최적화 기법 일반에 해당한다.

## 4. 구조 및 흐름
abstract 수준의 정보만으로는 상세한 파이프라인 단계(센싱→스케줄링→실행→피드백)를 정확히 재구성하기 어렵다. 검색엔진 요약에 따르면 "매 시간슬롯마다 Lyapunov 기반 온라인 결정 문제를 풀어 모델·실행위치·해상도·필터링을 갱신하는" 구조로 추정되나, 본문 원문을 확인하지 못했으므로 확정적으로 서술하지 않는다.

## 5. 핵심 주장과 근거

| 항목 | 확인 여부 |
|------|----------|
| 논문 제목·저자·소속·venue·게재일·DOI | Crossref, OpenAlex API로 확인됨 |
| Abstract 전문 | 확인 안 됨 (IEEE Xplore 접근 실패, Semantic Scholar API 요청 제한으로 실패) |
| 구체적 실험 설정·baseline·수치 결과 | 확인 안 됨 |
| "장기 유틸리티 극대화 다목적 최적화 + Lyapunov 온라인 분해" 설계 | 원문 미확인, 검색엔진 재구성 설명에만 근거(신뢰도 낮음) |

## 6. 한계 및 부족한 점
- IEEE Xplore 문서 페이지(https://ieeexplore.ieee.org/document/11323168/)는 WebFetch로 접근해도 JS 렌더링 셸만 반환되어 abstract 원문을 확보하지 못했다.
- Semantic Scholar API(api.semanticscholar.org)는 두 차례 시도 모두 HTTP 429(Too Many Requests)로 실패했다.
- Crossref API(api.crossref.org)와 OpenAlex API(api.openalex.org)로 제목, 저자(Yanfen Liang, Guanyu Gao, 난징이공대학), 게재일(2025-12-14), 페이지(1-10), DOI는 확인했지만, 두 API 모두 abstract 텍스트 자체는 제공하지 않았다. OpenAlex 응답에는 `"has_fulltext": false`, `"open_access": {"is_oa": false}`로 명시되어 있어 폐쇄 접근(closed access) 논문임을 확인했다.
- WebSearch 결과로 얻은 설명은 검색엔진이 색인된 스니펫들을 종합해 재구성한 요약으로, 논문 원문의 정확한 문장과 일치한다는 보장이 없어 "원문 표현"으로 인용하지 않고 모두 "검색엔진 기반 재구성"으로 표시했다.
- 따라서 이 문서의 1, 2, 3절 서술 내용은 검증 신뢰도가 낮다. 정확한 인용이 필요하면 IEEE Xplore 구독 접근이나 저자 소속기관 페이지에서 원문을 재확인해야 한다.

## 7. 원문 기반 핵심 문장
> 원문 확인 안 됨 (abstract 원문 접근 실패로 직접 인용 불가)
