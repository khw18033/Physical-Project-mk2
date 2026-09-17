# Depth Any Camera: Zero-Shot Metric Depth Estimation from Any Camera

## 메타데이터
- categories: Equi-Rectangular Projection 통합 표현, Pitch-aware Image-to-ERP 변환, FoV Alignment, Zero-Shot Metric Depth Estimation
- domain: [[3D 인지]]
- source: Guo, Yuliang, Garg, Sparsh, Miangoleh, S. Mahdi H., Huang, Xinyu, Ren, Liu. "Depth Any Camera: Zero-Shot Metric Depth Estimation from Any Camera." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Guo_Depth_Any_Camera_Zero-Shot_Metric_Depth_Estimation_from_Any_Camera_CVPR_2025_paper.html
- year: 2025
- authors: Guo et al.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)

## 1. 핵심 요약
- 최근 depth foundation model들은 강한 zero-shot 일반화 성능을 보이지만, fisheye나 360도 카메라처럼 field of view(FoV)가 큰 카메라에서는 정확한 metric depth 추정이 여전히 어렵다.
- 이 논문은 Depth Any Camera(DAC)를 제안한다. perspective 이미지만으로 학습된 모델을 다양한 FoV를 가진 카메라에도 효과적으로 대응하도록 확장하는 zero-shot metric depth 추정 프레임워크다.
- DAC는 Equi-Rectangular Projection(ERP)을 통합 이미지 표현으로 사용하며, 핵심 구성요소로 pitch-aware Image-to-ERP 변환, FoV alignment, multi-resolution data augmentation을 포함한다.
- DAC는 perspective 이미지만으로 학습되었음에도 fisheye·360도 카메라에 별도 학습 데이터 없이 원활하게 일반화되며, 여러 fisheye·360도 데이터셋에서 기존 metric depth foundation model 대비 δ1 accuracy를 최대 50%까지 향상시켰다.

## 2. 문서 목적
- 해결하려는 문제: perspective 카메라 기준으로 학습된 depth foundation model이 fisheye·360도처럼 FoV가 크게 다른 카메라에 적용될 때 metric depth 정확도가 크게 떨어지는 문제.
- 기술적 목표: 이미 확보된 대규모 perspective 3D 데이터를 그대로 활용하면서, 카메라 종류에 관계없이 재사용 가능한 zero-shot metric depth 추정 프레임워크를 만드는 것.
- 다루는 범위: ERP 기반 통합 표현 설계, pitch-aware Image-to-ERP 변환, FoV alignment, multi-resolution training 기법, indoor(ScanNet++, Matterport3D 등)·outdoor(KITTI-360 등) fisheye·360도 데이터셋에서의 평가.

## 3. 핵심 개념 상세

### Equi-Rectangular Projection(ERP) 통합 표현
- 원문 표현: "DAC employs Equi-Rectangular Projection (ERP) as a unified image representation, enabling consistent processing of images with diverse FoVs."
- 정의: perspective, fisheye, 360도 등 서로 다른 FoV의 카메라 영상을 하나의 구형 투영 기반 표현 공간으로 통일하는 방식.
- 역할: 카메라 종류마다 별도 모델을 두지 않고 동일한 depth 모델이 서로 다른 FoV의 입력을 일관되게 처리할 수 있게 한다.

### Pitch-aware Image-to-ERP 변환
- 원문 표현: "A key innovation is the introduction of an efficient Pitch-aware Image-to-ERP conversion based on grid sampling and Gnomonic Geometry, enabling seamless ERP-space data augmentations. Specifically, pitch-aware ERP conversion with pitch-angle augmentation projects perspective images into high-distortion regions of the ERP space, effectively simulating observations unique to large-FoV cameras."
- 정의: grid sampling과 gnomonic geometry를 기반으로 perspective 이미지를 다양한 pitch 각도에서 ERP 공간으로 투영하는 변환 기법.
- 역할: perspective 이미지만 가지고도 fisheye·360도 카메라에서 나타나는 고왜곡 영역의 관측 패턴을 학습 데이터에 시뮬레이션해, 실제 large FoV 촬영 데이터 없이 일반화를 가능하게 한다.

### FoV Alignment
- 원문 표현: "a FoV alignment operation to support effective training across a wide range of FoVs"
- 정의: 서로 다른 FoV 범위를 가진 학습 샘플들을 정합해 학습에 사용하는 절차.
- 역할: 좁은 FoV부터 매우 넓은 FoV까지 하나의 모델이 일관되게 학습되도록 지원한다.

### Multi-Resolution Data Augmentation
- 원문 표현: "multi-resolution data augmentation to address resolution disparities between training and testing"
- 정의: 학습에 사용되는 ERP patch를 원본 해상도 외에 추가로 낮은 해상도(원문 기준 약 0.7, 0.4배)로 리사이즈해 함께 학습하는 기법.
- 역할: attention 기반 모듈이 학습 시 사용한 해상도와 실제 테스트 해상도가 다를 때 성능이 저하되는 문제를 완화한다.

## 4. 구조 및 흐름
1. perspective 이미지를 pitch-aware Image-to-ERP 변환으로 ERP 공간에 투영하며, 다양한 pitch 각도로 augmentation을 적용해 고왜곡 영역 관측을 시뮬레이션한다.
2. FoV alignment 단계에서 서로 다른 FoV 범위의 ERP patch를 정합해 학습 배치를 구성한다.
3. multi-resolution training 단계에서 각 ERP patch를 여러 해상도(원본 및 축소본)로 함께 학습해 학습-테스트 해상도 불일치를 줄인다.
4. 학습된 모델은 perspective 이미지만으로 학습되었음에도 fisheye·360도 카메라 입력에 대해 별도 미세조정 없이 zero-shot metric depth를 추정한다.
5. indoor(ScanNet++, Matterport3D 등)와 outdoor(KITTI-360 등) 조건의 fisheye·360도 데이터셋에서 δ1 accuracy 등으로 성능을 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| DAC는 perspective 이미지만으로 학습해도 별도 학습 데이터 없이 fisheye·360도 카메라에 일반화된다 | "DAC is trained exclusively on perspective images but generalizes seamlessly to fisheye and 360-degree cameras without the need for specialized training data" |
| DAC는 기존 metric depth foundation model 대비 large FoV 조건에서 크게 향상된 성능을 보인다 | "DAC achieves state-of-the-art zero-shot metric depth estimation, improving δ1 accuracy by up to 50% on multiple fisheye and 360-degree datasets compared to prior metric depth foundation models" |
| network 기반 spherical 변환 방식은 large FoV에서 한계가 있으며, DAC의 geometry 기반 학습 파이프라인이 더 효과적이다 | "while UniDepth ... utilizes a network-based spherical conversion, it struggles with large FoV cameras, exposing the limitations of deep learning in extrapolated domains ... In contrast, DAC's success underscores the effectiveness of our geometry-based training pipeline." |

## 6. 한계 및 부족한 점
- outdoor 환경에서는 같은 network 구성 기준으로 iDisc 대비 향상 폭이 marginal하다는 점을 저자들이 직접 인정한다: "it achieves only marginal improvements over iDisc under the same network configuration, with less pronounced gains compared to indoor settings." 저자들은 이를 outdoor 학습 데이터의 카메라 pitch variance가 제한적이어서 고왜곡 영역 시뮬레이션 효과가 줄어들기 때문으로 설명한다.
- outdoor LiDAR 기반 평가 데이터는 왜곡이 적은 영역에 점이 집중되어 있어("LiDAR points are concentrated in less distorted areas"), 대형 FoV 영역에서의 성능 차이를 평가에 온전히 반영하기 어렵다는 한계가 있다.
- 확인한 범위(ar5iv 전문, CVF abstract) 내에서는 실시간성·연산 비용에 대한 구체적 분석이나 향후 연구 방향에 대한 별도의 명시적 절은 확인되지 않음.

## 7. 원문 기반 핵심 문장
> "While recent depth foundation models exhibit strong zero-shot generalization, achieving accurate metric depth across diverse camera types—particularly those with large fields of view (FoV) such as fisheye and 360-degree cameras—remains a significant challenge."
