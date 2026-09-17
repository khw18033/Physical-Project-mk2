# AnyCalib: On-Manifold Learning for Model-Agnostic Single-View Camera Calibration

## 메타데이터
- categories: 단일 영상 카메라 캘리브레이션, 구면 접평면 On-Manifold 회귀, 폐형해 기반 내부파라미터 복원, 모델-비종속 캘리브레이션
- domain: [[카메라 보정]], [[3D 인지]]
- source: Tirado-Garín, Javier, Civera, Javier. "AnyCalib: On-Manifold Learning for Model-Agnostic Single-View Camera Calibration." IEEE/CVF International Conference on Computer Vision (ICCV), 2025.
- url: https://arxiv.org/abs/2503.12701
- year: 2025
- authors: Javier Tirado-Garín, Javier Civera (University of Zaragoza, I3A, Robotics Computer Vision and Artificial Intelligence Group, Spain)
- venue: IEEE/CVF International Conference on Computer Vision (ICCV)

## 1. 핵심 요약
- 단일 in-the-wild 영상에서 카메라 내부파라미터를 추정하는 기존 방법들은 특정 카메라 모델(핀홀 등)에 종속되거나 중력 방향 같은 외부 단서를 요구하는데, AnyCalib는 영상 자체의 원근·왜곡 단서만으로 모델에 구애받지 않는 캘리브레이션이 가능함을 보인다.
- 핵심 아이디어는 캘리브레이션을 픽셀별 광선(ray) 회귀 문제로 재정의하는 것이다. 네트워크는 구면 S²의 접평면(tangent plane)에 정의된 2차원 좌표인 "FoV field" θ∈ℝ²를 픽셀마다 예측하고, 로그맵/지수맵으로 이를 다시 구면상의 광선(ray)과 왕복 변환한다.
- 이 중간 표현(광선장)으로부터 pinhole, Brown-Conrady, Kannala-Brandt를 포함한 다양한 카메라 모델의 내부파라미터를 처음으로 폐형해(closed-form, linear least squares)로 복원할 수 있음을 보이고, 이후 5회의 Gauss-Newton 반복으로 비선형 기하량을 정련한다.
- crop·stretch 등 편집된 영상에도 적용 가능하며, 훨씬 적은 데이터로 학습했음에도 3D foundation model을 포함한 대안 방법들을 실험적으로 능가한다.

## 2. 문서 목적
- 해결하려는 문제: 단일 영상만으로 카메라 내부파라미터를 추정하는 기존 딥러닝 방법들이 특정 카메라 모델(주로 핀홀)에 고정되어 있거나 중력 방향 등 부가 단서를 필요로 해 일반성이 떨어지는 문제.
- 기술적 목표: 카메라 모델에 비종속적인(model-agnostic) 중간 표현을 학습해, 하나의 네트워크 출력으로부터 서로 다른 렌즈·투영 모델의 내부파라미터를 폐형해로 복원할 수 있는 프레임워크를 설계하는 것.
- 다루는 범위: 구면 접평면 기반 FoV field 표현과 학습 목표 설계, 다양한 카메라 모델별 내부파라미터의 선형/비선형 복원 절차, crop·stretch 편집 영상에 대한 처리, LaMAR·MegaDepth·TartanAir·Stanford2D3D·ScanNet++ 등 다중 데이터셋 평가와 3D foundation model 대비 비교.

## 3. 핵심 개념 상세

### On-Manifold FoV Field (구면 접평면 표현)
- 원문 표현(요지): "FoV fields correspond to elements in the tangent space T_z₁S² at the optical axis z₁=[0,0,1]ᵀ∈S²"이며, 이 접평면은 {v∈ℝ³ | z₁ᵀv=0}으로 정의된다. 구면과 접평면 사이의 변환은 로그맵(logarithm map, Eq. 2)과 지수맵(exponential map, Eq. 6)으로 이루어진다.
- 정의: 각 픽셀에 대응하는 광선 방향(단위구 S² 위의 점)을, 광축 z₁을 기준점으로 하는 접평면 위의 2차원 벡터 θ∈ℝ²로 표현한 것. 이 θ가 곧 픽셀별 각도 범위(angular extent)를 나타내는 "FoV field"이다.
- 역할: 광선 자체(3차원, 단위 노름 제약 있음)를 직접 회귀하는 대신 제약 없는 2차원 벡터를 예측하게 함으로써 네트워크 출력을 최소·비구속(minimal, unconstrained) 표현으로 만들고, 구면 매니폴드 위에서의 학습(on-manifold learning)을 접평면상의 표준 회귀 문제로 전환한다.

### 픽셀별 광선(ray) 회귀와 폐형해 내부파라미터 복원
- 원문 표현(요지): θ는 "bijective to the rays of each pixel"이며, 초점거리 등 일부 파라미터(a, c)를 먼저 추정하면 "Eqs. 8 and 9 become linear with respect to the remaining intrinsics of a wide range of commonly used camera models."
- 정의: 네트워크가 예측한 FoV field를 지수맵으로 광선장(ray field)으로 복원한 뒤, 이 광선들과 각 카메라 모델의 투영식을 연립해 선형최소제곱(linear least squares)으로 내부파라미터 대부분을 폐형해로 구하고, 남은 비선형 기하량은 5회의 Gauss-Newton 반복으로 정련한다.
- 역할: 네트워크는 카메라 모델을 알 필요 없이 오직 픽셀-광선 대응만 학습하고, 실제 모델별 파라미터화(핀홀, 왜곡 계수 개수 등)는 후처리 폐형해 단계에서 분리해 처리함으로써 하나의 모델로 다수의 카메라 모델을 지원한다.

### 지원 카메라 모델 목록
- 원문/저장소 근거: 논문은 "a wide range of commonly used camera models, including but not limited to: pinhole, Brown-Conrady and Kannala-Brandt"라고 명시하며, 공개 저장소(GitHub)는 실제 구현·평가 대상으로 다음을 열거한다: Pinhole(및 Simple Pinhole), Radial/Brown-Conrady(및 Simple Radial, k∈[1,4] 왜곡 계수), Kannala-Brandt(및 Simple KB), Unified Camera Model(UCM, 및 Simple UCM), Enhanced UCM(EUCM, 및 Simple EUCM), Division model(및 Simple Division, k∈[1,4]).
- 검증 결과: 동료가 제시한 "pinhole, Brown-Conrady, Kannala-Brandt, UCM/EUCM, division model" 목록은 저장소 기준으로 정확히 일치한다(각 모델의 단일 초점거리 "Simple" 변형까지 포함해 총 12개 파라미터화). 논문 본문은 이 중 pinhole·Brown-Conrady·Kannala-Brandt 세 가지만 대표 예시로 명시하고 "including but not limited to"로 나머지(UCM/EUCM/division 등)를 포괄한다.

## 4. 구조 및 흐름
1. 입력 영상을 백본 네트워크에 통과시켜 픽셀별 FoV field θ∈ℝ²(구면 S²의 접평면 좌표)를 회귀한다.
2. 지수맵(Eq. 6)을 이용해 θ를 다시 구면상의 단위 광선(ray) 방향으로 변환해 픽셀-광선 대응(광선장)을 얻는다.
3. 일부 핵심 파라미터(a, c 등)를 먼저 추정한 뒤, 광선장과 각 카메라 모델의 투영 방정식을 연립해 나머지 내부파라미터를 선형최소제곱으로 폐형해 복원한다.
4. 비선형 기하량이 남는 경우 5회의 Gauss-Newton 반복으로 정련한다.
5. crop·stretch로 편집된 영상에도 동일한 광선장 표현이 적용 가능함을 활용해 원본이 아닌 편집 영상에서도 캘리브레이션을 수행한다.
6. LaMAR, MegaDepth, TartanAir, Stanford2D3D, ScanNet++ 등 다중 데이터셋과 다양한 카메라 모델 조합에서 3D foundation model 등 대안 방법과 비교 평가한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 픽셀별 광선 회귀라는 단일 중간 표현으로 다양한 카메라 모델의 내부파라미터를 처음으로 폐형해 복원할 수 있다 | 접평면 FoV field → 지수맵으로 광선장 복원 → 각 카메라 모델 투영식과 연립한 선형최소제곱으로 pinhole·Brown-Conrady·Kannala-Brandt를 포함한 다수 모델의 파라미터를 도출(논문 Eq. 8, 9 및 이어지는 Gauss-Newton 정련) |
| crop·stretch 등으로 편집된 영상에도 동일 방법이 적용된다 | 논문이 명시적으로 "Our approach also applies to edited -- cropped and stretched -- images"라고 기술 |
| 적은 학습 데이터로도 3D foundation model 등 기존 대안을 능가한다 | 초록에서 "AnyCalib consistently outperforms alternative methods, including 3D foundation models, despite being trained on orders of magnitude less data"라고 명시, LaMAR/MegaDepth/TartanAir/Stanford2D3D/ScanNet++ 등 다중 데이터셋 평가로 뒷받침 |

## 6. 한계 및 부족한 점
- 이번 확인은 arXiv 초록·본문 발췌(HTML v2)와 GitHub 저장소(README, LICENSE)를 통해 이루어졌으며, PDF 전문을 페이지 단위로 전부 통독하지는 않았다. 수식 번호(Eq. 2, 6, 8, 9)와 인용 문구는 확인된 발췌 범위 내에서 재구성한 것이다.
- 논문 초록은 지원 카메라 모델을 "pinhole, Brown-Conrady and Kannala-Brandt"만 명시적 예시로 들고 "including but not limited to"로 표현하므로, UCM/EUCM/division model까지의 전체 목록은 초록이 아니라 공개 저장소(README)의 실제 구현 목록을 근거로 확정했다.
- 저장소 라이선스 파일 원문은 Apache License 2.0 표준 조문이며 저작권자(copyright holder) 이름이 파일 내에 별도로 명시되어 있지 않아, "Apache 2.0"이라는 라이선스 종류 자체는 확인했으나 저작권 귀속 문구까지는 확인하지 못했다.
- 학습·평가 데이터로 사용된 확장 OpenPano 데이터셋 생성 절차나 벤치마크 8개 데이터셋 각각의 정량적 수치는 이번 확인 범위에서 세부까지 재현하지 않았다.

## 7. 원문 기반 핵심 문장
> "We frame the calibration process as the regression of the rays corresponding to each pixel. We show, for the first time, that this intermediate representation allows for a closed-form recovery of the intrinsics for a wide range of camera models, including but not limited to: pinhole, Brown-Conrady and Kannala-Brandt."

> "FoV fields correspond to elements in the tangent space T_z₁S² at the optical axis z₁=[0,0,1]ᵀ∈S²."

> "Our approach also applies to edited -- cropped and stretched -- images. Experimentally, we demonstrate that AnyCalib consistently outperforms alternative methods, including 3D foundation models, despite being trained on orders of magnitude less data."
