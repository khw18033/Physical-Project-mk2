# CTPNet: Achieving Real-Time Semantic Segmentation on Resource-Constrained Edge Devices for Autonomous Driving

## 메타데이터
- categories: Real-Time Semantic Segmentation, Resource-Constrained Edge Deployment
- domain: [[객체 탐지·분할]]
- source: Atif, Nadeem, Mazhar, Saquib, Ameen, Mohammed, Ahamed, Shaik Rafi, Bhuyan, M.K. "CTPNet: Achieving Real-Time Semantic Segmentation on Resource-Constrained Edge Devices for Autonomous Driving." IEEE Transactions on Circuits and Systems I: Regular Papers, vol. 73, no. 6, pp. 4322-4335, 2026.
- url: https://doi.org/10.1109/tcsi.2025.3649392
- year: 2026
- authors: Nadeem Atif, Saquib Mazhar, Mohammed Ameen, Shaik Rafi Ahamed, M.K. Bhuyan
- venue: IEEE Transactions on Circuits and Systems I: Regular Papers (vol. 73, no. 6, pp. 4322-4335)

## 1. 핵심 요약
- 이 논문은 자율주행 맥락에서 자원 제약이 큰 엣지 장치 위에서 실시간으로 동작하는 semantic segmentation 네트워크 CTPNet을 제안한다(논문 제목 기준으로 확인됨).
- 저자 소속은 인도공과대학교 구와하티(IITG) 전자전기공학과이며, 같은 연구 그룹은 SLICENet(FPGA 기반 경량 segmentation), DECoDeNet(임베디드용 accuracy-efficiency trade-off), CGMANet(도로 장면 실시간 semantic segmentation을 위한 context-guided multiscale attention) 등 저지연·저자원 semantic segmentation 계열 연구를 지속적으로 발표해 왔다(발행 목록 기준으로 확인됨).
- 원 논문 본문(초록·방법론·실험 결과 포함)은 IEEE Xplore 유료 접근 제한으로 인해 이번 조사에서는 직접 확인하지 못했다. Crossref·Unpaywall 조회 결과 이 논문에는 오픈 액세스 사본이 존재하지 않는다("is_oa": false).
- 따라서 아래 2~7절 중 본문 내용에 기반해야 하는 항목들은 논문 제목과 확인된 서지정보 범위 내에서만 서술하며, 확인되지 않은 구체적 아키텍처·수치·주장은 포함하지 않는다.

## 2. 문서 목적
- 해결하려는 문제: 논문 제목이 명시하는 범위에서, 자율주행에 사용되는 semantic segmentation 모델을 연산·메모리가 제한된 엣지 장치에서 실시간으로 구동해야 하는 문제로 추정된다. (원문 확인 안 됨 — 제목 기반 추정)
- 기술적 목표: 원문 확인 안 됨.
- 다루는 범위: 원문 확인 안 됨. 서지정보로 확인되는 범위는 IEEE Transactions on Circuits and Systems I: Regular Papers 73권 6호(2026)에 4322-4335쪽으로 게재되었다는 사실뿐이다.

## 3. 핵심 개념 상세

### Real-Time Semantic Segmentation
- 원문 표현: 원문 확인 안 됨.
- 정의: 원문 확인 안 됨. 논문 제목에 명시된 용어이며, 일반적으로는 입력 영상의 각 픽셀을 실시간 처리 속도로 클래스별로 분류하는 task를 가리킨다.
- 역할: 원문 확인 안 됨.

### Resource-Constrained Edge Deployment
- 원문 표현: 원문 확인 안 됨.
- 정의: 원문 확인 안 됨. 논문 제목에 명시된 용어이며, 일반적으로는 서버급 GPU가 아닌 연산·메모리·전력이 제한된 엣지 하드웨어에서 모델을 구동하는 배포 조건을 가리킨다.
- 역할: 원문 확인 안 됨.

## 4. 구조 및 흐름
- 원문 확인 안 됨. IEEE Xplore 원문 접근이 차단되어(HTTP 403/202 응답, 로그인 요구) 네트워크 아키텍처, encoder-decoder 구성, 손실 함수 등 방법론 세부사항을 확인할 수 없었다. Crossref 메타데이터에서는 43개의 참고문헌 목록만 확인되며, 이 중 다수가 실시간 semantic segmentation·efficient convolution·attention 관련 선행 연구(DABNet, SegFormer, ENet 등)로, CTPNet이 이 계열의 경량 segmentation 연구 흐름에 속함을 간접적으로 시사한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 원문 확인 안 됨 | 원문 확인 안 됨 |

이 표는 원 논문의 초록·본문에 접근하지 못해 채울 수 없었다. 확인된 것은 서지정보(저자, 소속, 게재 저널·권·호·페이지, 게재년도, DOI)뿐이며, 성능 수치나 구체적 기술 주장은 확인되지 않은 상태에서 임의로 작성하지 않았다.

## 6. 한계 및 부족한 점
- 이 문서 작성 시점에 IEEE Xplore(ieeexplore.ieee.org/document/11359993)는 로그인 없이는 초록조차 제공하지 않았고, IEEE 스테이징 PDF 서버 접근도 봇 차단(HTTP 418)으로 실패했다.
- Semantic Scholar API는 반복 조회 시 요청 제한(HTTP 429)으로 응답하지 않았고, ResearchGate·Bing 검색에서도 초록 스니펫을 확인할 수 없었다.
- Unpaywall 조회 결과 이 논문은 오픈 액세스 사본이 존재하지 않는 완전 폐쇄형(closed) 게재물로 확인되었다.
- 따라서 이 문서는 다른 4개 문서와 달리 원문 인용·구체적 수치·아키텍처 설명을 포함하지 못했다. 후속 조사에서 기관 구독 등을 통해 원문에 접근할 수 있다면 이 문서를 갱신해야 한다.

## 7. 원문 기반 핵심 문장
> 원문 확인 안 됨.
