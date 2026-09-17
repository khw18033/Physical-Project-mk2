# PS-InSAR를 이용한 황강댐 변위 분석

## 메타데이터
- categories: PS-InSAR, 댐 변위 모니터링, Sentinel-1, 접근 제한 인프라의 위성 기반 간접 점검
- domain: [[인프라 점검·이상탐지]]
- source: 김주훈(Kim, Joo Hun), 김지성(Kim, Ji Sung)(한국건설기술연구원 수자원하천연구본부). "PS-InSAR를 이용한 황강댐 변위 분석." 대한토목학회논문집, 45권 5호, pp. 557-565, 2025.
- url: https://doi.org/10.12652/Ksce.2025.45.5.0557
- year: 2025
- authors: 김주훈(Kim, Joo Hun), 김지성(Kim, Ji Sung)
- venue: 대한토목학회논문집 (KSCE Journal of Civil and Environmental Engineering Research), 45(5)

## 1. 핵심 요약
- 계측 자료를 확보할 수 없는 북한 황강댐을 대상으로, 위성 SAR 자료에 PS-InSAR(Persistent Scatterer InSAR) 기법을 적용해 시계열 변위를 분석한 연구다.
- 2017~2024년 상승궤도(ascending) Sentinel-1 SLC 영상 105장과 2017~2021년 하강궤도(descending) 영상 80장을 사용해 콘크리트댐 구간과 필댐(fill dam) 구간의 변위를 각각 산출했다.
- 콘크리트댐 구간은 두 궤도 모두에서 매우 작은 변위(상승궤도 평균 1.4mm, 하강궤도 평균 0.6mm)를 보여 구조적으로 안정적이었고, 필댐 구간은 두 궤도 모두 연 수 mm 수준의 완만한 침하 경향(상승궤도 평균 -4.5mm, 하강궤도 평균 -5.7mm)을 보였다.

## 2. 문서 목적
- 해결하려는 문제: 접근이 제한된 북한 지역에 위치해 현장 계측 자료를 확보할 수 없는 황강댐의 구조적 안정성을 어떻게 원격으로 모니터링할 것인가.
- 기술적 목표: 위성 SAR 자료와 PS-InSAR 기법으로 계측기 없이도 댐체 시계열 변위를 정밀하게 추정하고, 서로 다른 두 위성 궤도(상승·하강) 결과를 상호 비교해 분석 결과의 타당성을 간접 검증하는 것.
- 다루는 범위: Sentinel-1 C-band SAR 영상(상승궤도 105장, 하강궤도 80장)에 100m 기준선 제약과 0.75 이상 코히런스(coherence) 조건으로 PS(persistent scatterer) 픽셀을 선정해 변위를 추정하는 절차와 그 결과 해석. 수직·수평 성분 분해를 위한 상승·하강 궤도 결합 분석은 후속 연구 과제로 남겨두었다.

## 3. 핵심 개념 상세

### PS-InSAR (Persistent Scatterer InSAR)
- 정의: 시계열 SAR 영상에서 시간이 지나도 위상 반사 특성이 안정적으로 유지되는 픽셀(persistent scatterer)을 식별하고, 이 픽셀들의 위상 변화만을 이용해 지표·구조물의 미세 변위를 시계열로 추정하는 기법.
- 역할: 이 연구에서 계측기가 없는 황강댐의 콘크리트댐·필댐 구간 변위를 추정하는 핵심 방법으로 사용된다.

### 코히런스(coherence) 기반 PS 픽셀 선정과 기준선 제약
- 정의: 간섭쌍(interferometric pair) 생성 시 100m 기준선(baseline) 제약을 적용하고, 코히런스 값이 0.75 이상인 픽셀만 PS로 식별해 변위 추정에 사용하는 처리 조건.
- 역할: 식생·계절 변화 등으로 위상이 불안정한 픽셀을 배제해 변위 추정의 신뢰도를 높이는 품질 관리 기준으로 작동한다.

### 상승·하강 궤도 교차 검증
- 정의: 동일 지역에 대해 서로 다른 관측 기하를 갖는 상승궤도(ascending)와 하강궤도(descending) Sentinel-1 자료를 각각 독립적으로 분석한 뒤 두 결과의 변위 경향을 비교하는 절차.
- 역할: 지상 계측 자료(ground truth)가 없는 상황에서, 서로 다른 궤도에서 얻은 결과가 일관된 경향을 보이는지로 위성 기반 변위 분석의 타당성을 간접적으로 검증하는 근거로 사용된다.

## 4. 구조 및 흐름
1. 배경: 계측 자료가 없는 북한 황강댐의 구조 안전성 모니터링 필요성 제시.
2. 자료: Sentinel-1 C-band SLC 영상, 상승궤도 105장(2017-2024), 하강궤도 80장(2017-2021) 수집.
3. 처리: 100m 기준선 제약으로 간섭쌍을 생성하고 코히런스 0.75 이상 픽셀을 PS로 선정해 시계열 변위 추정.
4. 분석: 콘크리트댐·필댐 구간별로 상승·하강 궤도 각각의 평균 변위를 산출.
5. 검증: 두 궤도의 변위 경향 일치 여부로 분석 결과의 타당성을 간접 확인.
6. 결론: 콘크리트댐은 안정적, 필댐은 완만한 침하 경향이며, 후속 연구로 수직·수평 성분 분해를 위한 궤도 결합 분석을 제안.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 황강댐 콘크리트댐 구간은 구조적으로 안정적이다 | KCI·DOI 원문 초록(WebFetch로 확인): 상승궤도 평균 변위 1.4mm, 하강궤도 평균 변위 0.6mm로 "매우 작은 변위를 보여 구조적 안정성을 나타냄"("very small displacements, indicating structural stability") |
| 황강댐 필댐 구간은 완만한 침하 경향을 보인다 | 동일 초록: 상승궤도 평균 -4.5mm, 하강궤도 평균 -5.7mm로 "연 수 mm 수준의 완만한 침하 경향"("a gentle subsidence trend of several mm/yr") |
| 계측기 없이도 위성 기반 간접 모니터링이 접근 제한 인프라에 유효하다 | 초록 결론부: "This study demonstrated the effectiveness of a satellite-based indirect monitoring system for infrastructure with limited access." |

## 6. 한계 및 부족한 점
- 이번 확인은 KCI 서지정보 페이지(kci.go.kr, artiId=ART003250897)와 DOI(10.12652/Ksce.2025.45.5.0557)가 실제로 가리키는 대한토목학회논문집 XML 뷰어 페이지(kscejournal.or.kr)에 WebFetch로 접근해 제목·저자·소속·권호·페이지·영문 초록 전체·키워드를 확인한 수준이다. 논문 본문 전체(구체적 처리 파라미터, SNAP/StaMPS 등 소프트웨어, 그림·표, 참고문헌)는 확보하지 못했다.
- 저자 소속은 한국건설기술연구원(KICT) 수자원하천연구본부이며, K-water(한국수자원공사) 소속이 아니다.
- **재조사 과정의 오류 정정**: 이번 조사 초기에 DBpia에서 "황강댐", "PS-InSAR" 키워드로 연구 프로필이 태깅된 K-water 수자원위성센터 소속 강기묵 연구원을 저자로 추정했으나, KCI 원문 확인 결과 실제 저자는 김주훈·김지성(한국건설기술연구원)이며 강기묵 연구원은 이 논문과 무관한 것으로 판단된다. 키워드 프로필 매칭만으로 저자를 추정하면 안 된다는 사례.
- 사용자가 제공한 원 브리프는 게재지를 "대한토목학회 추정"으로만 표기했는데, 실제로는 학술대회 초록이 아니라 대한토목학회논문집(KSCE Journal of Civil and Environmental Engineering Research) 정식 학술지 논문(2025년 10월, 45권 5호)으로 확인된다.
- 이 논문 자체가 하천 도메인이 아니라 댐(황강댐) 구조물 변위 모니터링을 다루므로, 이 저장소의 하천 제방(섬진강 사례)·호안(河川護岸) 문서와는 대상 구조물이 다르다는 점에 유의해야 한다.

## 7. 원문 기반 핵심 문장
> "The purpose of this study was to analyze the time-series displacement of the Hwanggang Dam in North Korea by applying the PS-InSAR technique using satellite SAR data. [...] The analysis results showed that the average displacement in the ascending orbit was 1.4 mm for the concrete dam and -4.5 mm for the fill dam. In the descending orbit, the average displacement was 0.6 mm for the concrete dam and -5.7 mm for the fill dam. [...] This study demonstrated the effectiveness of a satellite-based indirect monitoring system for infrastructure with limited access." (kscejournal.or.kr 논문 페이지 영문 초록 전문, WebFetch로 확인)
