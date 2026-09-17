# SLAM3R: Real-Time Dense Scene Reconstruction from Monocular RGB Videos

## 메타데이터
- categories: Image-to-Points 네트워크, Local-to-World 네트워크, Sliding Window 기반 재구성, Retrieval 기반 재등록
- domain: [[3D 인지]]
- source: Liu, Yuzheng, Dong, Siyan, Wang, Shuzhe, Yin, Yingda, Yang, Yanchao, Fan, Qingnan, Chen, Baoquan. "SLAM3R: Real-Time Dense Scene Reconstruction from Monocular RGB Videos." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Liu_SLAM3R_Real-Time_Dense_Scene_Reconstruction_from_Monocular_RGB_Videos_CVPR_2025_paper.html
- year: 2025
- authors: Liu et al.
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)

## 1. 핵심 요약
- SLAM3R은 monocular RGB video만으로 local 3D reconstruction과 global coordinate registration을 feed-forward neural network로 통합하는 end-to-end 시스템이다.
- 전통적인 pose 최적화 기반 방법과 달리 카메라 파라미터를 explicit하게 풀지 않고, 각 window의 RGB 이미지로부터 직접 3D pointmap을 회귀(regress)한다.
- Image-to-Points(I2P) network와 Local-to-World(L2W) network의 두 네트워크 구조로 이루어져 있으며, sliding window 방식으로 비디오를 겹치는 클립으로 나눠 처리한다.
- 여러 데이터셋에 걸친 실험에서 state-of-the-art 수준의 reconstruction 정확도와 완전성(completeness)을 유지하면서 20+ FPS의 실시간 성능을 달성했으며, CVPR 2025 Highlight, China3DV 2025 Top1 논문으로 선정되었다.

## 2. 문서 목적
- 해결하려는 문제: 기존 dense 3D reconstruction 방법 다수가 카메라 파라미터(pose)를 explicit하게 추정·최적화하는 절차에 의존해 처리 속도가 느리고 실시간 스트리밍 환경에 적합하지 않은 문제.
- 기술적 목표: 카메라 파라미터를 별도로 풀지 않고 RGB 이미지에서 직접 3D pointmap을 회귀하는 feed-forward network로, monocular RGB video에서 실시간(20+ FPS)으로 dense하고 전역적으로 일관된(globally consistent) 3D reconstruction을 얻는 것.
- 다루는 범위: I2P/L2W 두 네트워크의 설계, sliding window 기반 클립 처리, retrieval 기반 global registration(암묵적 재정위), 여러 데이터셋에 걸친 정확도·완전성·속도 평가.

## 3. 핵심 개념 상세
### Image-to-Points (I2P) 네트워크
- 원문 표현: "multi-view cross-attention to combine information from different supporting frames"
- 정의: DUSt3R의 2-view 아키텍처를 다중 뷰로 확장해, 하나의 sliding window 안에서 keyframe과 supporting frame들의 정보를 multi-view cross-attention으로 결합하여 통일된 local 좌표계에서 3D pointmap을 회귀하는 네트워크.
- 역할: 각 sliding window 클립에 대해 카메라 intrinsic/extrinsic을 explicit하게 풀지 않고도 local dense reconstruction을 생성한다.

### Local-to-World (L2W) 네트워크
- 원문 표현: "SLAM3R directly regresses 3D pointmaps from RGB images in each window and progressively aligns and deforms these local pointmaps to create a globally consistent scene reconstruction - all without explicitly solving any camera parameters."
- 정의: 각 window에서 I2P가 만든 local pointmap들을 점진적으로(progressively) 정렬·변형(align and deform)하여 단일 global 좌표계로 등록(registration)하는 네트워크.
- 역할: 전통적인 pose graph 최적화나 bundle adjustment 단계를 대체해, 카메라 파라미터 없이도 전체 비디오 시퀀스에 걸친 전역 일관성(global consistency)을 확보한다.

### Sliding Window 기반 클립 처리
- 원문 표현: "the system first converts it into overlapping clips using a sliding window mechanism"
- 정의: 입력 비디오를 기본 길이 11프레임의 겹치는(overlapping) 클립으로 나누고, 각 window의 중간 프레임을 local 좌표계를 정의하는 keyframe으로, 나머지를 supporting view로 사용하는 처리 방식.
- 역할: 비디오 전체를 한 번에 요구하지 않고 클립 단위로 스트리밍 처리할 수 있게 해, 매 스텝의 연산량을 일정하게 유지하면서 실시간 동작을 가능하게 한다.

### Retrieval 기반 재등록(암묵적 재정위)
- 원문 표현: "lightweight retrieval module" / "implicit re-localization"
- 정의: 이미 등록된 keyframe들을 담은 경계가 있는(bounded) reservoir를 유지하면서, 새 keyframe을 등록하기 전에 lightweight retrieval module로 가장 관련 있는 참조 프레임을 선택하는 절차.
- 역할: 별도의 explicit loop closure 알고리즘 없이도 이전에 관측한 영역으로 돌아왔을 때 재정위(re-localization)를 암묵적으로 제공해, 누적 오차를 줄이는 데 기여한다.

## 4. 구조 및 흐름
1. 입력 RGB 비디오를 기본 11프레임 길이의 겹치는 sliding window 클립으로 분할하고, 각 클립의 keyframe을 지정한다.
2. I2P network가 multi-view cross-attention으로 keyframe과 supporting frame들의 정보를 결합해, 카메라 파라미터 없이 해당 클립의 local 3D pointmap을 회귀한다.
3. L2W의 retrieval module이 bounded keyframe reservoir에서 새 keyframe과 가장 관련 있는 기등록 참조 프레임을 선택한다.
4. L2W network가 새 local pointmap을 선택된 참조 프레임 기준으로 점진적으로 정렬·변형해 global 좌표계에 등록한다(암묵적 재정위 포함).
5. 비디오가 스트리밍되는 동안 이 과정이 반복되며 global dense point cloud가 누적되고, 전체 파이프라인은 20+ FPS로 동작한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 카메라 파라미터를 explicit하게 풀지 않고도 전역 일관된 reconstruction이 가능하다 | I2P·L2W feed-forward network가 pointmap을 직접 회귀·정렬하며, 여러 데이터셋에서 state-of-the-art 정확도·완전성을 달성 |
| monocular RGB video에서 실시간 dense reconstruction이 가능하다 | 실험에서 20+ FPS의 real-time 성능을 명시 |
| retrieval 기반 모듈이 explicit loop closure 없이 재정위를 제공한다 | bounded keyframe reservoir + lightweight retrieval module이 "implicit re-localization" 제공 |
| 대규모 실내 등 다양한 데이터셋에서 SOTA 수준을 달성한다 | 여러 데이터셋에 걸쳐 state-of-the-art reconstruction accuracy/completeness 확인, CVPR 2025 Highlight·China3DV 2025 Top1 선정 |

## 6. 한계 및 부족한 점
- 저자들이 직접 명시: 대규모 야외(large-scale outdoor) 장면에서는 global bundle adjustment가 없기 때문에 누적 drift(accumulated drift) 문제에 여전히 직면한다고 밝힌다.
- retrieval 기반 재정위는 bounded reservoir 안에서 동작하므로, reservoir 범위를 벗어나는 매우 큰 규모의 장면에 대한 재정위 보장 범위는 확인되지 않는다.
- 확인한 범위(CVPR 논문 페이지, arXiv html 버전, GitHub 저장소) 내에서 대규모 outdoor drift 외의 추가 실패 사례나 future work에 대한 별도의 명시적 논의는 확인되지 않는다.

## 7. 원문 기반 핵심 문장
> "SLAM3R provides an end-to-end solution by seamlessly integrating local 3D reconstruction and global coordinate registration through feed-forward neural networks. ... SLAM3R directly regresses 3D pointmaps from RGB images in each window and progressively aligns and deforms these local pointmaps to create a globally consistent scene reconstruction - all without explicitly solving any camera parameters. Experiments across datasets consistently show that SLAM3R achieves state-of-the-art reconstruction accuracy and completeness while maintaining real-time performance at 20+ FPS."
