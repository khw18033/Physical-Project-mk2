# MetaDepth-CPU: Zero-Shot Monocular Depth Estimation for Edge Devices

## 메타데이터
- categories: Zero-Shot Monocular Depth Estimation, ViT-G Teacher Knowledge Distillation, Convolutional Encoder-Decoder 경량 아키텍처, Mobile CPU 실시간 추론
- domain: [[3D 인지]], [[엣지 실행·자원]]
- source: Mapeke, Marc, Zhang, Zaiwei, Ye, Wei, Ranjan, Rakesh, Huang, JQ. "MetaDepth-CPU: Zero-Shot Monocular Depth Estimation for Edge Devices." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW), 2026.
- url: https://openaccess.thecvf.com/content/CVPR2026W/ECV/html/Mapeke_MetaDepth-CPU_Zero-Shot_Monocular_Depth_Estimation_for_Edge_Devices_CVPRW_2026_paper.html
- year: 2026
- authors: Mapeke, Marc et al.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW), Efficient Computer Vision (ECV) 워크숍

## 1. 핵심 요약
- 모노큘러(단안) depth estimation은 증강현실, computational photography, 엣지 디바이스에서의 실시간 장면 이해 등 모바일 인지(mobile perception)의 핵심 능력이다.
- 최근 depth foundation model들은 수천만~수억 파라미터 규모의 대형 transformer 구조와 연산 비용이 큰 attention 메커니즘에 의존해 모바일 CPU에서의 실시간 추론에 부적합하다.
- MetaDepth-CPU는 모바일 디바이스에 배포 가능한 경량 convolutional encoder-decoder 아키텍처와, 고용량 ViT-G teacher 모델로부터의 대규모 knowledge distillation을 결합한 compact depth foundation model 계열이다.
- 다양한 synthetic 데이터로 학습된 ViT-G teacher로부터 distillation함으로써 경량 student 모델도 강한 geometric prior와 zero-shot 일반화 능력을 갖춘다.
- MetaDepth-CPU는 가장 작은 SOTA GPU 모델 대비 2~5배 적은 파라미터로 경쟁력 있는 zero-shot 성능을 내며, GPU나 NPU 가속 없이 모바일 CPU에서 15~30 FPS로 동작한다.

## 2. 문서 목적
- 해결하려는 문제: 최신 depth foundation model이 뛰어난 zero-shot 일반화 성능을 보이지만 대형 transformer·attention 구조 때문에 GPU/NPU가 없는 모바일 CPU 환경에서는 실시간 추론이 어려운 문제.
- 기술적 목표: 대형 ViT-G teacher가 가진 geometric prior와 zero-shot 일반화 능력을, 경량 convolutional encoder-decoder 구조의 student 모델에 knowledge distillation으로 옮겨 모바일 CPU에서도 실시간 동작이 가능한 depth foundation model을 만드는 것.
- 다루는 범위: MetaDepth-CPU 아키텍처(경량 conv encoder-decoder) 설계, ViT-G teacher로부터의 대규모 knowledge distillation 절차, 파라미터 수·zero-shot 정확도·모바일 CPU 추론 속도(FPS) 비교.

## 3. 핵심 개념 상세
### Zero-Shot Monocular Depth Estimation (모바일 대상)
- 원문 표현: "Monocular depth estimation is a key capability for mobile perception and embodied intelligence, enabling applications such as augmented reality, computational photography, and real-time scene understanding on edge devices."
- 정의: 학습 시 보지 못한 장면·도메인에서도 별도의 fine-tuning 없이 단일 카메라 영상만으로 픽셀별 깊이를 추정하는 능력을, 모바일·엣지 디바이스에서 실시간으로 제공하는 것.
- 역할: 증강현실 오브젝트 배치, computational photography의 피사계심도 효과, 엣지 디바이스에서의 실시간 장면 이해처럼 별도 깊이 센서 없이도 단안 카메라만으로 동작해야 하는 응용의 기반이 된다.

### 대형 Transformer 기반 Depth Foundation Model의 배포 한계
- 원문 표현: "Recent depth foundation models rely on large transformer architectures with tens to hundreds of millions of parameters and computationally expensive attention mechanisms, making them impractical for real-time inference on mobile CPUs."
- 정의: 수천만에서 수억 개 파라미터 규모의 transformer와 연산 비용이 큰 attention 메커니즘을 사용하는 최신 depth foundation model 계열.
- 역할: 높은 zero-shot 정확도의 원천이지만, 동시에 GPU/NPU 가속이 없는 모바일 CPU에서는 실시간 추론이 사실상 불가능하게 만드는 제약 조건으로 작용하며, MetaDepth-CPU가 극복하려는 대상이다.

### ViT-G Teacher 기반 대규모 Knowledge Distillation
- 원문 표현: "The approach combines an efficient convolutional encoder–decoder architecture with large-scale knowledge distillation from a high-capacity ViT-G teacher model trained on diverse synthetic data."
- 정의: 다양한 synthetic 데이터로 학습된 고용량 ViT-G teacher 모델의 지식을, 경량 convolutional encoder-decoder 구조의 student 모델에 대규모(1억 5천만 장 이상 이미지 규모)로 distillation하는 절차.
- 역할: teacher가 학습한 강한 geometric prior와 zero-shot 일반화 능력을 경량 student 모델이 이어받게 하여, 파라미터 수는 크게 줄이면서도 경쟁력 있는 zero-shot depth 정확도를 유지하게 한다.

### 경량 Convolutional Encoder-Decoder 아키텍처
- 정의: attention 기반 transformer 대신 convolution 연산 중심으로 구성된 encoder-decoder 구조의 depth estimation 모델.
- 역할: transformer의 attention 연산이 갖는 높은 연산·메모리 비용을 피해, GPU·NPU 가속 없이도 모바일 CPU에서 15~30 FPS의 실시간 추론 속도를 낼 수 있게 하는 MetaDepth-CPU의 핵심 아키텍처 선택이다.

## 4. 구조 및 흐름
1. 고용량 ViT-G teacher 모델을 다양한 synthetic 데이터로 학습시켜 강한 geometric prior와 zero-shot 일반화 능력을 확보한다.
2. 경량 convolutional encoder-decoder 구조의 student 모델(MetaDepth-CPU)을 정의한다.
3. 1억 5천만 장이 넘는 다양한 이미지에 대해 teacher의 출력을 이용한 대규모 knowledge distillation으로 student를 학습시킨다.
4. 학습된 student 모델을 모바일 CPU 환경에 배포해 GPU·NPU 가속 없이 단안 영상으로부터 깊이를 실시간 추정한다.
5. 파라미터 수, zero-shot 정확도, 모바일 CPU 상에서의 FPS를 기준으로 기존 SOTA GPU 모델과 비교 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 대형 transformer 기반 depth foundation model은 모바일 CPU 실시간 추론에 부적합하다 | "large transformer architectures with tens to hundreds of millions of parameters and computationally expensive attention mechanisms, making them impractical for real-time inference on mobile CPUs" |
| ViT-G teacher로부터의 distillation으로 경량 모델도 강한 zero-shot 능력을 가질 수 있다 | "large-scale knowledge distillation from a high-capacity ViT-G teacher model trained on diverse synthetic data"를 통해 "competitive zero-shot performance" 달성 |
| MetaDepth-CPU가 훨씬 적은 파라미터로 경쟁력 있는 성능을 낸다 | "using 2-5x fewer parameters than the smallest SOTA GPU models" |
| GPU/NPU 없이 모바일 CPU에서 실시간 동작이 가능하다 | "run at 15–30 FPS on mobile CPUs, enabling real-time depth-aware applications without requiring GPU or NPU acceleration" |

## 6. 한계 및 부족한 점
- CVF 공식 HTML/PDF 페이지는 자동 수집 시 본문이 비어 있거나 접근이 차단되어(HTTP 403/빈 콘텐츠), 검색 엔진이 색인한 abstract 스니펫을 통해서만 내용을 확인했다.
- 확인한 범위(abstract 스니펫)에서는 저자가 명시한 구체적 한계·failure case·future work에 대한 서술은 확인되지 않았다.
- "2-5x fewer parameters", "15-30 FPS" 등의 수치가 어떤 구체적 모델 변형(크기)과 어떤 벤치마크·디바이스 기준인지에 대한 세부 정보는 확인하지 못했다.

## 7. 원문 기반 핵심 문장
> "MetaDepth-CPU is a family of compact monocular depth estimation foundation models designed for efficient deployment on mobile devices."
