# Hydra-Multi: Collaborative Online Construction of 3D Scene Graphs with Multi-Robot Teams

## 메타데이터
- categories: 계층적 Loop Closure Detection, Align-Optimize-Reconcile 프레임워크, Multi-Robot Scene Graph 병합
- domain: [[3D 인지]], [[로보틱스·다중로봇]]
- source: Chang, Yun, Hughes, Nathan, Ray, Aaron, Carlone, Luca. "Hydra-Multi: Collaborative Online Construction of 3D Scene Graphs with Multi-Robot Teams." arXiv preprint arXiv:2304.13487, 2023.
- url: https://arxiv.org/abs/2304.13487
- year: 2023
- authors: Yun Chang, Nathan Hughes, Aaron Ray, Luca Carlone
- venue: arXiv preprint (cs.RO)

## 1. 핵심 요약
- 3D scene graph는 환경을 object, room, building 등 여러 추상화 수준의 node와 그 관계(edge)로 표현하는 layered map 표현으로 최근 주목받고 있지만, 여러 로봇이 협업해 하나의 3D scene graph를 online으로 구축하는 시스템은 거의 다뤄지지 않았다.
- 이 논문은 여러 로봇의 센서 데이터로부터 online으로 multi-robot 3D scene graph를 구축하는 최초의 multi-robot spatial perception 시스템인 Hydra-Multi를 제안한다.
- 각 로봇이 만든 local scene graph를 중앙 서버가 순차적으로 입력받아, 로봇 간 상대 좌표 변환을 찾고 loop closure detection으로 서로 다른 로봇에서 온 scene graph node를 올바르게 조정(reconcile)하는 centralized 시스템이다.
- 핵심 파이프라인은 계층적 loop closure detection, 초기 좌표계 정렬(frame alignment), Graduated Non-Convexity(GNC) 기반 align-optimize-reconcile 최적화로 구성된다.
- 시뮬레이션과 실제 환경 실험을 통해 online으로 정확한 3D scene graph를 재구성할 수 있음을 보였으며, 서로 다른 sensor suite를 가진 로봇들이 만든 서로 다른 map 표현을 융합해 heterogeneous team을 지원할 수 있음도 함께 시연했다.

## 2. 문서 목적
- 해결하려는 문제: 3D scene graph 표현은 단일 로봇 매핑에서는 활발히 연구되었지만, 여러 로봇이 관측한 센서 데이터를 하나의 일관된 multi-robot 3D scene graph로 online 융합하는 higher-level metric-semantic 표현 연구는 드물다는 문제. 원문 표현: "there is only a sparse set of works that aims at enabling multi-robot systems to construct higher-level metric-semantic representations."
- 기술적 목표: 여러 로봇의 local scene graph를 incremental하게 입력받아 로봇 간 상대 변환을 추정하고, loop closure를 이용해 중복된 scene graph node를 정확히 병합함으로써 online으로 정확한 joint 3D scene graph를 구축하는 것.
- 다루는 범위: Hydra 기반 계층적 loop closure detection 모듈 설계, 로봇 간 초기 pose 보정을 불필요하게 만드는 frame alignment 모듈, GNC 기반 align-optimize-reconcile 최적화 프레임워크, 시뮬레이션(uHumans2)·실제 환경(SidPac, Simmons) 데이터셋에서의 정량 평가, heterogeneous sensor suite를 가진 로봇 팀에 대한 지원 시연.

## 3. 핵심 개념 상세
### 3D Scene Graph 계층 구조
- 원문 표현: "nodes represent spatial concepts at multiple levels of abstraction (e.g., objects, rooms, and buildings for indoor environments), and edges represent relations between concepts (e.g., inclusion, adjacency)."
- 정의: Hydra-Multi는 Hydra의 계층 구조를 그대로 사용하며, agent layer(로봇 궤적), places layer(자유 공간을 나타내는 GVD/ESDF 기반 표현), objects layer(의미 라벨과 bounding box를 가진 semantic object), rooms layer(방 단위 추상화), mesh/visual layer(semantic 주석이 달린 3D 재구성 mesh)로 구성된 multi-layer 구조를 사용한다.
- 역할: 서로 다른 로봇이 서로 다른 종류의 센서·인지 능력만으로 관측하더라도, 각 로봇의 결과가 호환되는 layer에만 기여하면 되므로 이 다층 구조 자체가 heterogeneous map 융합을 가능하게 하는 기반이 된다.

### 계층적 Loop Closure Detection
- 원문 표현: "a 3D-scene-graph-based hierarchical loop closure detection module...which enables a more versatile inter-robot loop closure detection."
- 정의: scene graph의 상위 layer(예: room, object) 수준에서 descriptor를 비교하는 top-down 단계와, 시각 keypoint에는 RANSAC을, object node에는 TEASER++를 사용하는 bottom-up geometric verification 단계로 구성된 로봇 간 loop closure 탐지 방법.
- 역할: 서로 다른 로봇이 관측한 장면 사이에서 동일 장소·객체를 식별해, 이후 frame alignment와 scene graph 병합의 입력이 되는 로봇 간 대응 관계를 제공한다.

### Frame Alignment (초기 좌표계 정렬)
- 원문 표현: "a frame alignment module that removes the need to calibrate the initial poses of the robots."
- 정의: 탐지된 로봇 간 loop closure를 이용해 robot-level dependence graph 위에서 임의의 spanning tree를 선택하고, robust pose-averaging으로 로봇 쌍 사이의 상대 pose를 추정하는 모듈. 원문: "we choose an arbitrary spanning tree in the robot-level dependence graph...then estimate the relative pose between pairs of robots."
- 역할: 로봇들의 시작 위치를 사전에 수동 보정하지 않아도, 관측된 loop closure만으로 서로 다른 로봇의 local 좌표계를 하나의 공통 좌표계로 정렬할 수 있게 한다.

### Align-Optimize-Reconcile 프레임워크 (GNC 기반)
- 원문 표현: "an align-optimize-reconcile framework that uses Graduated Non-Convexity (GNC) to optimize multi-robot 3D scene graphs while being robust to outlier loop closures and erroneous associations of scene graph nodes across different robots."
- 정의: 공간적으로 겹치고 크기가 비슷한 place node, 동일한 semantic label과 겹치는 bounding box를 가진 object node 등을 병합 후보로 제안한 뒤, embedded deformation graph 기반 pose-graph 최적화에서 GNC로 outlier를 걸러내고, GNC inlier로 선택된 병합만 유효한 병합으로 확정하는 반복적 프레임워크. 원문: "A merge candidate is considered valid if it is selected as an inlier by GNC."
- 역할: perceptual aliasing으로 인한 대량의 잘못된 loop closure나 잘못된 node 대응이 있어도, scene graph의 최종 정확도를 훼손하지 않고 robust하게 여러 로봇의 local scene graph를 하나로 병합한다.

### Heterogeneous Sensor Suite 지원
- 원문 표현: "In case a robot with a different sensor or mapping suite is added to the team, we are still able to support the robot and merge its local map into the Hydra-Multi scene graph, as long as the robot map representation is compatible with at least one layer in the scene graph."
- 정의: 로봇마다 탑재한 센서·인지 파이프라인이 달라 산출하는 map 표현이 다르더라도(예: stereo camera 기반 object-level SLAM만 수행하는 로봇, 또는 semantic 주석 없이 mesh만 만드는 LIDAR 로봇), 각 로봇의 출력이 scene graph의 특정 layer와 호환되기만 하면 그 layer 단위로 융합할 수 있다는 성질.
- 역할: 모든 로봇이 동일한 센서·인지 능력을 갖출 것을 요구하지 않고, 각 로봇이 기여할 수 있는 layer만 채우는 방식으로 서로 다른 하드웨어 구성의 로봇 팀을 하나의 scene graph 구축에 참여시킬 수 있게 한다.

## 4. 구조 및 흐름
1. 각 로봇이 자신의 센서 데이터로 로컬 Hydra instance를 실행해 partial local 3D scene graph를 incremental하게 구축한다.
2. 각 로봇의 local scene graph가 중앙 서버로 전달되어, 아직 최적화·조정되지 않은 "un-optimized and un-reconciled frontend scene graph"로 합쳐진다(로봇마다 관측한 중복 node가 존재할 수 있음).
3. 계층적 loop closure detection이 top-down descriptor 비교와 bottom-up geometric verification(RANSAC/TEASER++)을 통해 로봇 간 loop closure를 탐지한다.
4. 탐지된 loop closure를 이용해 robot-level dependence graph의 spanning tree 위에서 robust pose-averaging으로 로봇 간 상대 좌표 변환을 추정한다(frame alignment).
5. 공간적 겹침·의미적 유사도를 기준으로 병합 후보(merge candidate)를 제안한다.
6. embedded deformation graph 기반 pose-graph 최적화를 GNC로 수행해 outlier loop closure와 잘못된 병합 후보를 걸러내고, GNC inlier로 확정된 병합만 반영한다(align-optimize-reconcile).
7. 최종적으로 정합된 하나의 multi-robot 3D scene graph가 online으로 유지되며, 서로 다른 sensor suite를 가진 로봇의 map 표현도 호환되는 layer 단위로 함께 융합된다.
8. 시뮬레이션 데이터셋 uHumans2와 실제 데이터셋 SidPac, Simmons에서 궤적 정확도(ATE), object 탐지 정확도, 실행 시간과 단일 로봇 대비 매핑 소요 시간을 비교 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 기존 연구는 multi-robot 시스템으로 higher-level metric-semantic 표현을 구축하는 사례가 드물다 | "there is only a sparse set of works that aims at enabling multi-robot systems to construct higher-level metric-semantic representations" |
| Hydra-Multi는 여러 로봇의 센서 데이터로부터 online으로 multi-robot 3D scene graph를 구축하는 최초의 시스템이다 | "This paper describes Hydra-Multi, the first multi-robot spatial perception system capable of constructing a multi-robot 3D scene graph online from sensor data collected by robots in a team." |
| GNC 기반 align-optimize-reconcile 프레임워크는 outlier loop closure와 잘못된 node 대응에도 robust하게 동작한다 | "an align-optimize-reconcile framework that uses Graduated Non-Convexity (GNC) to optimize multi-robot 3D scene graphs while being robust to outlier loop closures and erroneous associations of scene graph nodes across different robots" |
| Hydra-Multi는 시뮬레이션과 실제 환경 모두에서 정확한 3D scene graph를 online으로 재구성할 수 있다 | "We evaluate Hydra-Multi on simulated and real scenarios and show it is able to reconstruct accurate 3D scene graphs online." |
| 서로 다른 sensor suite를 가진 로봇의 map 표현도 최소 한 layer만 호환되면 융합할 수 있다 | "we are still able to support the robot and merge its local map into the Hydra-Multi scene graph, as long as the robot map representation is compatible with at least one layer in the scene graph" |
| Multi-robot 매핑은 단일 로봇 순차 탐사보다 빠르면서도 유사한 성능을 낸다 | 시스템은 "performance comparable to the single-robot system while enabling faster mapping"을 보였으며, 실험에서 multi-robot 매핑은 약 30분, 단일 로봇 순차 탐사는 약 50분이 소요되었다. |

## 6. 한계 및 부족한 점
- 저자가 직접 명시한 future work: "Future work includes relaxing the assumption that objects in the scene are static, and moving from a centralized to a distributed backend for increased scalability." 즉 현재 시스템은 정적 객체를 가정하며, 중앙 서버(centralized backend)가 모든 로봇의 measurement를 수집·최적화하는 구조라 확장성에 한계가 있음을 저자 스스로 인정한다.
- 저자가 명시한 추가 향후 과제: "Reduce the communication bandwidth from the agents to the base station," "Speed up the scene graph optimization," "Harden Hydra-Multi towards large-scale real-world deployment" — 즉 통신 대역폭 최적화, 최적화 속도, 대규모 실환경 배포 견고성은 아직 충분히 해결되지 않았다.
- SidPac 데이터셋에서는 ATE가 3.92±0.9m로 다른 데이터셋(uH2 0.25±0.05m, SM1 0.99±0.31m, SM2 0.79±0.15m)보다 크게 나빴으며, 저자는 이를 "unfavorable lighting, prevalence of glass (causing partial and noisy depth estimates), feature-poor regions in hallways, and the lack of other types of sensors"로 설명한다. 즉 visual-inertial 단일 센서에 의존하는 로봇 구성은 조명·유리·저-feature 환경에서 취약하다.
- Simmons 데이터셋은 "80% to 90% outlier loop closures"에 달하는 심각한 perceptual aliasing을 겪었다고 보고되어, GNC 기반 outlier 제거가 필요한 만큼 초기 loop closure detection 자체의 정밀도는 아직 낮다는 점을 시사한다.
- **MR-COGraphs와의 비교**: 두 논문은 "여러 로봇이 만든 local 3D scene 표현을 하나의 global 표현으로 병합한다"는 동일한 상위 문제를 다루지만, 강조점과 메커니즘이 다르다. MR-COGraphs는 통신 대역폭 제한 환경에서의 open-vocabulary map 전송량 절감(data-driven feature encoder/decoder로 압축·복원)을 핵심 기여로 삼고, 병합 자체는 feature 기반 place recognition과 translation estimation으로 비교적 단순하게 처리한다. 반면 Hydra-Multi는 전송량 절감을 다루지 않고("Reduce the communication bandwidth"는 오히려 future work로 남아 있다), 대신 계층적 loop closure detection과 GNC 기반 align-optimize-reconcile이라는 outlier에 robust한 정합·최적화 메커니즘 자체에 집중한다. 즉 MR-COGraphs는 "무엇을 전송하고 어떻게 압축할 것인가"에, Hydra-Multi는 "여러 로봇의 관측을 어떻게 정확하고 robust하게 하나의 scene graph로 정합할 것인가"에 각각 초점을 맞춘 상호보완적 논문으로 볼 수 있다. 또한 MR-COGraphs의 scene 표현은 object node + 공간 인접 edge로 이루어진 단일 계층 graph(COGraph)인 반면, Hydra-Multi는 Hydra의 agent/places/objects/rooms/mesh 다층 구조를 그대로 유지한 채 병합한다는 점에서 표현 자체의 세분화 수준도 다르다.
- **"heterogeneous sensor suite" 주장 검증**: 동료 요약("서로 다른 sensor suite를 가진 heterogeneous robot team까지 다룹니다")은 원문에 근거가 있어 대체로 정확하다. 다만 정밀하게 보면, 논문이 실제로 시연한 것은 "한 로봇은 semantically annotated map(예: visual-inertial + RGB-D로 object 인지까지 수행), 다른 로봇은 semantic 주석 없는 순수 geometric 3D 재구성(예: visual-inertial + LIDAR mesh)"을 만들고 이 둘을 scene graph의 호환되는 layer 단위로 결합하는 수준이다. 즉 서로 다른 센서 모달리티를 가진 로봇들이 협업하는 것은 사실이지만, 이는 딥러닝 수준의 cross-modal fusion(예: LIDAR feature와 카메라 feature를 하나의 표현으로 학습·정합)이 아니라, "각 로봇이 자신의 센서로 만들 수 있는 layer만 채우고, layer가 존재하지 않는 로봇은 해당 layer에 기여하지 않는다"는 다소 느슨한 layer 단위 호환성에 기반한다. 조건도 "the robot map representation is compatible with at least one layer"로 명시되어 있어, 임의의 이종 센서 조합을 보장하는 것이 아니라 최소 한 layer가 호환될 때만 해당 로봇을 지원할 수 있다는 제한적 의미다.

## 7. 원문 기반 핵심 문장
> "This paper describes Hydra-Multi, the first multi-robot spatial perception system capable of constructing a multi-robot 3D scene graph online from sensor data collected by robots in a team. In particular, we develop a centralized system capable of constructing a joint 3D scene graph by taking incremental inputs from multiple robots, effectively finding the relative transforms between the robots' frames, and incorporating loop closure detections to correctly reconcile the scene graph nodes from different robots."
