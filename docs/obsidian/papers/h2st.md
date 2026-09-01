# H2ST: Hierarchical Two-Sample Tests for Continual Out-of-Distribution Detection

## 메타데이터
- categories: [[Hierarchical Two-Sample Tests (H2ST)]], [[Classifier Two-Sample Test (C2ST)]], [[Feature-level Source-Target Prediction]], [[Calibrated Detection]]
- domain: [[Out-of-Distribution Detection]], [[Continual Learning]]
- source: Yuhang Liu, Wenjie Zhao, Yunhui Guo, "H2ST: Hierarchical Two-Sample Tests for Continual Out-of-Distribution Detection," Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025, pp. 15413-15423.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Liu_H2ST_Hierarchical_Two-Sample_Tests_for_Continual_Out-of-Distribution_Detection_CVPR_2025_paper.html
- year: 2025
- authors: Liu et al.
- venue: CVPR 2025 (IEEE/CVF Conference on Computer Vision and Pattern Recognition)

## 1. 핵심 요약
- Task Incremental Learning(TIL)을 open-world 환경으로 확장하면서, 모델 출력(softmax/logit/energy)에 의존하는 기존 OOD detection 방법들의 문제점(임계값 선택 어려움, 모델 성능 의존, task-id 미제공)을 통계적 two-sample test로 해결한 방법이 H2ST(Hierarchical Two-sample Tests)다.
- H2ST는 raw sample이나 모델 출력이 아니라 feature map을 입력으로 사용하는 source-target classifier들을 task별로 계층 구조로 쌓아, 임계값 없이 hypothesis testing만으로 ID/OOD 판정과 task-id 예측을 동시에 수행한다.
- MNIST, SVHN, CIFAR-10, CIFAR-100, Mini-ImageNet, CoRe50, Stream-51 등 7개 데이터셋과 ER, GEM 두 replay 기반 TIL 방법 위에서 MSP, Energy, ODIN, MaxLogit, Gentropy, FeatureNorm, MORE 등 기존 OOD detection 방법 대비 일관되게 우수한 F1과 task-id accuracy(TA)를 보였다.

## 2. 문서 목적
- 해결하려는 문제: 기존 TIL 방법들은 closed-world 가정(테스트 데이터가 항상 in-distribution) 하에서만 동작하며, open-world에서 OOD 샘플이 유입되면 (1) 스코어 기반 OOD 방법들이 임계값 선택에 의존하고, (2) 모델 성능(softmax/logit 품질)에 과도하게 종속되며, (3) ID/OOD 이진 분류만 가능할 뿐 어떤 task에 속하는 ID 샘플인지(task-id) 식별하지 못한다는 세 가지 한계가 있다.
- 기술적 목표: 임계값 선택 없이(threshold-free) hypothesis testing으로 OOD를 판정하고, 모델의 출력이 아닌 feature map을 활용해 모델 성능에 대한 과도한 의존을 줄이며, 계층적(hierarchical) 구조로 task-level의 세밀한 ID 판정 및 task-id 예측을 낮은 연산 오버헤드로 수행하는 것이다.
- 다루는 범위: open-world TIL이라는 새로운 문제 설정을 정의하고, 이를 위한 continual OOD detection 방법(H2ST)을 replay 기반 TIL(ER, GEM) 위에서 설계·검증한다. Continual learning 자체의 catastrophic forgetting 완화는 본 논문의 핵심 목표가 아니며, OOD detection이 TIL 성능에 미치는 영향만 부수적으로 분석한다.

## 3. 핵심 개념 상세
### Hierarchical Two-Sample Tests (H2ST)
- 원문 표현: "H2ST is composed of T task-speciﬁc two-sample test layers that are cascaded together, with each layer equipped with a source-target classiﬁer initialized via Xavier initialization."
- 정의: 학습된 task 수 T개에 대응하는 task별 source-target classifier {g1, g2, ..., gT}를 계층적으로 연결한 구조로, 각 layer가 feature-level source-target prediction → online classifier update → calibrated detection의 3단계를 수행하는 continual OOD detection 방법.
- 역할: 새 target 샘플이 첫 layer부터 순차적으로 판정을 거치며, 특정 layer에서 confident하게 ID로 판정되면 early-exit하고 그 layer의 인덱스를 task-id로 간주한다. 모든 T개 layer에서 기각되면 해당 샘플을 OOD로 분류한다.

### Classifier Two-Sample Test (C2ST)
- 원문 표현: "Nevertheless, C2ST does not apply to continual OOD detection, due to the following limitations. Raw samples lead to high-dimensional inputs, raising costs, and missing high-level semantics. A single binary classiﬁer lacks task-id identiﬁcation, while using a speciﬁc classiﬁer per task complicates the classiﬁcation and increases overhead as the number of tasks grows."
- 정의: 두 표본이 같은 분포에서 나왔는지 판별하기 위해 source/target 샘플을 구분하는 이진 classifier를 학습하고, 그 accuracy를 test statistic으로 사용해 통계적으로 유의성을 검정하는 고전적 two-sample test 기법.
- 역할: H2ST가 계승·개선하는 기반 방법이자 비교 baseline이다. 단일 classifier(single-C2ST)는 task-id를 구분하지 못하고, task별로 별도 classifier를 두는 C2ST는 task 수가 늘어날수록 모든 T개 classifier를 매 샘플마다 평가해야 해 연산 비용이 커진다는 한계가 H2ST 설계의 직접적 동기가 된다.

### Feature-level Source-Target Prediction
- 원문 표현: "Unlike C2ST, which directly uses raw samples, H2ST instead employs feature representations as input to the classiﬁer gj, i.e., ŷτ,j = gj(φ(xτ,j)) and ŷ'τ,j = gj(φ(x'τ)), and we do not use the output of the TIL model fθ as most OOD detection methods do."
- 정의: 메모리 버퍼에서 뽑은 source 샘플과 새로 관측된 target 샘플을 TIL 모델 fθ에 통과시켜 얻은 feature map φ(x)를 각 layer의 source-target classifier gj의 입력으로 사용해 source/target 여부를 예측하는 H2ST의 첫 번째 단계.
- 역할: raw 샘플의 고차원성·의미 부족 문제와 모델 출력(softmax/logit) 기반 방법의 모델 성능 의존 문제를 동시에 회피하면서, 고수준 feature 표현을 최대한 활용하도록 한다.

### Calibrated Detection
- 원문 표현: "The detector dj of the j-th two-sample test layer can directly determine whether a sample is ID or OOD for the j-th task, eliminating the need for a threshold."
- 정의: Clopper-Pearson(CP) 구간을 이용해 source-target classifier의 정확도 추정치 μ̂w,τ,j가 우연 수준(1/2)과 통계적으로 구분되는지를 유의수준 α와 window size w 하에서 검정함으로써 ID/OOD를 판정하는 H2ST 각 layer의 세 번째 단계.
- 역할: 스코어 기반 OOD 방법들이 요구하는 임의의 threshold 선택 과정을 통계적 가설검정으로 대체해 threshold-free 판정을 가능하게 하며, 이 판정 결과가 각 layer의 early-exit 여부와 최종 task-id 결정에 직접 사용된다.

## 4. 구조 및 흐름
1. Replay 기반 TIL 모델 fθ가 순차적인 task 스트림 {D1, ..., DN}으로부터 incremental하게 학습되며, 각 task의 일부 샘플이 메모리 버퍼 {B1, ..., BT}에 저장된다.
2. 탐지 시점 τ마다 새 target 샘플 x'τ가 관측되면 TIL 모델을 통해 feature map φ(x'τ)를 얻고, 첫 번째 layer(j=1)부터 순차적으로 진입한다.
3. 각 layer j에서 메모리 버퍼 Bj에서 뽑은 source 샘플의 feature와 target feature를 해당 layer의 source-target classifier gj에 입력해(Step 1) source/target을 예측하고, gj를 온라인으로 업데이트한 뒤(Step 2) CP 구간 기반 calibrated detection으로 ID/OOD를 판정한다(Step 3).
4. 특정 layer에서 ID로 판정되면 그 즉시 종료(early-exit)하고 해당 layer 인덱스를 task-id로 반환하며, 모든 T개 layer에서 기각되면 샘플을 OOD로 분류한다. ID 샘플은 TIL 모델로 label을 추가 예측하고, OOD 샘플은 라벨링 후 다음 task의 학습 데이터로 재사용된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| H2ST는 기존 OOD detection 방법(MSP, Energy, ODIN, MaxLogit, Gentropy, FeatureNorm, MORE) 대비 continual OOD detection에서 일관되게 우수하다 | Table 1: ER 기준 평균 F1 86.49%/TA 88.05%, GEM 기준 평균 F1 89.12%/TA 89.10%로 모든 baseline을 상회하며, CIFAR-10에서 ER 기준 2위 대비 F1 +25.92%, TA +30.79% |
| Hierarchical 구조는 non-hierarchical C2ST보다 OOD detection 성능이 높으면서 연산 오버헤드는 더 낮다 | Ablation: 전체 데이터셋·TIL 방법 평균 F1 +11.37%, TA +4.20% 개선. T=9일 때 샘플당 처리 시간이 H2ST 16.7ms, C2ST 22.0ms |
| 향상된 OOD detection은 더 많은 다양한 학습 데이터를 확보하게 하여 TIL 분류 정확도(ACC)를 높이지만 forgetting(FT)은 악화시키는 trade-off가 존재한다 | Table 2: 평균 ACC가 2위 방법(MORE) 대비 +2.59% 증가; 본문에서 "it concurrently exacerbates forgetting"이라고 명시 |
| 메모리 버퍼 크기가 커질수록 모든 지표가 개선되지만 OOD detection 지표는 일정 크기 이후 수익 체감(diminishing returns)을 보인다 | Fig. 4 및 Table 3: memory size 40→300 구간에서 H2ST의 ACC/F1/TA가 지속 상승하나 상승폭이 점차 감소, 모든 memory size에서 H2ST가 C2ST·Gentropy를 상회 |

## 6. 한계 및 부족한 점
- 논문에 별도의 "Limitations" 섹션은 명시되어 있지 않으며, 본문 곳곳에 서술된 trade-off와 제약만 확인된다.
- OOD detection 성능이 향상될수록 새 task 학습 데이터가 늘어나 forgetting이 악화되는 trade-off가 존재한다고 저자가 직접 언급한다: "Meanwhile, it concurrently exacerbates forgetting... This tension highlights a critical trade-off inherent to continual learning: balancing new knowledge integration against previous knowledge preservation, but it's not the focus of this paper."
- H2ST는 "achieves seamless integration with replay-based TIL methods by directly utilizing their inherent memory buffers"라고 명시되어 있어, 메모리 버퍼를 사용하지 않는 regularization 기반·architecture 기반 CL 방법에 대한 적용 가능성은 논문에서 다루지 않는다(replay-based 방법인 ER, GEM에서만 검증됨).
- Task 수 T가 늘어나면 H2ST도 여전히 최대 T개의 source-target classifier를 유지·평가해야 하며, C2ST 대비 평균 (T+1)/2로 줄어들 뿐 완전히 상수 오버헤드는 아니다. 또한 저자는 "we compare the performance of H2ST with baselines in Table 1, but omit computational overhead comparisons"라고 밝혀, 스코어 기반 baseline들과의 연산 오버헤드 비교는 C2ST 대비로만 제공되고 MSP·Energy 등과는 제공되지 않는다.
- 메모리 크기가 작을 때는 저장된 샘플이 task 분포를 충분히 대표하지 못해 성능이 저하되며, 최적 메모리 크기 결정에는 "trade-off between achieving peak performance and cost-effectiveness"에 대한 별도 고려가 필요하다고 명시되어 있다.

## 7. 원문 기반 핵심 문장
> H2ST eliminates the need for threshold selection through hypothesis testing and utilizes feature maps to better exploit model capabilities without excessive dependence on model performance.
