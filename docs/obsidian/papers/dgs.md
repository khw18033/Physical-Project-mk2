# Boosting Vision-Language Models Towards Cross-Domain Incremental Object Detection

## 메타데이터
- categories: [[Dynamic Task Grouping]], [[Incremental Group Adapters]], [[Intra-Group Consolidation]]
- domain: [[Vision-Language Model]], [[Incremental Object Detection]]
- source: Wang, Xu, Lin, Zihan, Zhang, Yixin, Wang, Zilei, "Boosting Vision-Language Models Towards Cross-Domain Incremental Object Detection", CVPR, 2026.
- url: https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Boosting_Vision-Language_Models_Towards_Cross-Domain_Incremental_Object_Detection_CVPR_2026_paper.html
- year: 2026
- authors: Xu Wang et al.
- venue: CVPR 2026

## 1. 핵심 요약
- vision-language 기반 탐지기가 여러 도메인과 신규 카테고리에 걸쳐 순차적으로 학습해야 하는 Cross-Domain Incremental Object Detection(CDIOD) 상황에서, task 분포 유사도에 따라 동적으로 그룹을 구성하고 그룹 단위 adapter를 점진적으로 공유 subspace에 통합하는 Dynamic Group Subspace(DGS) 프레임워크를 제안한다.
- 저자들은 CDIOD라는 새 벤치마크(DIOR, PascalVOC, RUOD 세 도메인)를 함께 제시하고, GroundingDINO를 기반 모델로 사용해 COCO 클래스 증분, CDIOD 도메인 증분, ODinW-13 task 증분 세 벤치마크에서 DGS를 평가한다.
- 공식 GitHub 저장소(Never-wx/dgs)는 MMDetection 3.3 기반으로 구현되어 있으며 LoRA, GroupLoRA, Adapter, RepLinear, MoE-LoRA, AdaptiveExpandMoE, Router 등의 PEFT 관련 모듈을 포함한다.

## 2. 문서 목적
- 해결하려는 문제: full fine-tuning 방식은 새로운 task에 대한 적응력(adaptivity)은 높지만 이전 지식을 심하게 잊어버리는 catastrophic forgetting 문제를 가지고, 기존 PEFT 기반 방법은 안정성(stability)은 확보하지만 CDIOD와 같은 cross-domain incremental 상황에서는 성능이 저하되어 stability-adaptivity 균형을 동시에 달성하지 못하는 문제.
- 기술적 목표: task를 분포 유사도에 따라 동적으로 그룹화하고, 그룹별로 확장 가능한 adapter를 두어 task-specific adapter를 진화하는 공유 subspace로 점진적으로 통합함으로써, 적은 추가 파라미터만으로 stability와 adaptivity를 함께 개선하는 DGS 프레임워크를 구현하는 것.
- 다루는 범위: GroundingDINO를 기반 vision-language 탐지기로 사용하고 vision/language branch의 feed-forward network에 LoRA 계열 adapter를 삽입하는 구조를 대상으로 하며, COCO(클래스 증분), 저자들이 새로 제안한 CDIOD(DIOR/PascalVOC/RUOD 도메인 증분), ODinW-13(task 증분) 세 벤치마크에서의 평가를 다룬다.

## 3. 핵심 개념 상세
### Dynamic Task Grouping
- 원문 표현: "Dynamic Task Grouping (DTG) adaptively groups tasks based on distributional similarity"
- 정의: feature space에서 각 task의 분포를 Gaussian으로 근사하고, 새로운 task와 기존 그룹 간 KL divergence가 임계값 τ 이하이면 해당 그룹에 편입시키고, 그렇지 않으면 새로운 그룹을 초기화하는 방식으로 task를 분포 유사도 기준으로 동적으로 묶는 메커니즘.
- 역할: 유사한 분포를 가진 task 사이의 지식 공유(knowledge sharing)를 촉진하고, 서로 이질적인 task 사이의 충돌(task collision)을 방지한다.

### Incremental Group Adapters
- 원문 표현: "Incremental Group Adapters (IGA) manage the expandable adapters tied to each group"
- 정의: 각 task 그룹마다 GroundingDINO의 vision branch와 language branch의 feed-forward network에 삽입되는 확장 가능한 LoRA/GroupLoRA 계열 adapter 모듈을 관리하는 컴포넌트.
- 역할: 그룹이 늘어날 때 파라미터를 점진적으로만 확장시켜, 전체 모델을 재학습하지 않고도 parameter efficiency를 유지하며 새 task를 반영할 수 있게 한다.

### Intra-Group Consolidation
- 원문 표현: "Intra-Group Consolidation (IGC) progressively consolidates task-specific adapters into an evolving shared subspace."
- 정의: task-specific adapter를 "αbase ← λαbase + (1−λ)αnew" 형태의 갱신식과 knowledge distillation 기반 정렬을 통해 그룹의 base adapter로 반복적으로 병합하는 과정.
- 역할: adapter 파라미터가 task 수에 비례해 무한히 늘어나는 것(parameter proliferation)을 방지하고, 그룹 내에서 점진적으로 진화하는 공유 subspace를 구성한다.

## 4. 구조 및 흐름
1. 새로운 task(도메인 또는 클래스 집합)가 순차적으로 들어오면, Dynamic Task Grouping이 feature 분포의 Gaussian 근사와 KL divergence 비교를 통해 기존 그룹에 편입할지 새 그룹을 생성할지 결정한다.
2. 배정된 그룹에 대해 Incremental Group Adapters가 GroundingDINO의 vision/language branch FFN에 확장형 LoRA/GroupLoRA adapter를 삽입해 해당 task를 학습한다.
3. 학습이 진행되며 Intra-Group Consolidation이 task-specific adapter를 group base adapter로 점진적으로 통합하고 knowledge distillation으로 이전 지식과의 정렬을 유지한다.
4. 통합된 group adapter들이 진화하는 공유 subspace를 형성하며, 이후 새 task/도메인이 도착할 때마다 1~3 과정을 반복해 COCO, CDIOD(DIOR/PascalVOC/RUOD), ODinW-13 벤치마크에서 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| DGS가 CDIOD에서 stability-adaptivity 균형을 크게 개선한다 | CDIOD(10 phases) 설정에서 추가 파라미터를 1.2%만 사용하고도 +11.4 AP 개선을 달성 |
| 단순 LoRA나 task별 독립 LoRA는 DGS의 그룹 기반 설계에 비해 열등하다 | ablation에서 "Single LoRA(Row 2)는 adaptivity는 있지만 심한 forgetting을 겪고, T-LoRA(Row 3)는 task별 LoRA를 학습해 파라미터가 선형적으로 증가하고 routing error를 유발한다"고 보고 |
| DGS의 개선이 CDIOD뿐 아니라 일반적인 task-incremental 상황에도 적용된다 | ODinW-13에서 평균 +1.2 AP 개선을 보고 |
| PEFT 기반 방법은 cross-domain 안정성은 낫지만 CDIOD에서 여전히 한계가 있다 | "PEFT-based methods achieve better cross-domain stability by isolating task-specific knowledge and preserving pre-trained representations. However, PEFT-based approaches still underperform in CDIOD due to two factors."라고 서술 |

## 6. 한계 및 부족한 점
- DGS는 정확한 task distribution 추정에 의존하며, 데이터가 제한적인 상황에서는 이 추정이 부정확해져 최적이 아닌 그룹화(suboptimal grouping)로 이어질 수 있다고 저자들이 명시한다.
- PEFT 기반 방법 일반이 CDIOD에서 성능이 떨어지는 구체적인 두 가지 요인의 세부 내용은 확인한 자료 범위에서 전체가 드러나지 않아 명시되지 않음.
- 대규모 정량 결과표, 전체 ablation 수치, 추론 비용·지연시간 등 세부 실험 결과는 원문 접근 제한으로 확인하지 못해 명시되지 않음.

## 7. 원문 기반 핵심 문장
> "DGS consists of three key components: Dynamic Task Grouping (DTG) adaptively groups tasks based on distributional similarity; Incremental Group Adapters (IGA) manage the expandable adapters tied to each group; and Intra-Group Consolidation (IGC) progressively consolidates task-specific adapters into an evolving shared subspace."
