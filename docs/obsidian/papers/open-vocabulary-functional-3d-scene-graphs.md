# Open-Vocabulary Functional 3D Scene Graphs for Real-World Indoor Spaces

## 메타데이터
- categories: Functional 3D Scene Graph, Interactive Element Detection, VLM·LLM 기반 관계 추론, FunGraph3D 데이터셋
- domain: [[3D 인지]]
- source: Zhang, Chenyangguang, Delitzas, Alexandros, Wang, Fangjinhua, Zhang, Ruida, Ji, Xiangyang, Pollefeys, Marc, Engelmann, Francis. "Open-Vocabulary Functional 3D Scene Graphs for Real-World Indoor Spaces." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Open-Vocabulary_Functional_3D_Scene_Graphs_for_Real-World_Indoor_Spaces_CVPR_2025_paper.html
- year: 2025
- authors: Zhang et al.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)

## 1. 핵심 요약
- posed RGB-D 이미지로부터 functional 3D scene graph를 예측하는 태스크를 새로 제안한다. 기존 3D scene graph가 객체 간 공간적 관계(spatial relationship)에 집중하는 것과 달리, functional 3D scene graph는 객체, interactive element, 그리고 이들 간의 functional relationship을 함께 표현한다.
- 이런 태스크를 위한 학습 데이터가 없기 때문에, VLM(visual language model)과 LLM(large language model)을 이용해 functional knowledge를 인코딩한다.
- 확장된 SceneFun3D 데이터셋과 새로 수집한 FunGraph3D 데이터셋으로 평가하며, Open3DSG·ConceptGraph를 적용(adapt)한 baseline보다 유의미하게 우수한 성능을 보인다.
- 3D question answering과 robotic manipulation 등 downstream application을 functional 3D scene graph로 시연한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 3D scene graph는 객체 간 공간적 관계만 표현해, 손잡이·버튼·노브처럼 실제 조작(interaction)이 필요한 작은 요소와 그 요소가 어떤 객체를 동작시키는지의 관계를 포착하지 못한다. 또한 이런 functional 관계를 학습할 수 있는 데이터셋 자체가 부재하다.
- 기술적 목표: 객체, interactive element, functional relationship을 함께 포함하는 3D scene graph를 posed RGB-D 이미지로부터 예측하되, 전용 학습 데이터 없이 foundation model(VLM/LLM)의 사전지식으로 functional knowledge를 인코딩하는 것.
- 다루는 범위: node candidate(객체·interactive element) 탐지, node 서술(caption) 생성, local/remote functional relationship 추론, 최종 graph 구성, FunGraph3D 데이터셋 수집·주석, Open3DSG/ConceptGraph 적용 baseline과의 정량 비교, 3D QA·robotic manipulation downstream 적용.

## 3. 핵심 개념 상세
### Functional 3D Scene Graph
- 원문 표현: "functional 3D scene graphs capture objects, interactive elements, and their functional relationships."
- 정의: 기존 객체 중심 3D scene graph를 확장해, 손잡이·버튼·노브 같은 작은 interactive element를 별도 노드로 포함하고 이 요소와 그것이 제어하는 객체 사이의 functional relationship을 edge로 표현하는 scene 표현.
- 역할: 공간 관계만 표현하는 기존 scene graph와 달리, 실제 조작에 필요한 "무엇을 다루어야 어떤 객체가 동작하는가"의 관계까지 표현해 상호작용 기반 task에 활용할 수 있는 표현을 제공한다.

### Interactive Element Detection
- 원문 표현: "this approach leads to more accurate detection of small interactive parts."
- 정의: GPT-4로 각 객체에 대해 가능한 interactive element 태그(예: handle, knob, button)를 생성한 뒤 이를 object tag와 결합("door. handle")해 GroundingDINO 프롬프트로 사용, 작은 부품을 탐지하는 절차.
- 역할: 일반적인 open-vocabulary detector가 놓치기 쉬운 작은 상호작용 요소를, 상위 객체 맥락과 결합한 프롬프트를 통해 더 정확하게 탐지할 수 있게 한다.

### Local/Remote Functional Relationship 추론
- 원문 표현: "confidence-aware reasoning"
- 정의: element와 object가 물리적으로 붙어 있는 local relationship(공간적 overlap 필터링 후 LLM이 "opens" 같은 관계 서술을 생성)과, 물리적으로 떨어진 remote relationship(예: TV와 리모컨처럼 분리된 경우, LLM이 후보 pairing을 생성하고 VLM이 전원 연결 여부 등 물리적 타당성을 점검한 뒤 LLM이 confidence score를 부여하는 "confidence-aware reasoning")을 구분해 추론하는 절차.
- 역할: 단순 근접·overlap 기준으로는 파악할 수 없는, 물리적으로 분리된 조작 요소-객체 관계까지 functional graph에 포함시킨다.

### VLM/LLM 기반 노드 서술 생성
- 원문 표현: "we leverage foundation models, including visual language models (VLMs) and large language models (LLMs), to encode functional knowledge."
- 정의: LLAVA로 크롭된 객체·interactive element의 다중 시점(multi-view) caption을 생성하고, GPT-4가 이를 하나의 통합 서술로 요약하는 절차. 작은 interactive element는 확대되고 붉은 윤곽선으로 강조된 crop을 다중 스케일·다중 시점으로 서술한다.
- 역할: functional scene graph 학습에 필요한 전용 데이터가 부족한 상황에서, 별도 학습 없이 foundation model의 사전지식으로 각 노드의 의미와 기능을 서술한다.

### FunGraph3D 데이터셋
- 정의: Leica RTC360 레이저 스캐너 기반 고정밀 3D scan, iPad RGB-D 비디오, Apple Vision Pro egocentric 영상을 COLMAP(Superpoint/Superglue) 기반으로 정합해 구성한, 주방·거실·침실·욕실을 포함한 다수 실내 공간에 대해 객체·interactive element·functional relationship을 open-vocabulary 라벨로 주석한 데이터셋.
- 역할: 기존 SceneFun3D를 확장하고, functional 3D scene graph 예측 방법을 정량적으로 평가할 수 있는 새로운 실측 벤치마크를 제공한다.

## 4. 구조 및 흐름
1. Node Candidate Detection: RAM++로 각 프레임에서 object tag를 얻고, GroundingDINO로 2D bounding box·segmentation mask를 탐지한다. GPT-4가 생성한 interactive element tag를 object tag와 결합한 프롬프트로 작은 부품도 함께 탐지하며, 여러 프레임의 2D 탐지 결과를 depth map과 카메라 투영 행렬로 융합해 point cloud·bounding box를 가진 3D node candidate를 구성한다.
2. Node Candidate Description: 의미적 confidence와 기하학적 기여도를 함께 고려해 상위 시점을 선택하고, LLAVA가 크롭된 객체의 caption을 생성하면 GPT-4가 이를 통합 서술로 요약한다. interactive element는 확대·강조된 crop으로 다중 스케일·다중 시점 caption을 합성한다.
3. Functional Relationship 추론: local relationship은 공간적 overlap 필터링 후 LLM이 언어 서술과 bounding box를 근거로 연결 타당성을 판단해 관계 서술을 생성하고, remote relationship은 LLM이 후보 pairing을 생성한 뒤 VLM이 물리적 타당성(전원 연결 여부 등)을 점검하고 LLM이 confidence score를 부여하는 confidence-aware reasoning으로 처리한다.
4. Graph Formation: local·remote subgraph를 하나의 최종 functional 3D scene graph로 결합한다.
5. Evaluation: node 탐지는 3D IoU와 CLIP 임베딩 유사도 순위 기준으로, triplet(객체·요소·관계) 평가는 BERT 임베딩 기반 top-K 순위 기준으로 확장된 SceneFun3D·FunGraph3D에서 Recall@K를 측정하고 Open3DSG·ConceptGraph 적용 baseline과 비교하며, 3D QA·robotic manipulation downstream 적용을 시연한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| functional 3D scene graph가 기존 spatial scene graph보다 풍부한 표현을 제공한다 | "functional 3D scene graphs capture objects, interactive elements, and their functional relationships" — 기존은 공간 관계만 표현 |
| foundation model 기반 접근이 적용된 기존 방법보다 우수하다 | "Our method significantly outperforms adapted baselines, including Open3DSG and ConceptGraph" |
| functional 3D scene graph가 실제 downstream task에 활용 가능하다 | "we also demonstrate downstream applications such as 3D question answering and robotic manipulation using functional 3D scene graphs" |
| 작은 interactive element 탐지에는 object 맥락을 결합한 프롬프트가 효과적이다 | GPT-4가 생성한 element tag를 object tag와 결합한 프롬프트가 "more accurate detection of small interactive parts"로 이어짐 |

## 6. 한계 및 부족한 점
- 확인한 범위(CVPR 논문 페이지, arXiv html 버전, Semantic Scholar) 내에서 별도의 명시적 limitations/future work 섹션은 확인되지 않는다.
- 평가가 "visually unambiguous"한 functional relationship으로 제한된다. 즉 egocentric 영상 등으로 명확히 확인 가능한 관계만 데이터셋 주석에 포함되어 있어, 모호한 관계에 대한 성능은 별도로 검증되지 않는다.
- 전체 파이프라인이 GPT-4, LLAVA 등 외부 foundation model의 성능과 가용성에 의존한다.
- 정확한 3D reconstruction(depth·pose가 포함된 posed RGB-D 입력)이 전제조건으로 요구된다.

## 7. 원문 기반 핵심 문장
> "We introduce the task of predicting functional 3D scene graphs for real-world indoor environments from posed RGB-D images. Unlike traditional 3D scene graphs that focus on spatial relationships of objects, functional 3D scene graphs capture objects, interactive elements, and their functional relationships."
