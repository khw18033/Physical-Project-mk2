# VGGT: Visual Geometry Grounded Transformer

## 메타데이터
- categories: Feed-Forward 3D Reconstruction, Alternating-Attention, 통합 멀티태스크 3D 예측, Camera Head와 DPT Head
- domain: [[3D 인지]]
- source: Wang, Jianyuan, Chen, Minghao, Karaev, Nikita, Vedaldi, Andrea, Rupprecht, Christian, Novotny, David. "VGGT: Visual Geometry Grounded Transformer." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Wang_VGGT_Visual_Geometry_Grounded_Transformer_CVPR_2025_paper.html
- year: 2025
- authors: Wang, Jianyuan, Chen, Minghao, Karaev, Nikita, Vedaldi, Andrea, Rupprecht, Christian, Novotny, David
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), CVPR 2025 Best Paper Award

## 1. 핵심 요약
- VGGT는 하나, 여러 장, 또는 수백 장의 뷰로부터 카메라 파라미터, point map, depth map, 3D point track을 포함한 장면의 핵심 3D 속성 전체를 직접 추론하는 feed-forward 신경망이다.
- 기존 3D 컴퓨터 비전 모델들이 단일 task에 특화되어 있던 것과 달리, VGGT는 하나의 네트워크로 여러 3D task를 동시에 처리한다.
- 1초 이내에 재구성을 수행할 만큼 단순하고 효율적이며, visual geometry 최적화 기반 후처리를 요구하는 대안 방법들보다도 더 우수한 성능을 보인다.
- 카메라 파라미터 추정, multi-view depth 추정, dense point cloud 재구성, 3D point tracking 등 다수의 3D task에서 state-of-the-art 결과를 달성한다.
- pretrained VGGT를 feature backbone으로 사용하면 non-rigid point tracking, feed-forward novel view synthesis 같은 downstream task의 성능도 크게 향상된다.

## 2. 문서 목적
- 해결하려는 문제: DUSt3R, MASt3R, VGGSfM 같은 기존 학습 기반 3D 재구성 방법들이 여전히 비용이 큰 반복적 post-optimization(global alignment, bundle adjustment)을 필요로 하며, 각 3D task마다 특화된 네트워크 설계가 필요했던 문제.
- 기술적 목표: 특수 목적 아키텍처 설계 없이도, 표준적인 대규모 Transformer 기반 접근이 카메라 파라미터·depth map·point map·point track을 하나의 forward pass로 동시에 예측할 수 있음을 보이는 것.
- 다루는 범위: alternating-attention 기반 Transformer 아키텍처 설계, camera head·DPT 기반 dense head·tracking head 구성, multi-task 학습, 카메라 파라미터 추정·multi-view depth·dense point cloud·point tracking 벤치마크 평가, downstream task로의 feature 활용.

## 3. 핵심 개념 상세

### Feed-Forward 3D Reconstruction
- 원문 표현: "It is also simple and efficient, reconstructing images in under one second, and still outperforming alternatives that require post-processing with visual geometry optimization techniques." / "In contrast, VGGT achieves superior performance while only operating in a feed-forward manner, requiring just 0.2 seconds on the same hardware."
- 정의: 입력 뷰들로부터 3D 속성을 반복적 최적화 없이 단일 forward pass로 직접 예측하는 재구성 방식.
- 역할: DUSt3R·MASt3R의 global alignment나 VGGSfM의 bundle adjustment처럼 10초 이상이 걸리는 후처리 최적화를 제거해, 빠른 3D 재구성이 필요한 응용에서 지연을 크게 낮춘다.

### Alternating-Attention(AA)
- 원문 표현: "Alternating-Attention. We slightly adjust the standard transformer design by introducing Alternating-Attention (AA), making the transformer focus within each frame and globally in an alternate fashion. Specifically, frame-wise self-attention attends to the tokens within each frame separately, an[d global self-attention attends across all frames]."
- 정의: 프레임 내부의 토큰끼리만 attention을 수행하는 frame-wise self-attention과, 모든 프레임의 토큰에 걸쳐 attention을 수행하는 global self-attention을 번갈아 적용하는 Transformer 설계.
- 역할: 프레임별 지역 정보와 여러 뷰 간 전역 정보를 모두 반영해, 임의 개수의 입력 뷰에 대해서도 확장 가능한 단일 backbone으로 카메라·depth·point map·track을 함께 예측할 수 있게 한다.

### 통합 멀티태스크 3D 예측
- 원문 표현: "We present VGGT, a feed-forward neural network that directly infers all key 3D attributes of a scene, including camera parameters, point maps, depth maps, and 3D point tracks, from one, a few, or hundreds of its views."
- 정의: 카메라 파라미터, depth map, point map, 3D point track이라는 서로 다른 3D task의 출력을 하나의 네트워크가 공유된 표현으로부터 동시에 예측하는 구조.
- 역할: task별로 별도 모델을 두지 않고 하나의 backbone과 여러 개의 task-specific head만으로 다양한 3D 속성을 얻을 수 있게 해, 단일 task 특화 모델 대비 아키텍처 복잡도를 줄인다.

### Camera Head와 DPT 기반 Dense Head
- 원문 표현: "A camera head makes the final prediction for camera extrinsics and intrinsics, and a DPT head for any dense output." / "The output image tokens are used to predict the dense outputs, i.e., the depth maps, point maps, and tracking features."
- 정의: camera token으로부터 카메라 extrinsics·intrinsics를 예측하는 camera head와, 이미지 토큰으로부터 depth map·point map·tracking feature 같은 dense한 출력을 예측하는 DPT 기반 head로 구성된 예측 구조.
- 역할: 카메라 파라미터라는 저차원(sparse) 출력과 depth·point map 같은 고차원(dense) 출력을 각각에 적합한 head로 분리해 예측함으로써 멀티태스크 학습을 안정화한다.

### Point Tracking Head
- 원문 표현: "we apply a visibility loss (binary cross-entropy) to estimate whether a point is visible in a given frame" (CoTracker2 architecture를 사용한 tracking head 관련 서술 문맥)
- 정의: CoTracker2 아키텍처를 기반으로, dense tracking feature와 query 이미지의 query point를 입력받아 다른 프레임에서의 대응 위치와 가시성(visibility)을 함께 예측하는 head.
- 역할: 별도의 tracking 전용 모델 없이도 VGGT backbone의 feature만으로 3D point track과 occlusion 여부를 예측할 수 있게 한다.

## 4. 구조 및 흐름
1. 하나에서 수백 장까지의 입력 이미지를 patch embedding으로 토큰화하고, camera token과 register token을 함께 구성한다.
2. Alternating-Attention Transformer backbone이 frame-wise self-attention과 global self-attention을 번갈아 적용해 프레임 내·프레임 간 정보를 모두 처리한다.
3. camera head가 camera token으로부터 각 프레임의 카메라 extrinsics·intrinsics를 예측한다.
4. DPT 기반 head가 이미지 토큰으로부터 depth map, point map, tracking feature 등 dense한 출력을 예측한다.
5. tracking head(CoTracker2 기반)가 query point와 tracking feature를 이용해 다른 프레임에서의 대응 위치와 visibility를 예측한다.
6. 전체 예측은 반복적 post-optimization 없이 단일 forward pass로 완료되며, pretrained VGGT의 feature는 non-rigid tracking·novel view synthesis 등 downstream task의 backbone으로도 재사용될 수 있다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| VGGT는 post-optimization 없이도 이를 사용하는 방법들을 능가한다 | "It is also simple and efficient, reconstructing images in under one second, and still outperforming alternatives that require post-processing with visual geometry optimization techniques." |
| VGGT는 DUSt3R·MASt3R 대비 훨씬 짧은 시간에 우수한 성능을 낸다 | "although DUSt3R and MASt3R conduct expensive optimization (global alignment—around 10 seconds per scene), our method still outperforms them significantly in a simple feed-forward regime at only 0.2 seconds per reconstruction." |
| VGGT는 카메라 파라미터 추정에서도 기존 feature matching 기반 방법을 능가한다 | camera pose 관련 매칭 벤치마크에서 VGGT(Ours)가 AUC@5 33.9 / AUC@10 55.2 / AUC@20 73.4로, Roma(31.8/53.4/70.9)·DKM(29.4/50.7/68.3) 등 기존 방법을 상회 |
| pretrained VGGT feature는 downstream task 성능도 향상시킨다 | "We also show that using pretrained VGGT as a feature backbone significantly enhances downstream tasks, such as non-rigid point tracking and feed-forward novel view synthesis." |

## 6. 한계 및 부족한 점
- 저자들은 다음과 같은 한계를 직접 명시한다: "While our method exhibits strong generalization to diverse in-the-wild scenes, several limitations remain. First, the current model does not support fisheye or panoramic images."
- 극단적인 입력 회전(extreme input rotations) 조건에서 재구성 성능이 떨어진다: "reconstruction performance drops under conditions involving extreme input rotations."
- 경미한 non-rigid motion은 처리 가능하지만, 큰 폭의 non-rigid deformation이 있는 장면에서는 실패한다: "although our model handles scenes with minor non-rigid motions, it fails in scenarios involving substantial non-rigid deformation."
- feed-forward 방식이 대부분의 대안을 능가하지만, post-optimization을 추가로 적용하면 여전히 성능이 더 개선될 여지가 있다고 저자들은 언급한다("there is still room for improvement since post-optimization sti[ll helps]").

## 7. 원문 기반 핵심 문장
> "We present VGGT, a feed-forward neural network that directly infers all key 3D attributes of a scene, including camera parameters, point maps, depth maps, and 3D point tracks, from one, a few, or hundreds of its views. This approach is a step forward in 3D computer vision, where models have typically been constrained to and specialized for single tasks."
