# Autonomous View Planning Methods for 3D Scanning

## 메타데이터
- categories: Next Best View, Autonomous View Planning, 3D Scanning Review, Robot-based 3D Reconstruction
- domain: [[로보틱스·다중로봇]], [[3D 인지]]
- source: Lee, Inhwan Dennis; Seo, Ji Hyun; Yoo, Byounghyun. "Autonomous view planning methods for 3D scanning." Automation in Construction, Volume 160, 2024, Article 105291.
- url: https://doi.org/10.1016/j.autcon.2024.105291
- year: 2024
- authors: Inhwan Dennis Lee, Ji Hyun Seo, Byounghyun Yoo
- venue: Automation in Construction (Elsevier, Scopus/Web of Science 색인 확인)

## 1. 핵심 요약
- 3D 스캐닝 기술의 발전이 리버스 엔지니어링, 자율 로봇 내비게이션 등 여러 분야로 적용 범위를 넓혀가는 가운데, 미지 또는 부분적으로만 알려진 형상(unknown or partially known geometries)을 대상으로 한 자율 뷰 플래닝(autonomous view planning) 기법들을 포괄적으로 검토(review)하는 논문이다.
- Automation in Construction 160권(2024)에 게재되었고, Scopus·Web of Science에 색인되어 있으며 149개 참고문헌을 인용한 리뷰 논문으로 확인된다(ouci.dntb.gov.ua 서지 정보 기준).
- 저자는 한국과학기술연구원(KIST)/고려대학교 소속의 Inhwan Dennis Lee, Ji Hyun Seo, Byounghyun Yoo다(웹 검색 결과 기준; 소속 표기는 이번 조회에서 논문 원문 1차 확인은 아님 — §6 참고).

## 2. 문서 목적
- 해결하려는 문제: 미지 또는 부분적으로만 알려진 물체·환경의 완전하고 고품질인 3D 형상을 획득하려면 다음에 어디를 스캔할지(Next Best View, NBV)를 자율적으로 결정해야 하는데, 이 결정 방법론들이 로봇공학·컴퓨터 비전 등 여러 분야에 흩어져 있어 통합적으로 정리한 리뷰가 필요하다는 문제.
- 기술적 목표: NBV 문제를 포함한 자율 뷰 플래닝 기법들을 model-based/non-model-based 등 분류 체계로 정리하고, object representation·candidate viewpoint proposal·optimal viewpoint selection의 3대 구성요소로 구조화해 검토하는 것(WebSearch로 확인된 요약 기준).
- 다루는 범위: 문화유산 디지털화, 산업 부품 검사, 실내 환경 매핑, 대규모 구조물 재구성 등 다양한 응용 분야에 걸친 뷰 플래닝 연구 149편의 리뷰(ouci.dntb.gov.ua 서지 정보 기준). 원문 전체 본문은 ScienceDirect·ResearchGate 접근이 차단되어 이번 조회에서 직접 확보하지 못했다(§6).

## 3. 핵심 개념 상세

### Next Best View (NBV) Planning
- 정의: 이미 관측된 데이터를 활용해 물체를 완전히 스캔하기 위한 다음 최적 촬영 시점(viewpoint)을 결정하는 문제. Connolly가 최초로 이 전략을 제시한 것으로 리뷰가 소개한다(WebSearch로 확인된 요약).
- 역할: 이 리뷰 논문 전체의 핵심 축으로, 이후 연구들이 이 문제를 object representation, candidate viewpoint proposal, optimal viewpoint selection의 3가지 구성요소로 점차 세분화해 모델링해 왔다고 정리한다.

### Model-based vs. Non-model-based 접근
- 정의: model-based 접근은 스캔 대상의 충분한 기하 정보가 사전에 주어져 전체 스캔 경로를 미리 계산할 수 있는 방식이고, non-model-based(추정) 접근은 사전 기하 정보 없이 관측을 진행하며 다음 시점을 결정하는 방식으로 대비된다(WebSearch 요약 기준, 원문 문단 전체 미확인).
- 역할: 리뷰가 기존 자율 뷰 플래닝 연구들을 분류하는 상위 기준으로 사용하는 것으로 파악된다.

### 응용 도메인 다양성
- 정의: 문화유산 디지털화, 산업 부품 검사, 실내 환경 매핑, 대규모 구조물 재구성 등 서로 다른 도메인에서의 뷰 플래닝 적용 사례.
- 역할: 이 리뷰가 특정 응용 하나에 국한되지 않고 3D 스캐닝 뷰 플래닝이라는 방법론 자체를 도메인 횡단적으로 정리한다는 점을 보여준다 — 이 저장소의 "도메인·배포 프로파일 분리"(AI-C-15) 관점과 참고할 만한 지점이다.

## 4. 구조 및 흐름
- 이번 확인 범위(서지 정보 사이트 ouci.dntb.gov.ua, ResearchGate/ScienceDirect 메타데이터, WebSearch 요약)에서 파악한 대략적 흐름은: (1) 3D 스캐닝 기술 발전과 응용 확대 소개 → (2) 자율 뷰 플래닝의 정의와 NBV 문제의 역사(Connolly의 최초 제안부터) → (3) NBV를 구성하는 3대 요소(object representation/candidate viewpoint proposal/optimal viewpoint selection) 기준의 기존 연구 분류 → (4) model-based/non-model-based 등 방법론적 분류 → (5) 문화유산·산업검사·실내매핑·대규모구조물 등 응용 사례 정리.
- 논문 본문의 세부 절 구성, 각 절의 정확한 소제목, 표·그림, 결론에서의 향후 연구 방향은 원문 전체를 확보하지 못해 이번 문서에서는 다루지 않는다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 자율 뷰 플래닝은 NBV 문제를 중심으로 발전해 왔으며, 이 문제는 object representation·candidate viewpoint proposal·optimal viewpoint selection 3요소로 점차 구조화되었다 | WebSearch로 확인된 논문 요약: "As research on the NBV planning problem advanced, it was gradually modeled into three core components: object representation, candidate viewpoint proposal, and optimal viewpoint selection." (원문 verbatim 여부는 미확인, §6) |
| 완전하고 고품질인 3D 형상 획득은 리버스 엔지니어링·품질검사·로봇의 자율 탐색과 상호작용에 공통적으로 중요하다 | WebSearch로 확인된 논문 요약: "Acquiring the complete and high-quality 3D geometric structure of an object is crucial for reverse engineering and quality inspection in industrial applications, as well as for autonomous exploration and interaction in robotics." (원문 verbatim 여부는 미확인, §6) |

## 6. 한계 및 부족한 점
- **원문 전체 미확보**: ScienceDirect(sciencedirect.com/science/article/pii/S092658052400027X)는 403/HTML 차단으로, ResearchGate 저자 업로드 PDF(researchgate.net/profile/Byounghyun-Yoo/.../Autonomous-view-planning-methods-for-3D-scanning.pdf)는 curl과 WebFetch 양쪽 모두 403으로 접근이 차단되었다. 이번 문서의 내용은 (a) ouci.dntb.gov.ua의 서지 메타데이터 페이지(제목·저자·저널·DOI·인용수·참고문헌수·색인 여부), (b) WebSearch 결과에 포함된 논문 요약 스니펫에 근거한다.
- **저자 소속기관**: Inhwan Dennis Lee, Ji Hyun Seo, Byounghyun Yoo가 KIST/고려대 소속이라는 정보는 WebSearch 결과 요약에서 나온 것으로, 논문 원문 1페이지(저자 소속 각주)를 직접 확인한 것이 아니다 — 참고 수준으로만 취급해야 한다.
- **"원문 기반 핵심 문장" 신뢰도**: §7의 인용문은 WebSearch 도구가 논문 내용을 요약하며 생성한 문장으로, 논문 원문의 정확한 verbatim 문장인지 이번 조회로는 검증하지 못했다 — 일반적인 학술 리뷰 서술과 부합하는 내용이지만, 향후 원문 PDF를 별도 경로(기관 접근, 저자 요청 등)로 확보해 재검증이 필요하다.
- 정량적 내용(예: 분류 체계 표, 방법별 비교표, 결론의 gap 분석)은 이번 조회 범위에서 확인하지 못했다.
- 이 논문은 KICT(한국건설기술연구원)가 아니라 저자 소속(KIST/고려대 추정)의 3D 스캐닝 뷰 플래닝 리뷰이며, 사용자가 원래 "KICT 관련 논문"으로 분류했던 것과 달리 소속기관 확인이 완전하지 않다는 점에 유의해야 한다.

## 7. 원문 기반 핵심 문장
> 이번 조회에서는 원문 PDF에 직접 접근하지 못해 100% 확실한 verbatim 인용을 제공할 수 없다. 대신 WebSearch 결과에 포함된, 논문 내용에 대한 요약 스니펫(원문 여부 미확증)만 아래에 참고로 남긴다.
>
> "Recent advancements in 3D scanning technology have broadened its applicability across fields like reverse engineering and autonomous robot navigation, with autonomous view planning being a key aspect of this digitalization process." (WebSearch 요약 스니펫, 원문 verbatim 여부 미확인)
