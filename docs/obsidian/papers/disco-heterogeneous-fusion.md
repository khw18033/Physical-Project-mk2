# DisCo: Facilitating Heterogeneous Sensor Information Cooperation in Multi-Agent Perception System

> **다른 논문과의 구분 주의**: 이 저장소에는 이름이 비슷한 [[disconet]] ("Learning Distilled Collaboration Graph for Multi-Agent Perception", DiscoNet, NeurIPS 2021, matrix-valued collaboration graph + knowledge distillation)가 이미 존재한다. 이 문서가 다루는 논문은 **완전히 다른, 2026년에 발표된 별개의 논문**이며 저자·내용·venue가 모두 다르다. 짧은 이름이 "DisCo"로 우연히 겹칠 뿐 DiscoNet과 직접적인 관계는 확인되지 않았다(논문 본문 접근 불가로 상호 인용 여부도 미확인).

## 메타데이터
- categories: 이종 센서·모달리티 융합, 공유 협업 특징 공간 투영, 동적 에이전트 구성 강건성(미확인)
- domain: [[협력 인지]]
- source: Zhao, Binyu, Zhang, Wei, Zou, Zhaonian. "Facilitating heterogeneous sensor information cooperation in multi-agent perception system." Information Sciences, Volume 749, Article 123529, 2026.
- doi: 10.1016/j.ins.2026.123529
- url: https://doi.org/10.1016/j.ins.2026.123529 (원문: https://www.sciencedirect.com/science/article/pii/S0020025526004603)
- year: 2026
- authors: Binyu Zhao, Wei Zhang, Zhaonian Zou (Harbin Institute of Technology, School of Computer Science and Technology, Harbin, China)
- venue: Information Sciences (Elsevier, ISSN 0020-0255), Volume 749, article no. 123529
- code: https://github.com/byzhaoAI/DisCo (상태: 스텁 저장소 — 아래 6절 참조)

## 1. 핵심 요약
- **확인된 사실만**: 이 논문은 Elsevier 저널 *Information Sciences* Volume 749(2026)에 article number 123529(DOI 10.1016/j.ins.2026.123529)로 게재되었다. CrossRef·OpenAlex·Semantic Scholar(DBLP ID: journals/isci/ZhaoZZ26) 세 개의 독립된 서지 데이터베이스에서 제목·저자·저널·권호가 모두 일치해 서지사항 자체는 신뢰도 높게 확인된다.
- 저자 Binyu Zhao는 CrossRef 참고문헌 목록에 본인의 선행 연구 "BM2CP: efficient collaborative perception with lidar-camera modalities" (CoRL 2023, arXiv:2310.14702)를 인용하고 있어, GitHub 계정 `byzhaoAI`(BM2CP 저장소 실제 소유자)와 동일 인물임이 정황상 확인된다. 즉 이 논문은 LiDAR-카메라 이종 모달리티 협업 인지를 다뤄온 저자의 후속 연구로 보인다.
- **본문·초록 접근 실패**: ScienceDirect 원문 페이지는 봇 차단 캡차("Are you a robot?")로 직접 접근이 차단되었고(WebFetch·curl·jina.ai 리더 프록시 모두 동일하게 차단됨), CrossRef/OpenAlex/Semantic Scholar 어디에도 초록 텍스트가 색인되어 있지 않다(OpenAlex `abstract_inverted_index`는 null, `is_oa: false`, `has_fulltext: false`). arXiv에 대응하는 프리프린트도 검색되지 않았다. 따라서 **MFI/MFP의 정확한 정의, 동적 에이전트 참여/이탈 처리 방식, 정량적 실험 결과는 이 문서 작성 시점 기준 원문으로 검증하지 못했다.**
- OpenAlex가 논문에서 자동 추출한 키워드는 robustness, fuse, perception, feature, projection, code, modality이며, 이는 "이종 모달리티를 특징 수준에서 융합(fuse)하고 공유 공간으로 투영(projection)해 강건성(robustness)을 확보한다"는 제목·과제 설명과 방향은 일치하지만, 이는 자동 개념 태깅일 뿐 초록 원문이 아니므로 근거로 사용하지 않는다.

## 2. 문서 목적
- 해결하려는 문제(제목 기준 추정): 서로 다른 센서 모달리티를 사용하는 이종 에이전트들이 참여하는 multi-agent perception 시스템에서 센서 정보를 효과적으로 협업(cooperation)시키는 문제.
- 사용자가 사전에 제시한 가설(원문 미확인, 검증 대상으로만 취급): "MFI(per-agent internal fusion, 에이전트 내부 모달리티 융합으로 추정)"와 "MFP(공유 협업 공간으로의 투영)"라는 두 메커니즘을 사용한다는 주장이 있었으나, **초록 원문을 확보하지 못해 이 명칭·정의를 확인도 반박도 할 수 없었다.** 아래 3절에서 확인 상태를 명시한다.
- 다루는 범위(정황 근거): CrossRef 참고문헌 목록에 BM2CP(LiDAR-카메라 협업), HM-ViT(hetero-modal V2V), HEAL(An Extensible Framework for Open Heterogeneous Collaborative Perception), Where2comm, V2X-ViT 등 최근 이종 협업 인지 문헌이 포함되어 있어, 이 논문도 동일 계열의 "이종 센서/모델 조합에서의 협업 인지 프레임워크" 문제를 다루는 것으로 추정된다(원문 미확인).

## 3. 핵심 개념 상세

### MFI, MFP — 확인 상태: **미확인 (Unconfirmed)**
- 사용자가 제시한 가설: MFI = "per-agent internal fusion"(에이전트 내부 융합), MFP = "projection into a shared collaboration space"(공유 협업 공간 투영).
- 검증 시도: ScienceDirect 원문(캡차 차단), CrossRef 레코드(초록 없음), OpenAlex 레코드(초록 없음, `abstract_inverted_index: null`), Semantic Scholar 레코드(`abstract: null`), arXiv 프리프린트 검색(해당 논문의 프리프린트 발견 안 됨) 모두에서 MFI/MFP라는 약어 자체를 확인할 수 있는 원문 텍스트를 찾지 못했다.
- 결론: **이 두 메커니즘의 정확한 명칭, 전체 스펠아웃, 내부 동작 방식은 이 문서에서 확인·서술하지 않는다.** OpenAlex 자동 키워드(fuse, feature, projection, modality)가 "모달리티별 특징 융합"과 "공유 공간으로의 투영"이라는 방향성과 대체로 부합하기는 하지나, 이는 약어의 존재나 정의를 뒷받침하는 근거로 삼기에는 불충분하다(자동 개념 태깅은 초록 재구성이 아님).

### 동적 에이전트 참여/이탈 및 모달리티 손실 대응 — 확인 상태: **미확인 (Unconfirmed)**
- 사용자가 제시한 질문: 에이전트가 동적으로 합류/이탈하거나 특정 모달리티를 잃었을 때 시스템이 어떻게 대응하는지.
- 검증 시도 결과: 위와 동일한 이유로 원문·초록에 접근하지 못해 실제 주장 내용을 확인할 수 없었다. 다만 CrossRef 참고문헌에 포함된 동시대 관련 연구(HEAL "open heterogeneous collaborative perception", Zhang 2025 "Selective shift: towards personalized domain adaptation in multi-agent collaborative perception")의 존재로 미루어 볼 때, 이 논문이 새로운 에이전트/모달리티 조합에 대한 적응(domain adaptation) 또는 확장성을 다룰 개연성은 있으나 이는 정황적 추정일 뿐 논문 자체의 주장으로 서술할 수 없다.
- 결론: 이 항목은 **"확인 불가"로 명시**하며, 추후 원문 접근이 가능해지면 갱신이 필요하다.

## 4. 구조 및 흐름
- **확인 불가**: 초록·본문에 접근하지 못해 논문의 파이프라인 단계, 모듈 구성, 학습 절차를 서술할 근거가 없다. 임의로 구성을 추정해 서술하지 않는다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| (확인 불가) | 원문 실험 결과·수치를 확보하지 못했다. ScienceDirect 캡차 차단, CrossRef/OpenAlex/Semantic Scholar에 초록 미색인, 대응 arXiv 프리프린트 부재로 인해 정량적 주장-근거 표를 채울 수 없다. |

## 6. 한계 및 부족한 점
- **접근 경로 전부 실패**: (1) WebFetch로 ScienceDirect 직접 접근 → HTTP 403. (2) curl + 브라우저 User-Agent로 재시도 → HTTP 403, 응답 본문은 Cloudflare/Elsevier 봇 차단 캡차 페이지("Are you a robot?", reference number 포함)였다. (3) jina.ai 리더 프록시 경유 → 동일하게 캡차 페이지만 반환. (4) CrossRef API → 서지 메타데이터(제목/저자/권/호/DOI/날짜/참고문헌 28건)는 확보했으나 초록 필드 없음. (5) OpenAlex API → `abstract_inverted_index: null`, `is_oa: false`, `has_fulltext: false`로 초록·전문 모두 폐쇄. (6) Semantic Scholar API → `abstract: null`, OA PDF 링크 없음. (7) arXiv API/검색 → 이 논문에 대응하는 프리프린트를 찾지 못함. 따라서 이 문서는 **서지사항과 GitHub 저장소 상태만 1차 확인**했고, 논문의 실제 기술 내용(MFI/MFP 정의, 방법론, 실험, 주장)은 검증하지 못한 상태로 남긴다.
- **발행일 관련 수정**: 사용자가 제시한 "2026-09-05"라는 정확한 날짜는 어떤 서지 DB에서도 그대로 확인되지 않았다. 확인된 날짜는 다음과 같이 서로 다르다 — CrossRef `published-print`: 2026년 9월(일 단위 정보 없음, Volume 749와 일치), CrossRef `created`: 2026-04-21, OpenAlex `publication_date`: 2026-04-21(온라인 최초 게재로 추정), Semantic Scholar `publicationDate`: 2026-04-01. 즉 **"Volume 749, 2026년 9월 게재"는 CrossRef 기준으로 확인되지만, "9월 5일"이라는 특정 일자는 확인할 수 없었다** — ScienceDirect 웹페이지에 노출되는 "Available online" 또는 조회 시점 날짜였을 가능성이 있으나 원문 접근 차단으로 재확인 불가.
- **GitHub 저장소 상태 (정밀 확인 완료)**: 동료의 주장("README만 있고 커밋 1개")을 GitHub REST API(`api.github.com/repos/byzhaoAI/DisCo`, `.../commits`, `.../contents/`)로 직접 조회해 정확히 확인했다.
  - 저장소 생성일: 2026-04-14T00:45:23Z, 마지막 push: 2026-04-14T00:45:23Z (생성 이후 변경 없음).
  - 커밋 이력: 총 **1개** 커밋("Initial commit", 2026-04-14, GitHub 서명 검증됨).
  - 루트 디렉터리 내용: **`README.md` 파일 1개뿐** (크기 7바이트 — `# DisCo` 정도의 제목 한 줄 수준). 그 외 소스 코드 파일(.py 등), 디렉터리, description, star, fork, release 모두 없음(0 stars, 0 forks, description: null).
  - **결론**: 동료의 주장은 정확하다. 이 저장소는 현재 **재현 가능한 구현체가 아니라 이름만 선점된 자리표시자(placeholder) 수준**이며, 논문 재현(reproduction) 후보가 아니라 저자가 코드를 추후 공개할 예정임을 알리는 설계 참고용 링크로만 취급해야 한다.
- 이 문서는 논문 본문을 확인하지 못한 상태에서 작성되었으므로, MFI/MFP의 정확한 의미·동적 에이전트 대응 방식·정량적 성능 주장은 **모두 "미확인"으로 남겨두었다.** 추후 기관 접근(institutional access) 등으로 원문을 확보하면 3~5절을 갱신해야 한다.

## 7. 원문 기반 핵심 문장
> (확인 불가) — ScienceDirect 원문이 봇 차단 캡차로 차단되어 있고, 초록이 CrossRef/OpenAlex/Semantic Scholar 어디에도 색인되어 있지 않으며 대응 arXiv 프리프린트도 발견되지 않아, 원문에서 직접 인용할 수 있는 문장을 확보하지 못했다. 임의로 문장을 재구성하거나 추정 인용을 만들지 않는다.
