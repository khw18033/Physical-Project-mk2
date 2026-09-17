# Open-Vocabulary Octree-Graph for 3D Scene Understanding

## 메타데이터
- categories: Octree-Graph 장면 표현, Adaptive-Octree, Chronological Group-wise Segment Merging, Instance Feature Aggregation
- domain: [[3D 인지]]
- source: Wang, Zhigang, Su, Yifei, Li, Chenhui, Wang, Dong, Huang, Yan, Zhao, Bin, Li, Xuelong. "Open-Vocabulary Octree-Graph for 3D Scene Understanding." Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2025.
- url: https://openaccess.thecvf.com/content/ICCV2025/html/Wang_Open-Vocabulary_Octree-Graph_for_3D_Scene_Understanding_ICCV_2025_paper.html
- year: 2025
- authors: Zhigang Wang, Yifei Su, Chenhui Li, Dong Wang, Yan Huang, Bin Zhao, Xuelong Li
- venue: IEEE/CVF International Conference on Computer Vision (ICCV)

## 1. 핵심 요약
- Open-vocabulary 3D scene understanding은 embodied agent에 필수적이며, 최근 연구들은 pretrained vision-language model(VLM)로 object segmentation을 수행한 뒤 이를 point cloud에 투영해 3D map을 구축한다.
- 그러나 point cloud는 순서 없는 좌표 집합이라 저장 공간이 크고, occupancy 정보나 공간 관계(spatial relation)를 직접 담지 못해 path planning, text-based object retrieval 같은 downstream task에서 비효율적이다.
- 이 논문은 이를 해결하기 위해 Octree-Graph라는 새로운 3D scene 표현을 제안한다.
- Chronological Group-wise Segment Merging(CGSM)과 Instance Feature Aggregation(IFA)으로 3D instance와 semantic feature를 얻고, 각 instance의 형태에 따라 occupancy를 조정 가능한 adaptive-octree로 표현한 뒤, adaptive-octree를 graph node로, 공간 관계를 edge로 삼아 Octree-Graph를 구성한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 open-vocabulary 3D scene 표현이 point cloud 기반이라 저장 공간을 많이 차지하고, occupancy·공간 관계 정보를 명시적으로 담지 못해 downstream task(경로 계획, 텍스트 기반 객체 검색)에서 비효율적인 문제.
- 기술적 목표: object 단위 occupancy와 semantic 정보를 형태에 맞게 압축해서 담는 adaptive-octree 구조와, object 간 공간 관계를 명시적으로 표현하는 graph 구조를 결합한 새로운 3D scene 표현을 제시하는 것.
- 다루는 범위: VLM 기반 segmentation 결과로부터 시간적으로 일관된 3D instance를 얻는 CGSM·IFA 알고리즘 설계, 형태 적응적인 occupancy 표현을 위한 adaptive-octree 구조 설계, adaptive-octree를 node로 하고 공간 관계를 edge로 하는 Octree-Graph 구성.

## 3. 핵심 개념 상세
### Point Cloud 표현의 한계
- 원문 표현: "a point cloud is a set of unordered coordinates that requires substantial storage space and does not directly convey occupancy information or spatial relation, making existing methods inefficient for downstream tasks, e.g., path planning and text-based object retrieval."
- 정의: point cloud가 순서 없는 좌표들의 집합이기 때문에, 저장 공간이 크고 객체의 점유(occupancy) 영역이나 다른 객체와의 공간적 관계를 직접적으로 표현하지 못한다는 한계.
- 역할: 3D map을 활용해 경로 계획이나 자연어 기반 객체 검색을 수행하는 시스템에서, 원본 point cloud를 그대로 사용하는 대신 더 구조화된 표현으로 변환해야 하는 이유를 설명하는 문제 정의로 쓰인다.

### Chronological Group-wise Segment Merging (CGSM)
- 원문 표현: "a Chronological Group-wise Segment Merging (CGSM) strategy and an Instance Feature Aggregation (IFA) algorithm are first designed to get 3D instances and corresponding semantic features."
- 정의: 여러 시점(frame)에서 얻은 segmentation 결과를 시간 순서에 따라 그룹 단위로 병합해, 동일 객체에 해당하는 segment들을 일관된 3D instance로 통합하는 전략.
- 역할: 프레임마다 독립적으로 수행되는 segmentation 결과를 시간축에 걸쳐 하나의 객체로 정합시켜, 노이즈가 있는 개별 프레임 segmentation으로부터 안정적인 3D instance를 얻는 데 쓰이는 절차다.

### Instance Feature Aggregation (IFA)
- 원문 표현: "an Instance Feature Aggregation (IFA) algorithm are first designed to get 3D instances and corresponding semantic features."
- 정의: CGSM으로 얻어진 3D instance에 대해 여러 관측에서 나온 semantic feature를 하나의 instance-level feature로 집계하는 알고리즘.
- 역할: 동일 객체를 여러 각도·시점에서 관측한 semantic feature들을 하나의 대표 feature로 통합해, open-vocabulary 질의(query) 시 참조할 수 있는 instance 단위 semantic 표현을 만드는 데 쓰인다.

### Adaptive-Octree 구조
- 원문 표현: "an adaptive-octree structure is developed that stores semantics and depicts the occupancy of an object adjustably according to its shape."
- 정의: 객체의 형태에 따라 세분화 정도를 조정하며 occupancy와 semantic 정보를 함께 저장하는 octree 기반 구조.
- 역할: 균일한 해상도로 공간을 분할하는 대신 객체 형태에 맞춰 적응적으로 세분화함으로써, 저장 공간을 절약하면서도 필요한 부분에서는 정밀한 occupancy 정보를 유지하는 3D 공간 표현 기법이다.

### Octree-Graph
- 원문 표현: "the Octree-Graph is constructed where each adaptive-octree acts as a graph node, and edges describe the spatial relations among nodes."
- 정의: 각 객체의 adaptive-octree를 graph의 node로 삼고, 객체 간 공간적 관계를 edge로 표현하는 scene-level graph 구조.
- 역할: 개별 객체의 형태·점유 정보(node)와 객체 간 배치 관계(edge)를 하나의 구조에 통합해, 자연어 질의에 대한 객체 검색이나 경로 계획처럼 객체 간 관계 정보가 필요한 downstream task에서 참조 가능한 scene 표현으로 쓰인다.

## 4. 구조 및 흐름
1. 입력 영상 시퀀스에 대해 pretrained VLM으로 object segmentation을 수행한다.
2. CGSM 전략으로 여러 프레임의 segment를 시간 순서에 따라 그룹 단위로 병합해 일관된 3D instance를 얻는다.
3. IFA 알고리즘으로 각 3D instance에 대응하는 semantic feature를 여러 관측에서 집계한다.
4. 각 instance에 대해 형태에 따라 세분화 수준을 조정하는 adaptive-octree를 구축해 semantic·occupancy 정보를 저장한다.
5. 모든 adaptive-octree를 graph node로, instance 간 공간 관계를 graph edge로 삼아 scene 전체의 Octree-Graph를 구성한다.
6. 구성된 Octree-Graph는 open-vocabulary 텍스트 질의에 대한 객체 검색, 경로 계획 등 downstream task의 입력으로 활용된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| point cloud 기반 3D 표현은 저장 공간과 관계 표현 측면에서 비효율적이다 | "a point cloud is a set of unordered coordinates that requires substantial storage space and does not directly convey occupancy information or spatial relation" |
| CGSM·IFA로 얻은 instance를 adaptive-octree로 표현하면 객체 형태에 맞춰 occupancy를 조정 가능하다 | "an adaptive-octree structure is developed that stores semantics and depicts the occupancy of an object adjustably according to its shape" |
| Octree-Graph는 객체 간 공간 관계를 explicit한 graph edge로 표현한다 | "the Octree-Graph is constructed where each adaptive-octree acts as a graph node, and edges describe the spatial relations among nodes" |

## 6. 한계 및 부족한 점
- 확인한 초록 범위에서는 정량적 저장 공간 절감률이나 downstream task 성능 수치는 확인되지 않았다.
- 이 방법은 pretrained VLM의 object segmentation 결과를 전제로 CGSM·IFA를 수행하므로, VLM segmentation 품질이 낮은 경우 이후 instance·octree·graph 구성 전반의 품질에 어떤 영향을 미치는지는 초록 수준에서 확인되지 않는다.
- 확인한 범위(초록) 내에서는 저자가 직접 명시한 실패 사례나 future work에 대한 서술은 확인되지 않는다.

## 7. 원문 기반 핵심 문장
> "Despite progress, a point cloud is a set of unordered coordinates that requires substantial storage space and does not directly convey occupancy information or spatial relation, making existing methods inefficient for downstream tasks, e.g., path planning and text-based object retrieval."
