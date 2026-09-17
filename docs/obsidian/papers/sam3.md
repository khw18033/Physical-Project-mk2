# SAM 3: Segment Anything with Concepts

## 메타데이터
- categories: Promptable Concept Segmentation, Presence Head 기반 인식-위치추정 분리, 이미지-비디오 통합 Backbone, SA-Co 데이터 엔진
- domain: [[객체 탐지·분할]]
- source: Meta AI (Carion, Nicolas, Feichtenhofer, Christoph, et al.). "SAM 3: Segment Anything with Concepts." arXiv preprint arXiv:2511.16719, 2025.
- url: https://ai.meta.com/research/sam3/
- year: 2025
- authors: Carion, Feichtenhofer et al. (Meta AI, 38인)
- venue: arXiv preprint (arXiv:2511.16719)

## 1. 핵심 요약
- SAM 3는 이미지와 비디오에서 concept prompt(짧은 명사구, 이미지 예시(exemplar), 또는 둘의 조합)에 기반해 객체를 탐지·분할·추적하는 통합 모델이다.
- Promptable Concept Segmentation(PCS)이라는 태스크를 정의한다: concept prompt를 받아 매칭되는 모든 객체 인스턴스에 대한 분할 마스크와 고유 identity를 반환한다.
- 이미지 수준 detector와 memory 기반 video tracker가 하나의 backbone을 공유하며, recognition(인식)과 localization(위치추정)을 presence head로 분리해 검출 정확도를 높인다.
- hard negative를 포함해 400만 개의 고유 concept label 규모의 SA-Co(Segment Anything with Concepts) 데이터셋을 생성하는 확장 가능한 data engine을 구축했다.
- 이미지·비디오 PCS 모두에서 기존 시스템 대비 정확도를 두 배로 높였고, 기존 SAM의 visual segmentation 능력도 함께 개선했다.

## 2. 문서 목적
- 해결하려는 문제: 기존 SAM 계열은 점·박스 등 시각적 프롬프트로 단일 객체를 분할하는 데는 강했지만, "이 개념에 해당하는 모든 객체"를 텍스트나 예시로 한 번에 찾아 분할·추적하는 능력은 부족했다.
- 기술적 목표: 텍스트 명사구와 이미지 예시를 결합한 concept prompt로 이미지·비디오 전반에서 모든 매칭 인스턴스를 탐지·분할·추적하는 단일 모델과, 이를 학습·평가하기 위한 대규모 데이터셋·벤치마크를 구축하는 것.
- 다루는 범위: PCS 태스크 정의, SA-Co 데이터 엔진과 데이터셋 구축, 이미지 detector와 video tracker가 backbone을 공유하는 아키텍처, presence head 설계, 이미지·비디오 PCS 및 기존 visual segmentation 벤치마크에서의 성능 평가.

## 3. 핵심 개념 상세
### Promptable Concept Segmentation (PCS)
- 원문 표현: "Promptable Concept Segmentation (PCS) takes such prompts and returns segmentation masks and unique identities for all matching object instances."
- 정의: 짧은 명사구, 이미지 예시, 또는 둘의 조합으로 주어지는 concept prompt를 입력받아, 이미지나 비디오 안에서 그 개념에 해당하는 모든 객체 인스턴스의 분할 마스크와 고유 identity를 반환하는 태스크.
- 역할: 상자 하나로 객체 하나를 지정하던 기존 promptable segmentation을 "이 개념에 맞는 모든 객체"를 한 번에 찾는 문제로 확장해, 반복적인 프롬프트 없이 특정 범주의 모든 인스턴스를 일괄적으로 얻을 수 있게 한다.

### Concept Prompt (텍스트·이미지 예시 프롬프트)
- 원문 표현: "objects in images and videos based on concept prompts, which we define as either short noun phrases (e.g., \"yellow school bus\"), image exemplars, or a combination of both."
- 정의: "yellow school bus"와 같은 짧은 명사구, 대상 객체를 보여주는 이미지 예시(exemplar), 혹은 이 둘을 결합한 형태로 주어지는 프롬프트.
- 역할: 사용자가 원하는 대상을 카테고리 이름이나 시각적 예시 중 편한 방식으로, 또는 둘을 함께 사용해 지정할 수 있게 하여 open-vocabulary한 대상 지정을 지원한다.

### 이미지-비디오 통합 Backbone과 Presence Head
- 원문 표현: "Our model consists of an image-level detector and a memory-based video tracker that share a single backbone. Recognition and localization are decoupled with a presence head, which boosts detection accuracy."
- 정의: 이미지 수준의 detector와 프레임 간 정보를 기억하는 memory 기반 video tracker가 하나의 backbone을 공유하는 구조이며, "이 개념이 존재하는가"를 판단하는 recognition과 "어디에 있는가"를 판단하는 localization을 별도의 presence head로 분리한 설계.
- 역할: 이미지와 비디오라는 서로 다른 입력 형태에 대해 별도 모델을 두지 않고 backbone을 재사용하며, recognition과 localization을 분리함으로써 개념이 존재하지 않는 경우의 오탐을 줄여 검출 정확도를 높인다.

### SA-Co 데이터 엔진과 데이터셋
- 원문 표현: "we build a scalable data engine that produces a high-quality dataset with 4M unique concept labels, including hard negatives, across images and videos."
- 정의: 이미지와 비디오에 걸쳐 400만 개의 고유 concept label과 hard negative(개념이 존재하지 않는 상황) 샘플을 포함한 고품질 데이터셋(SA-Co)을 생성하는 확장 가능한 데이터 생성 파이프라인.
- 역할: PCS처럼 "모든 매칭 인스턴스"를 찾아야 하고 "개념이 아예 없는 경우"도 구분해야 하는 태스크를 학습·평가하기 위해, 기존 COCO/LVIS보다 넓은 범위의 concept label과 hard negative를 갖춘 데이터 기반을 제공한다.

## 4. 구조 및 흐름
1. 사용자가 짧은 명사구, 이미지 예시, 또는 둘을 결합한 concept prompt를 입력한다.
2. 이미지 입력의 경우 이미지 수준 detector가 공유 backbone에서 얻은 feature 위에서 presence head로 개념의 존재 여부를 먼저 판단하고, 존재하면 위치(localization)를 함께 추정한다.
3. 비디오 입력의 경우 동일한 공유 backbone을 사용하는 memory 기반 video tracker가 프레임 간 정보를 유지하며 개념에 해당하는 인스턴스의 identity를 시간에 걸쳐 유지한다.
4. 매칭되는 모든 인스턴스에 대해 분할 마스크와 고유 identity가 함께 출력된다.
5. SA-Co 데이터 엔진으로 생성된 대규모 concept label·hard negative 데이터로 모델을 학습하고, 새로 구축한 SA-Co 벤치마크로 PCS 성능을 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| SAM 3가 이미지·비디오 PCS 모두에서 기존 시스템보다 크게 우수하다 | "SAM 3 doubles the accuracy of existing systems in both image and video PCS" |
| recognition과 localization을 분리하는 presence head가 검출 정확도를 높인다 | "Recognition and localization are decoupled with a presence head, which boosts detection accuracy."라고 원문에서 직접 명시 |
| 대규모 SA-Co 데이터셋이 PCS 학습·평가에 필요한 기반을 제공한다 | "a scalable data engine that produces a high-quality dataset with 4M unique concept labels, including hard negatives, across images and videos" |
| SAM 3가 기존 SAM의 visual segmentation 능력도 함께 향상시킨다 | "improves previous SAM capabilities on visual segmentation tasks"라고 원문에서 명시 |

## 6. 한계 및 부족한 점
- ai.meta.com/research/sam3/ 공식 페이지는 자동 수집 시 제목 외 본문이 확보되지 않아, 본 문서는 대응하는 arXiv(2511.16719) abstract를 주 출처로 사용했다.
- 확인한 범위(abstract)에서는 저자가 스스로 명시한 한계나 실패 사례에 대한 구체적 서술은 확인되지 않았으며, 방법론 세부(presence head의 구체적 학습 방식, memory 기반 tracker의 세부 구조)는 abstract 수준에서 확인되지 않는다.
- "doubles the accuracy" 같은 정량적 향상 수치가 어떤 baseline·지표 기준인지에 대한 세부 수치는 abstract에서 확인되지 않는다.

## 7. 원문 기반 핵심 문장
> "We present Segment Anything Model (SAM) 3, a unified model that detects, segments, and tracks objects in images and videos based on concept prompts, which we define as either short noun phrases (e.g., \"yellow school bus\"), image exemplars, or a combination of both."
