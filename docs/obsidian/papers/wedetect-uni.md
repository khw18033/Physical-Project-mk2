# WeDetect: Fast Open-Vocabulary Object Detection as Retrieval

## 메타데이터
- categories: Retrieval 기반 Object Detection, Dual-tower Non-fusion 아키텍처, WeDetect-Uni Generic Object Proposal, Text/Category Retrieval 분리
- domain: [[객체 탐지·분할]]
- source: Fu, Shenghao, Su, Yukun, Rao, Fengyun, Lyu, Jing, Xie, Xiaohua, Zheng, Wei-Shi. "WeDetect: Fast Open-Vocabulary Object Detection as Retrieval." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2026.
- url: https://openaccess.thecvf.com/content/CVPR2026/html/Fu_WeDetect_Fast_Open-Vocabulary_Object_Detection_as_Retrieval_CVPR_2026_paper.html
- year: 2026
- authors: Fu et al.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)

## 1. 핵심 요약
- Open-vocabulary object detection에서 recognition을 이미지 영역(region)과 텍스트 쿼리를 공유 embedding space에서 매칭하는 retrieval 문제로 재정의한다.
- Non-fusion 방법은 dual-tower 아키텍처를 채택해 fusion 기반 방법보다 빠른 추론 속도를 얻지만 정확도가 낮은 경향이 있었는데, WeDetect는 잘 정제된 데이터와 충분한 학습으로 fusion 모델을 능가한다.
- WeDetect-Uni는 전체 detector를 freeze하고 objectness embedding(objectness prompt)만 추가로 학습해 카테고리에 무관한 generic object proposal을 생성하고, 이 proposal embedding으로 과거 데이터에 대한 object retrieval을 지원한다.
- WeDetect-Ref는 LMM 기반 이진 분류 모델로, WeDetect-Uni가 추출한 proposal 목록에서 복잡한 referring expression에 해당하는 대상을 retrieval한다.
- WeDetect-Large는 LVIS에서 49.4 AP로 LLMDet 대비 7.4 AP 높고, WeDetect-Ref 4B는 refcoco/+/g 평균 93.2점으로 Qwen3-VL 4B 대비 6.5점 높으면서 13배 빠르다. 전체적으로 15개 벤치마크에서 state-of-the-art 성능과 높은 추론 효율을 함께 달성한다.

## 2. 문서 목적
- 해결하려는 문제: fusion 기반 open-vocabulary detector는 정확도가 높지만 cross-modal fusion layer 때문에 추론이 느리고, 기존 non-fusion(dual-tower) 방법은 빠르지만 정확도가 fusion 모델에 미치지 못하는 trade-off가 존재한다.
- 기술적 목표: recognition을 retrieval 문제로 재정의해 non-fusion dual-tower 구조로도 fusion 모델을 능가하는 정확도와 실시간에 가까운 속도를 동시에 달성하는 것.
- 다루는 범위: WeDetect(기본 detector), WeDetect-Uni(universal proposal generator), WeDetect-Ref(referring expression comprehension) 세 변형의 설계와 15개 벤치마크에서의 평가.

## 3. 핵심 개념 상세
### Retrieval 기반 Open-Vocabulary Detection 재정의
- 원문 표현: "Recognition is similar to the retrieval problem, which matches image regions against text queries in a shared embedding space."
- 정의: 객체 인식을 이미지 영역(region)과 텍스트 쿼리를 하나의 공유 embedding space에서 매칭하는 retrieval 작업으로 재정의하는 접근.
- 역할: cross-modal fusion 없이도 region embedding과 text embedding 간 유사도 계산만으로 카테고리를 식별할 수 있게 해, open-vocabulary detection의 추론 구조를 단순화한다.

### Dual-tower Non-fusion 아키텍처
- 원문 표현: "Non-fusion methods adopt a dual-tower architecture and enjoy a fast inference speed."
- 정의: 이미지 인코더와 텍스트 인코더를 분리된 두 tower로 독립 실행하고 cross-modal fusion layer를 두지 않는 구조.
- 역할: 연산 비용이 큰 fusion layer("computationally intensive fusion layers")를 제거해 추론 효율을 높이며, 텍스트 쿼리가 바뀌어도 이미지 encoder 연산 결과를 재사용할 수 있게 한다.

### WeDetect-Uni Generic Object Proposal
- 원문 표현: "We freeze the entire detector and train only an objectness embedding for classification."
- 정의: 학습이 끝난 WeDetect detector 전체를 고정한 채 카테고리에 무관한 objectness embedding(objectness prompt) 하나만 추가로 학습해, 임의의 객체를 카테고리 구분 없이 proposal로 추출하는 방식.
- 역할: "arbitrary objects via a universal objectness prompt"를 추출해 특정 카테고리 집합에 종속되지 않는 범용 object proposal을 생성하고, 이렇게 얻은 proposal embedding을 이용해 과거에 저장된 이미지에서 object retrieval을 가능하게 한다.

### Text/Category Retrieval 분리
- 원문 표현: "Once a new query arrives, a simple dot production is needed for fast retrieval."
- 정의: 이미지에서 미리 추출해 둔 object embedding 집합과 새로 들어온 텍스트(카테고리) 쿼리의 embedding 사이의 dot product만으로 매칭을 수행하는 절차.
- 역할: 새로운 카테고리·쿼리가 추가되어도 이미지를 다시 인코딩할 필요 없이 저장된 object embedding과의 내적만 다시 계산하면 되므로, 카테고리 확장과 반복 질의에 드는 비용을 크게 줄인다.

## 4. 구조 및 흐름
1. Dual-tower 구조로 이미지 encoder가 region-level visual embedding을, text encoder가 카테고리/쿼리 텍스트의 embedding을 각각 독립적으로 계산한다.
2. 학습 단계에서 region embedding과 text embedding이 공유 embedding space에 정렬되도록 retrieval(대조) 방식으로 학습한다.
3. 추론 시 새로운 텍스트 쿼리가 들어오면 이미지를 다시 인코딩하지 않고, 이미 계산된 region embedding과 쿼리 embedding 간 dot product로 매칭한다("a set of object embeddings to represent an image").
4. WeDetect-Uni는 학습된 WeDetect 전체를 freeze한 채 objectness embedding만 추가 학습해, 카테고리 무관 generic proposal과 그 embedding을 함께 산출한다.
5. WeDetect-Ref는 WeDetect-Uni가 추출한 proposal 목록을 입력으로 받아 LMM 기반 이진 분류로 복잡한 referring expression에 해당하는 대상을 retrieval한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| non-fusion 구조도 fusion 모델을 능가할 수 있다 | WeDetect-Large가 LVIS에서 49.4 AP를 기록해 LLMDet 대비 7.4 AP 높음 |
| WeDetect-Uni의 objectness prompt로 범용 proposal과 retrieval이 가능하다 | 전체 detector를 freeze하고 objectness embedding만 학습해 "arbitrary objects via a universal objectness prompt"를 추출하고, 이를 통해 과거 데이터에서 object retrieval을 지원함 |
| WeDetect-Ref가 LMM 기반 referring expression에서 효율적이다 | refcoco/+/g 평균 93.2점으로 Qwen3-VL 4B 대비 6.5점 높고 13배 빠른 추론 속도를 달성 |
| 전체 프레임워크가 다양한 태스크에서 SOTA와 효율을 동시에 달성한다 | "state-of-the-art performance across 15 benchmarks with high inference efficiency" |

## 6. 한계 및 부족한 점
- WeDetect-Ref는 이진 분류 모델이라 한 번의 forward pass에서 여러 쿼리를 동시에 처리하지 못한다: "WeDetect-Ref is a binary classification model, which does not support detecting multiple queries in a single forward pass."
- CVF 공식 페이지(openaccess.thecvf.com)는 접근이 차단되어(HTTP 403) arXiv(2512.12309)와 ar5iv 렌더링본을 기준으로 확인했으며, 최종 CVPR 게재본과 세부 표현·수치가 다를 수 있다.
- 확인한 범위에서는 fusion 기반 최상위 모델 대비 rare class 등 특정 세부 카테고리에서의 성능 격차나 구체적 실패 사례에 대한 별도 논의는 확인되지 않았다.

## 7. 원문 기반 핵심 문장
> "Recognition is similar to the retrieval problem, which matches image regions against text queries in a shared embedding space."
