# LightMOT: Lightweight and Anchor-free Solution for Tracking Multiple Objects in Dense Populations

## 메타데이터
- categories: MobileNet 기반 경량 Backbone, Dilated Convolution 특징 맵 보존, Anchor-free Multi-Object Tracking, Dense Population Tracking
- domain: [[객체 추적]]
- source: Karthikeyan, P., Liu, Yong-Hong, Hsiung, Pao-Ann. "LightMOT: Lightweight and anchor-free solution for tracking multiple objects in dense populations." Future Generation Computer Systems, 2024.
- url: https://www.sciencedirect.com/science/article/pii/S0167739X2400654X
- year: 2024
- authors: Karthikeyan, P. et al.
- venue: Future Generation Computer Systems

## 1. 핵심 요약
- 혼잡한 교차로 등 high-traffic 지역의 인구 흐름 분석에서 object tracking 기술이 핵심적인 역할을 한다는 문제의식에서 출발한다.
- FairMOT의 backbone을 MobileNet으로 교체해 정확도를 크게 희생하지 않으면서 속도를 높이는 것을 핵심 아이디어로 삼는다.
- MobileNet에 Dilated Convolution(DC)을 결합해 FairMOT 대비 feature map 크기를 유지하면서 더 빠르고 효율적인 tracking을 달성한다.
- MOT20 데이터셋에서 32.2 FPS, 70.1% MOTA, 29.95%의 Cost Performance(CP) 점수를 기록해 FairMOT, Semi-TCL, RelationTrack, CAMTrack 등 기존 tracker를 앞선다.

## 2. 문서 목적
- 해결하려는 문제: 기존 MOT 방법들이 밀집된(dense) 장면에서 실시간 처리 성능을 유지하기 어렵고, 객체 수가 많고 occlusion이 잦은 crowded scene에서 속도-정확도 균형이 무너지는 문제.
- 기술적 목표: FairMOT 구조를 기반으로 backbone을 경량화(MobileNet)하면서도 feature map 정보 손실을 최소화(Dilated Convolution)해, 밀집 장면에서도 실시간에 가까운 tracking 속도를 유지하는 것.
- 다루는 범위: MobileNet 기반 backbone 설계, Dilated Convolution 적용 방식, MOT20 등 벤치마크에서 기존 anchor-free tracker와의 속도·정확도·비용 대비 성능(Cost Performance) 비교.

## 3. 핵심 개념 상세
### MobileNet 기반 경량 Backbone
- 원문 표현: 원문 확인 안 됨 (ScienceDirect 원문이 봇 차단으로 접근되지 않아, 검색 엔진이 색인한 요약만으로 확인함. "LightMOT replaces FairMOT's backbone with MobileNet to boost speed without compromising accuracy"라는 서술이 다수의 독립된 색인 결과에서 일관되게 확인됨)
- 정의: FairMOT의 원래 backbone을 경량 CNN인 MobileNet으로 교체한 구조.
- 역할: 검출과 Re-ID feature 추출을 동시에 수행하는 FairMOT 계열 구조를 유지하면서, backbone 연산량을 낮춰 crowded scene에서도 처리 속도를 높인다.

### Dilated Convolution 기반 특징 맵 보존
- 원문 표현: 원문 확인 안 됨 (색인 요약 기준: "By incorporating Dilated Convolution (DC) into MobileNet, it maintains FairMOT's feature map size while achieving faster, more efficient tracking")
- 정의: MobileNet에 Dilated Convolution을 결합해 convolution의 receptive field를 넓히면서도 FairMOT과 동일한 수준의 feature map 크기(해상도)를 유지하는 기법.
- 역할: backbone 경량화로 발생할 수 있는 feature map 해상도 저하를 Dilated Convolution으로 보완해, 조밀하게 모여 있는 다수 객체를 구분하는 데 필요한 공간 정보를 유지한다.

### Anchor-free Multi-Object Tracking
- 정의: 사전 정의된 anchor box 없이 객체의 중심점 등 anchor-free 방식으로 검출과 추적을 수행하는 MOT 구조.
- 역할: anchor 설계·매칭에 드는 추가 연산과 하이퍼파라미터 튜닝 부담 없이 detection과 tracking을 결합할 수 있게 하며, LightMOT는 이 anchor-free 구조 위에 경량 backbone을 결합한다.

### Dense Population Tracking (밀집 인구 흐름 추적)
- 원문 표현: "Object tracking technology plays a critical role in analysing population flow in high-traffic areas like road intersections."
- 정의: 도로 교차로처럼 사람·차량이 밀집해 오가는 high-traffic 지역에서 다수 객체의 흐름을 추적하는 응용 시나리오.
- 역할: LightMOT가 목표로 하는 대표적 사용 맥락으로, 밀집 상황에서의 occlusion과 실시간성 요구를 동시에 만족해야 하는 배경을 제공한다.

## 4. 구조 및 흐름
1. 입력 프레임이 MobileNet 기반 backbone(Dilated Convolution 포함)을 통과해 detection과 Re-ID를 위한 공유 feature map을 추출한다.
2. FairMOT 계열 구조와 마찬가지로 이 feature map에서 anchor-free 방식으로 객체 중심점과 크기를 검출한다.
3. 동일 feature map에서 Re-ID embedding을 함께 추출해 프레임 간 동일 객체를 연관시킨다.
4. 밀집 장면에서도 유지되는 feature map 해상도 덕분에 근접한 다수 객체를 구분하며 tracklet을 갱신한다.
5. MOT20 등 벤치마크에서 FPS·MOTA·Cost Performance(CP)로 성능을 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| MobileNet 기반 backbone 교체로 속도를 높이면서 정확도를 크게 해치지 않는다 | MOT20에서 32.2 FPS, 70.1% MOTA로 FairMOT 및 Semi-TCL, RelationTrack, CAMTrack 대비 우수한 결과(다수의 독립 색인 결과에서 일관되게 보고됨) |
| Dilated Convolution이 경량화에 따른 feature map 손실을 보완한다 | MobileNet에 Dilated Convolution을 결합해 FairMOT과 동일한 feature map 크기를 유지한다는 서술이 검색 색인 전반에서 일관되게 확인됨 |
| 속도·정확도·비용을 함께 고려한 Cost Performance(CP) 지표에서도 우수하다 | MOT20에서 29.95%의 CP 점수로 비교 대상 tracker들을 상회 |

## 6. 한계 및 부족한 점
- ScienceDirect 원문 페이지가 봇 차단(CAPTCHA/403)으로 직접 접근되지 않아, 본 문서의 수치·서술 상당 부분은 Google Scholar 색인 스니펫과 다수의 독립된 2차 색인 결과를 종합한 것이며, 원문 전체(방법론 세부·ablation·실패 사례)를 직접 대조하지는 못했다.
- 이 때문에 저자가 명시한 한계나 future work 여부는 확인하지 못했다.
- Abstract 전문, 상세 아키텍처 다이어그램, ablation 결과는 원문 접근이 필요하므로 이 문서에서는 다루지 못한다.

## 7. 원문 기반 핵심 문장
> "Object tracking technology plays a critical role in analysing population flow in high-traffic areas like road intersections."
