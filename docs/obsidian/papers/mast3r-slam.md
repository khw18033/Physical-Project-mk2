# MASt3R-SLAM: Real-Time Dense SLAM with 3D Reconstruction Priors

## 메타데이터
- categories: Pointmap Matching, Generic Camera Model, Local Fusion과 Loop Closure, Second-Order Global Optimisation
- domain: [[3D 인지]]
- source: Murai, Riku, Dexheimer, Eric, Davison, Andrew J. "MASt3R-SLAM: Real-Time Dense SLAM with 3D Reconstruction Priors." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Murai_MASt3R-SLAM_Real-Time_Dense_SLAM_with_3D_Reconstruction_Priors_CVPR_2025_paper.html
- year: 2025
- authors: Murai, Riku, Dexheimer, Eric, Davison, Andrew J.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), CVPR 2025 Highlight

## 1. 핵심 요약
- 이 논문은 MASt3R라는 two-view 3D reconstruction·matching prior를 기반으로 처음부터 다시 설계한 실시간 monocular dense SLAM 시스템을 제시한다.
- 카메라 중심이 유일하다는 것 외에는 고정되거나 파라메트릭한 카메라 모델을 가정하지 않아, in-the-wild 영상 시퀀스에서도 강건하게 동작한다.
- pointmap matching, camera tracking과 local fusion, graph construction과 loop closure, second-order global optimisation을 위한 효율적인 방법을 제안한다.
- known calibration이 있을 경우 시스템에 간단한 수정을 가하는 것만으로 여러 벤치마크에서 state-of-the-art 성능을 달성하며, 전체 시스템은 15 FPS로 동작하는 plug-and-play monocular SLAM 시스템이다.
- 저자들은 dense projective pointmap matching이 MASt3R-SfM의 brute-force matching 대비 정확도 손실 없이 1000배의 속도 향상을 달성했다고 밝힌다.

## 2. 문서 목적
- 해결하려는 문제: 기존 sparse SLAM은 정확한 pose 추정에는 강하지만 dense geometry 재구성과 일반성에 근본적 한계가 있고, DROID-SLAM 계열의 bundle adjustment 기반 dense SLAM은 smoothness 정규화 부재로 일관된 geometry를 보장하지 못하며 고정된 pinhole 카메라 모델에 묶여 있는 문제.
- 기술적 목표: two-view 3D reconstruction prior(MASt3R)를 SLAM의 tracking·mapping·relocalisation을 아우르는 통합 기반으로 사용해, 실시간 제약 속에서도 정확한 pose와 일관된 dense geometry를 동시에 얻는 것.
- 다루는 범위: pointmap matching 알고리즘, camera tracking과 local pointmap fusion, loop closure를 위한 graph 구성, second-order global optimisation, known calibration이 주어졌을 때의 시스템 수정, TUM RGB-D·EuRoC·7-Scenes·ETH3D 등 벤치마크 평가.

## 3. 핵심 개념 상세

### Two-view 3D Reconstruction Prior 기반 설계
- 원문 표현: "We present a real-time monocular dense SLAM system designed bottom-up from MASt3R, a two-view 3D reconstruction and matching prior."
- 정의: 사전학습된 two-view 3D reconstruction·matching 모델(MASt3R)의 출력을 SLAM 시스템 전체(추정·매칭·최적화)의 기초 구성요소로 삼아 상향식으로 설계하는 방식.
- 역할: 프레임 쌍마다 강력한 기하학적 사전지식을 제공해, 저텍스처·비정형 장면을 포함한 in-the-wild 영상에서도 강건한 추적과 매핑을 가능하게 한다.

### Generic Camera Model(파라메트릭 카메라 모델 비의존)
- 원문 표현: "our system is robust on in-the-wild video sequences despite making no assumption on a fixed or parametric camera model beyond a unique camera centre." / "this requires a parametric camera model with closed-form projection, while our only assumption is that each frame has a unique camera centre."
- 정의: 카메라 중심이 하나로 정의된다는 것 외에는 특정 렌즈·투영 모델(예: pinhole)을 가정하지 않고 pointmap이 정의하는 ray 집합만으로 카메라를 표현하는 방식.
- 역할: 다양한 렌즈·투영 특성을 가진 카메라나 시간에 따라 초점거리가 바뀌는 상황에서도 동일한 SLAM 파이프라인을 그대로 적용할 수 있게 한다.

### Pointmap Matching
- 원문 표현: "Correspondence is a fundamental component of SLAM that is required for both tracking and mapping. ... Our dense projective pointmap matching formulates search as local optimisation and achieves a 1000x speedup without compromising accuracy."
- 정의: MASt3R가 출력하는 pointmap과 feature를 이용해 두 이미지 간 픽셀 대응(match)을 dense하게 찾는 매칭 절차로, 탐색을 local optimisation 문제로 정식화한다.
- 역할: MASt3R-SfM이 사용하는 sparse·brute-force 매칭 대비 큰 폭의 속도 향상을 제공해, 실시간 SLAM에 요구되는 저지연 매칭을 가능하게 한다.

### Local Fusion과 Loop Closure
- 원문 표현: "We introduce efficient methods for pointmap matching, camera tracking and local fusion, graph construction and loop closure, and second-order global optimisation." / "Relocalisation If the system loses tracking due to an insufficient number of matches, relocalisation is triggered. ... the retrieval database is queried with a stricter threshold on the score."
- 정의: 새 프레임의 pointmap을 인접 keyframe들과 결합해 지역적으로 일관된 geometry를 유지하는 local fusion과, retrieval database를 이용해 과거 keyframe과의 재방문을 검출하고 tracking 유실 시 relocalisation을 트리거하는 loop closure·relocalisation 절차.
- 역할: 프레임 단위 누적 오차를 지역적으로 억제하는 동시에, 장기 궤적에서 발생하는 drift를 루프 클로저로 교정하고 추적 실패 상황에서도 시스템을 복구할 수 있게 한다.

### Second-Order Global Optimisation
- 원문 표현: "graph construction and loop closure, and second-order global optimisation" / "Given current estimates of keyframe poses ... and canonical pointmaps ... for keyframes, the goal of the backend optimisation is to achieve global [consistency]."
- 정의: keyframe pose와 canonical pointmap을 대상으로 2차(second-order) 최적화 기법을 적용해 전역적으로 일관된 pose와 dense geometry를 계산하는 backend 최적화 단계.
- 역할: MASt3R-SfM이 사용하는 1차(first-order) optimiser 대비 더 정확하고 안정적인 전역 정합을 실시간 제약 안에서 달성한다고 저자들은 주장한다.

## 4. 구조 및 흐름
1. 입력 프레임 쌍에 대해 MASt3R로 pointmap과 feature를 예측한다.
2. pointmap matching으로 두 이미지 간 픽셀 대응을 local optimisation 기반으로 빠르게 계산한다.
3. camera tracking과 local fusion으로 새 프레임의 pose를 추정하고 인접 keyframe들과 pointmap을 지역적으로 결합한다.
4. retrieval database를 이용해 과거 keyframe과의 재방문을 검출하면 graph에 loop closure edge를 추가하고, 추적이 유실되면 relocalisation을 트리거한다.
5. keyframe pose와 canonical pointmap을 대상으로 second-order global optimisation을 수행해 전역적으로 일관된 pose와 dense geometry를 얻는다.
6. known calibration이 주어지면 canonical pointmap을 해당 카메라 모델의 ray로 backprojection하도록 제약해 정확도를 더 높인다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 파라메트릭 카메라 모델 없이도 in-the-wild 영상에서 강건하게 동작한다 | "our system is robust on in-the-wild video sequences despite making no assumption on a fixed or parametric camera model beyond a unique camera centre" |
| dense pointmap matching이 기존 brute-force 매칭보다 훨씬 빠르다 | "Our dense projective pointmap matching formulates search as local optimisation and achieves a 1000x speedup without compromising accuracy as shown in Table 5." |
| known calibration을 활용하면 TUM RGB-D 등에서 state-of-the-art 궤적 정확도를 달성한다 | "On the TUM dataset, we demonstrate state-of-the-art trajectory error when using calibration as shown in Table 1." |
| 전체 시스템이 실시간으로 동작하며 globally-consistent pose와 dense geometry를 함께 산출한다 | "we propose a plug-and-play monocular SLAM system capable of producing globally-consistent poses and dense geometry while operating at 15 FPS" |

## 6. 한계 및 부족한 점
- 저자들은 frontend에서 필터링한 pointmap을 backend의 전체 global optimisation에서 완전히 재정제하지는 않는다는 한계를 직접 지적한다: "While we can estimate accurate geometry by filtering pointmaps in the frontend, we do not currently refine all geometry in the full global optimisation." DROID-SLAM처럼 bundle adjustment로 per-pixel depth를 최적화하면 이 프레임워크에서는 geometry의 비일관성(incoherent geometry)이 허용된다고 지적한다.
- pointmap을 3D에서 전역적으로 일관되게 만들면서 MASt3R 예측의 coherence도 유지하는 실시간 방법은 아직 없으며, 이를 향후 연구 방향으로 제시한다: "A method that can make pointmaps globally consistent in 3D while retaining the coherence of the original MASt3R predictions all in real-time would be an interesting direction for future work."
- decoder를 full resolution으로 사용하는 것이 현재 저지연 tracking과 loop closure 후보 검사의 병목이라고 명시한다: "using the decoder at full resolution is currently a bottleneck, especially for low-latency tracking and checking loop closure candidates. Improving network throughp[ut] will benefit the total system efficiency."
- MASt3R가 다양한 카메라 모델로 학습되어야 시간에 따라 변하는 intrinsics 등 더 일반적인 카메라 조건과 완전히 호환되는데, 이는 MASt3R 자체의 학습 데이터 다양성에 의존하는 한계로 남는다: "Since MASt3R is only train[ed] on a variety of camera models and will be compatible with our framework that never assumes a parametric camera model."

## 7. 원문 기반 핵심 문장
> "We present a real-time monocular dense SLAM system designed bottom-up from MASt3R, a two-view 3D reconstruction and matching prior. Equipped with this strong prior, our system is robust on in-the-wild video sequences despite making no assumption on a fixed or parametric camera model beyond a unique camera centre."
