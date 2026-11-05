# 카메라 특성 자동 결정 — 기존 연구 조사와 채택 판단

상태: 조사 및 채택 결정 기록 (2026-11-03).
요구사항: **AI-E-02** (카메라 보정 lifecycle). 관련 AI-C-02(좌표계 경계), AI-C-08(미디어 경로),
AI-C-05(선택 기능 격리), AI-S-08(사전정보와 관측의 분리), AI-C-19(권한 경계).
구현 위치: `edge/auto_calibration.py`, `edge/calibration.py`, `edge/calibration_profile.py`,
`edge/anycalib_style_recovery.py`, `edge/calibration_extrinsics.py`,
`edge/calibration_monitor.py`, `edge/calibration_transfer.py`, `edge/equirect_views.py`.
각 모듈 docstring 첫 줄의 `implements:` 가 정본이다.

AI-E-02 는 방법을 고르라고 하지 않고 **고정하지 말라**고 한다:

> "보정 방식은 사전 보정, 보정판 기반, 영상 시퀀스 self-calibration, 학습 기반 추정 등 특정
> 방법을 프레임워크의 필수 방식으로 고정하지 않아야 한다."

그래서 이 문서가 하는 일은 "무엇이 최고인가" 를 정하는 것이 아니다. **우리 현장에서 실제로
입력이 들어오는 방법이 무엇인가**를 가려내고, 들어오지 않는 방법은 왜 들어오지 않는지를
적어 두는 것이다. 거절 사유가 남아 있지 않으면 다음 사람이 같은 조사를 다시 한다.

---

## 1. 판정 기준 — 벤치마크가 아니라 우리 현장

각 기법은 자기 논문의 벤치마크 점수로 평가하지 않는다. 아래 여섯 줄로 평가한다.

| 축 | 우리 현실 |
|---|---|
| 카메라 | 이종 소수 대수. `sensor.camera.imx708`(협각), `imx708_wide`(광각), `sensor.camera.360`(Insta360 Pro 2), `go1_front`/`go1_stereo`(로봇 온보드), `ep`. UAV(x500)는 카메라 미탑재 |
| 보정판 | **대부분의 현장에 없다.** 체커보드를 들고 갈 수 있는 현장은 데모 현장뿐이다 |
| 영상 접근 | 프레임은 미디어 경로로 **엣지**까지 온다. 말단에서 무거운 연산을 돌리지 않는다(절대 준수 원칙 #13, AI-E-02) |
| 연산 | 엣지는 CPU + onnxruntime 기준. GPU 를 전제로 둘 수 없다 |
| 장애 | 모델·입력이 없으면 **그 방법만** 비가용이고 시스템은 계속 돈다(AI-C-05) |
| 산출 | 검증 통과한 것만 프로파일이 된다. 정확도는 **측정한 것만** 선언한다(미측정은 0 이 아니다) |

마지막 줄이 조사 결과를 가장 많이 걸러냈다. 논문들은 대체로 "추정값" 을 내고 **그 추정값이
얼마나 틀렸는지** 는 내지 않는다. 우리는 추정값을 `perception/spatial_evidence.py` 로 넣어야
하고, 거기서 `accuracy_m` 이 None 인 근거는 가중에서 보류된다 — 정확도를 내지 못하는 기법은
사람이 줄자로 잰 값을 **이길 수 없는 등급**으로만 쓸 수 있다는 뜻이다. 그것이 틀린 설계가
아니라 정확히 맞는 설계다(AI-S-08, AI-L-03).

---

## 2. 이미 있는 것 — `edge/anycalib_style_recovery.py` 가 덮는 범위

새로 무엇을 더할지 말하기 전에 이미 있는 것부터 정확히 적는다.

`RayFieldIntrinsicsRecovery` 가 하는 일: 호출자가 준 **픽셀↔광선 방향 대응**에서 pinhole
내부 파라미터 (fx, fy, cx, cy) 를 선형 최소제곱으로 닫힌 형태로 푼다. `u = fx·(rx/rz) + cx`,
`v = fy·(ry/rz) + cy` 가 (fx, cx) 와 (fy, cy) 에 대해 각각 선형이므로 2개 이상의 대응이면
풀린다. 잔차 RMS 를 내고 임계 초과면 `stable=False` 로 표시한다.

하지 **않는** 일 — 모듈 docstring 이 이미 명시하고 있고, 이 조사도 같은 결론이다:

- AnyCalib 의 실제 기여인 **학습된 FoV-field 회귀기**는 들어 있지 않다. 신경망도, 가중치도,
  학습 데이터도 없다.
- 그래서 **영상 내용에서 광선 방향을 스스로 만들지 않는다.** 광선은 항상 호출자 입력이다.
- 왜곡 계수를 추정하지 않는다. pinhole 만 본다.
- 외부 파라미터(카메라가 어디 있고 어디를 보는가)는 아예 다루지 않는다.

**남긴 구멍이 이 작업의 범위다**: (1) 광선을 줄 상류가 없는 현장에서 내부 파라미터를 어디서
얻는가, (2) 외부 파라미터를 누가 추정하는가, (3) 기존 보정이 더 이상 현실을 설명하지 않는
것을 누가 알아채는가.

---

## 3. 고전적 방법

### 3.1 Zhang 평면 타겟법 (`cv2.calibrateCamera`)

- 출처: Z. Zhang, "A Flexible New Technique for Camera Calibration", PAMI 2000
  ([Microsoft Research](https://www.microsoft.com/en-us/research/?p=145334)); 선행 ICCV 1999
  ["Flexible Camera Calibration by Viewing a Plane from Unknown Orientations"](https://www.microsoft.com/en-us/research/?p=320642).
- 가정: 평면 패턴을 **최소 2개 이상의 다른 방향**에서 본다. 패턴이나 카메라가 움직여도 되고
  움직임을 알 필요는 없다. 닫힌 형태 초기해 + 최대우도 비선형 정제, 방사 왜곡 포함.
- 현장 요구: **보정판.** 실무에서는 2장이 아니라 10여 장을 다양한 자세로 찍는다.
- 판정: **채택(보정판이 있는 현장 한정).** 이것이 이미 `edge/calibration.py::CameraCalibrator`
  이고, 정확도·재투영 오차가 가장 신뢰할 만한 유일한 경로다. 다만 **대부분의 현장에 보정판이
  없으므로 이것만 두면 대부분의 카메라가 영원히 미보정으로 남는다.** 그래서 필수 방법으로
  둘 수 없다 — AI-E-02 가 금지하는 것이 정확히 이 고정이다.

### 3.2 Scaramuzza 전방위 툴박스 (OCamCalib)

- 출처: Scaramuzza, Martinelli, Siegwart, ICVS 2006
  ([PDF](https://www.cvlibs.net/projects/autonomous_vision_survey/literature/Scaramuzza2006IROS.pdf));
  Scaramuzza ETH 박사논문 2007 ([record](https://www.research-collection.ethz.ch/handle/20.500.11850/14333?show=full));
  순수 Python 이식 [py-OCamCalib](https://github.com/jakarto3d/py-OCamCalib).
- 가정: 단일 시점 중심 투영이면 센서 모델을 특정하지 않는다. 결상 함수를 **Taylor 급수**로
  두고 계수를 데이터에서 푼다. dioptric(어안)과 catadioptric(거울) 모두 커버.
- 현장 요구: 보정판 + **사람이 코너를 클릭**하는 단계가 원 툴박스에 있다.
- 판정: **미채택.** 보정판 의존은 3.1 과 같고, 거기에 사람 개입이 더 붙는다. 어안 모델이
  필요한 자리(§6)는 보정판 없이 풀어야 하는 자리라서 이 툴박스가 닿지 않는다. 원 구현이
  MATLAB 이라는 점도 폐쇄망 조달에 불리하다(AI-C-16).

### 3.3 왜곡 모델 — Brown–Conrady vs Kannala–Brandt

모델 선택은 "어느 쪽이 좋은가" 가 아니라 **화각이 정한다.**

- Brown–Conrady: 반경 다항식 + 접선항. OpenCV 의 기본(비어안) 왜곡 모델이고
  ([OpenCV 포럼 논의](https://answers.opencv.org/question/236675/confusion-about-opencvs-distortion-model-wrt-brown-conrady-model/))
  협각~중간 화각에서 맞는다.
- Kannala–Brandt: `cv2.fisheye` 가 구현하는 모델(k1~k4, 홀수 차수 다항식). 광각·어안에 맞다.
  다만 **z = 0 에 특이점**이 있어 180°에 가까운 어안에는 부적합하다 — 이 지적의 출처는
  Double Sphere 논문 ([arXiv 1807.08957](https://arxiv.org/pdf/1807.08957)) 이다.
- 어안 왜곡 보정 기법 전반의 조망은 [arXiv 2401.00442](https://arxiv.org/pdf/2401.00442),
  차량 서라운드뷰 어안 관점은 [arXiv 2205.13281](https://arxiv.org/pdf/2205.13281).

우리 함대에 대입하면: 공식 Camera Module 3 는 표준 66° / 광각 102° 수평 화각(대각 75° / 120°,
초점거리 4.74mm / 2.75mm — 출처는 유통사 제원표
[Elektor](https://www.elektor.com/products/raspberry-pi-camera-module-3-wide) 이고 Raspberry Pi
[공식 제품 페이지](https://raspberrypi.com/products/camera-module-3)는 대각값만 적는다).
즉 **imx708 은 Brown–Conrady 로 충분하고 imx708_wide 는 경계선, 360 은 둘 다 틀리다.**
프레임워크가 왜곡 모델 하나를 고정하면 함대의 일부가 항상 잘못 보정된다 — 이것이 모델을
provider 뒤에 두는 이유이고, 왜곡 계수를 **프로파일에 적되 추정 안 한 항목은 비워 두는** 이유다.

---

## 4. 단일 영상 학습 기반

이 계열은 우리에게 매력적이다. 보정판이 필요 없고, 입력이 **엣지에 이미 도착한 프레임 한 장**
뿐이기 때문이다(AI-C-08 의 미디어 경로가 그대로 입력이 된다). 문제는 전부 조달과 런타임이다.

### 4.1 DeepCalib (Bogdan et al., CVMP 2018)

- 광각 영상 한 장에서 초점거리와 **단일 왜곡 계수**를 CNN 으로 회귀. 인터넷의 전방위 영상
  수백만 장으로 학습. 보정판·모션·장면 구조 전제가 없다.
  ([GeoCalib repo 가 baseline 으로 포함](https://github.com/cvg/geocalib))
- 판정: **미채택.** 왜곡 파라미터가 하나뿐이라 §3.3 의 모델 선택 문제를 해결하지 못하고,
  이후 기법들이 같은 입력으로 더 잘한다. 새 가중치를 조달할 가치가 가장 낮다.

### 4.2 Lopez et al., "Deep Single Image Camera Calibration With Radial Distortion" (CVPR 2019)

- tilt, roll, 초점거리, 방사 왜곡을 **한 장에서 동시에** 추정. 학습하기 쉬운 왜곡
  파라미터화와 점 투영 손실이 기여.
  ([CVF](https://openaccess.thecvf.com/content_CVPR_2019/html/Lopez_Deep_Single_Image_Camera_Calibration_With_Radial_Distortion_CVPR_2019_paper.html),
  [Mapillary](https://research.mapillary.com/publication/cvpr19d))
- 판정: **미채택(설계 참고).** 4.5~4.6 의 후속이 같은 입력에서 더 넓은 카메라 모델을 다룬다.

### 4.3 CTRL-C (Lee et al., ICCV 2021)

- 영상 + **선분 집합**을 입력으로 받는 transformer. 선분을 수직/수평 수렴선으로 분류하는
  보조 과제가 파라미터 회귀를 돕는다. Google Street View / SUN360 에서 기존 단일영상 기법 상회.
  ([CVF](https://openaccess.thecvf.com/content/ICCV2021/html/Lee_CTRL-C_Camera_Calibration_TRansformer_With_Line-Classification_ICCV_2021_paper.html),
  [arXiv 2109.02259](https://arxiv.org/abs/2109.02259v1), [code](https://github.com/jwlee-vcl/CTRL-C))
- 판정: **미채택.** 선분 수렴 구조에 의존하므로 §5.1 의 소실점 계열과 **같은 실패 모드**를
  물려받는다. 하천 호안·야외 개방 공간에는 수렴선이 없다. 모델까지 조달하면서 같은 한계를
  떠안을 이유가 없다.

### 4.4 Perspective Fields (Jin et al., CVPR 2023)

- **픽셀별 up-vector + latitude** 라는 표현을 제안. PerspectiveNet 이 그 field 를 예측하고
  ParamNet 이 roll/pitch/FoV/주점을 회귀한다. 360° 파노라마 crop 으로 학습해 GT 확보가 쉽다.
  **crop·warp 에 강건**하도록 설계됐다 — crop 이 주점을 옮겨서 "주점은 중앙" 가정을 깨는
  문제를 정면으로 다룬 것이 이 논문이다.
  ([CVF](https://openaccess.thecvf.com/content/CVPR2023/html/Jin_Perspective_Fields_for_Single_Image_Camera_Calibration_CVPR_2023_paper.html),
  [arXiv 2212.03239](https://arxiv.org/pdf/2212.03239))
- 판정: **미채택이되 가장 중요한 설계 입력.** 이 논문이 지적한 crop 민감성이 우리
  `ApplicabilityScope.zoom_token` 의 근거다 — crop/zoom 상태를 프로파일의 적용 조건으로
  적지 않으면 같은 카메라의 다른 crop 에 틀린 주점이 적용된다.

### 4.5 GeoCalib (Veicht, Sarlin, Lindenberger, Pollefeys, ECCV 2024)

- 네트워크가 신뢰도 포함 perspective field 를 예측하고 **Levenberg–Marquardt** 가 카메라
  파라미터를 적합한다. 최적화된 출력을 감독해 end-to-end 학습. 내부 최적화가
  **불확실도를 내서 실패 사례를 표시**한다. OpenPano 데이터셋으로 완전 재현 가능.
  ([ECVA](https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/5636_ECCV_2024_paper.php),
  [arXiv 2409.06704](https://arxiv.org/abs/2409.06704v2), [code](https://github.com/cvg/geocalib))
- 판정: **미채택(1순위 후보로 보류).** 거절 이유는 품질이 아니라 조달이다 — PyTorch 가중치를
  내부 저장소로 조달해야 하고(AI-C-16) 공개 트리에 들어가지 않으며, 이 작업 범위에서 그
  조달·CPU 벤치마크·검증 데이터를 세울 수 없다. **채택 가치가 가장 높은 미구현 후보**이고,
  그 이유는 성능이 아니라 **불확실도를 함께 낸다**는 점이다 — §1 의 마지막 줄이 요구하는
  "측정된 정확도" 를 이 계열에서 유일하게 직접 준다. provider 경계는 이 기법이 들어올 자리를
  비워 두고 설계한다.

### 4.6 AnyCalib (Tirado-Garín & Civera, ICCV 2025)

- 보정을 **픽셀별 광선 예측**으로 두고(on-manifold), 그 중간 표현에서 pinhole / Brown–Conrady /
  Kannala–Brandt 등 여러 모델의 내부 파라미터를 **닫힌 형태로** 복원한다. 중력 같은 외재
  단서를 요구하지 않고, crop·stretch 된 영상도 다룬다. 3D foundation model 대비 수십~수백 배
  적은 데이터로 학습해 더 좋다고 보고.
  ([CVF](https://openaccess.thecvf.com//content/ICCV2025/html/Tirado-Garin_AnyCalib_On-Manifold_Learning_for_Model-Agnostic_Single-View_Camera_Calibration_ICCV_2025_paper.html),
  [arXiv 2503.12701](https://arxiv.org/abs/2503.12701v2), [code](https://github.com/javrtg/AnyCalib))
- 저장소 확인 사항(README 직접 확인): 요구사항은 "Python (≥3.10) 과 PyTorch" 뿐이고 **ONNX
  내보내기는 언급이 없다.** 최소 예제는 `torch.device("cuda")` 를 하드코딩하고 CPU 추론 시간
  언급이 없다. 가중치·코드 Apache 2.0. `cam_id` 로 `pinhole`, `radial:k`, `kb:k`, `ucm`,
  `eucm`, `division:k` 를 고른다 — **모델 무관성이 실제로 API 로 드러나 있다.**
- 판정: **부분 채택 — 하류 닫힌 형태 단계만 이미 구현됨**(`edge/anycalib_style_recovery.py`).
  학습된 FoV-field 는 미채택이고 이유는 4.5 와 같다(가중치 조달 + CPU 런타임 미검증 + GPU
  전제 예제). 이 분리가 정직한 상태다: **대수는 우리 것이고 네트워크는 아직 우리 것이 아니다.**

### 4.7 CalibAnyView (Li et al., 2026)

- 단일 시점을 넘어 **희소 다시점**을 cross-view attention 으로 묶어 모델 무관 perspective field
  를 예측하고, 다시점 최적화로 **공유 내부 파라미터 + 시점별 중력**을 낸다. 보정판·조밀 시점
  커버리지·성공한 복원을 전제하지 않는다. ([arXiv 2605.14615](https://arxiv.org/abs/2605.14615))
- 판정: **미채택(추적 대상).** 우리 `rot8` 회전 스캔이 정확히 "한 카메라의 희소 다시점" 이라
  입력 형태가 맞는다. 다만 2026-05 공개이고 검증된 가중치·ONNX 경로·CPU 측정이 없어 지금
  운영 선택 후보가 될 수 없다(AI-B-09: 검증 전에는 정상 선택 후보로 보지 않는다).

---

## 5. 타겟 없는 자기보정

### 5.1 소실점 / Manhattan world

- 직교 소실점 **한 쌍**이 초점거리와 주점에 대한 제약 하나를 주고, 세 쌍이면 왜곡·skew 가
  없다는 가정 하에 내부 파라미터가 풀린다 ([arXiv 2103.11438](https://arxiv.org/pdf/2103.11438)).
  주점을 알면 한 쌍으로 충분하다. 고전 근거는 Caprile & Torre (IJCV 1990).
- Wildenauer & Hanbury (CVPR 2012) 는 **네 개의 선분**에서 직교 소실점 3개와 초점거리를 푸는
  최소해 + RANSAC ([record](https://mlanthology.org/cvpr/2012/wildenauer2012cvpr-robust)).
- Antunes et al. (CVPR 2017) 는 소실점과 왜곡(왜곡 중심·세기)·초점거리·회전을 함께 풀되,
  **선 3개만으로는 초점거리와 방사 왜곡 사이의 모호성이 남는다**고 명시
  ([PDF](https://home.deec.uc.pt/~jpbar/Publication_Source/cvpr2017.pdf)).
- 중력 사전정보를 쓰는 최신 소실점 추정은 [arXiv 2308.10694](https://arxiv.org/pdf/2308.10694) —
  여기서도 주점을 영상 중앙으로 **두고** 초점거리만 푼다.
- 판정: **미채택.** 실내 시설 감시에는 맞지만 하천·호안·야외 개방 공간에는 직교 수렴 구조가
  없다. 도메인에 따라 되고 안 되는 방법을 기본 경로로 두면 "도메인명으로 분기" 와 같은 결과가
  된다(절대 준수 원칙 #3). 선택형 provider 로 나중에 추가할 자리는 열어 둔다.

### 5.2 Plumb-line / 직선 기반 방사 왜곡

- 기원은 Brown (1971). 핵심 제약은 **직선성** — pinhole 모델에서 장면의 직선은 영상에서도
  직선이어야 하므로, 그 어긋남이 왜곡을 준다.
- Devernay & Faugeras, "Straight lines have to be straight" (MVA 2001) 가 표준 비선형 최적화
  정식화. Strand & Hayman (BMVC 2005) 은 왜곡된 직선의 궤적이 원호라는 점을 써 원 적합으로
  재정식화 ([PDF](https://bmva-archive.org.uk/bmvc/2005/papers/138/paper.pdf)).
  리뷰: Lerma García & Cabrelles López, *The Photogrammetric Record* 2007
  ([record](https://riunet.upv.es/entities/publication/4c1a0eb9-e4bb-4021-a970-dae1ad2f3bb3/full)).
- 알려진 약점: **선을 찾아야 한다.** 직선을 검출하기 어렵거나 다른 강한 gradient 와 구분하기
  어려운 장면에서 무너진다.
- 판정: **미채택.** 5.1 과 같은 실패 모드이고(구조 의존), 왜곡만 주고 초점거리를 주지 않는다.
  스포츠 경기장 선처럼 **사전에 직선임을 아는** 구조가 있는 현장이 생기면 그때 provider 로 더한다.

### 5.3 순수 회전 호모그래피 / 무한 호모그래피 (Hartley 계열)

- 순수 회전에서는 뷰 사이 호모그래피를 점 대응만으로 직접 계산할 수 있고, `H = K R K⁻¹` 이
  **절대원뿔의 쌍대 영상(DIAC) `K Kᵗ`** 에 대한 제약을 준다. 정규화한 `K⁻¹ H K` 가 회전행렬이
  어야 한다는 조건이 그 제약이다. de Agapito, Hayman, Reid 가 내부 파라미터가 변하는 경우로
  일반화. 개요는 [Camera auto-calibration (Wikipedia)](https://en.wikipedia.org/wiki/Camera_auto-calibration),
  정리는 Hartley & Zisserman *Multiple View Geometry* 의 autocalibration 장
  ([Cambridge Core](https://www.cambridge.org/core/books/abs/multiple-view-geometry-in-computer-vision/autocalibration/351F3B228E8F5AF85A5ACC1372F5E3B6)),
  반정의계획법 전역 최적해는 [Simplified Active Calibration, arXiv 1806.11468](https://arxiv.org/pdf/1806.11468) 가 인용.
- **문헌이 미리 경고한 것**: 이 계열은 "순수 회전이라는 단순한 특수 경우에서조차 잡음에 매우
  민감" 하고, "퇴화와 준모호성의 수가 많다" — 그리고 그 해법으로 **알려진 회전각을 비선형 정제에
  넣거나 병진을 포함**하라고 권한다.
- 판정: **채택(단, 검증을 통과해야만).** 이유는 입력 때문이다 — 이 방법이 요구하는 것은
  **엣지에 이미 와 있는 프레임 두 장과 그 사이 특징 대응**뿐이다. 보정판도, 조달할 가중치도,
  GPU 도 필요 없다. 우리 함대에서 입력이 실제로 존재하는 비(非)보정판 방법은 현재 이것뿐이다.
  그리고 문헌이 경고한 민감성은 **검증기로 잡는 것**이 맞는 처리다 — 아래가 그 실측이다.

### 5.4 실측 — 순수 회전 가정이 우리 로봇에서 깨지는 지점

실제 자산 `local/physical_demo_assets/20260910-134818_rot8/` (464x400, 8방향 회전 스캔)로 측정.
구현은 ORB 대응 + RANSAC 호모그래피 + DIAC 직교성 잔차 1차원 최소화.

| 조건 | 결과 |
|---|---|
| **실제 픽셀 + 알려진 warp** (실제 프레임을 `K R K⁻¹` 로 변형, f = 320/480/700, 12°/20°) | f 복원 오차 **±6.2% 이내**, ORB inlier 재투영 RMS **0.75~0.94 px**, 직교성 잔차 ≤ 0.008 |
| **실제 rot8 연속 쌍 7개** (로봇이 실제로 회전) | f 가 수평화각 **102~126°** 또는 **7°** 로 나옴(둘 다 imx708 계열에 불가능), 직교성 잔차 **0.035~0.67**(위의 4~80배), RANSAC inlier 20~92개 |

해석: **추정기는 맞고 가정이 깨졌다.** 로봇은 카메라 광학 중심이 아니라 **자기 몸통 축**을
중심으로 돌기 때문에 병진이 섞이고, 그 순간 `H = K R K⁻¹` 가 성립하지 않는다. §5.3 이 인용한
"퇴화와 준모호성" 경고가 실측으로 재현된 것이다.

그래서 이 방법은 **고정 카메라의 pan 스캔**(광학 중심 근처를 축으로 도는 경우)에서 쓰고,
이동 로봇의 몸통 회전에서는 검증기가 거부해 **이전 정상 프로파일이 유지되어야** 한다.
직교성 잔차와 화각 타당성 두 검사가 그 거부를 만든다 — 숨겨진 실패가 아니라 기록된 거부다.

### 5.4 DroidCalib / "Deep Geometry-Aware Camera Self-Calibration from Video" (Hagemann, Knorr, Stiller, ICCV 2023)

- 미분 가능한 **자기보정 번들조정 층**이 고전적 Gauss–Newton 스텝으로 내부 파라미터를 정제한다.
  재학습 없이 다른 카메라 모델에 적응하고, DROID-SLAM 안의 frontend·backend 양쪽에서 돈다.
  큰 렌즈 왜곡을 포함해 미지 환경·미지 모델로 일반화한다고 보고.
  ([CVF PDF](https://openaccess.thecvf.com/content/ICCV2023/papers/Hagemann_Deep_Geometry-Aware_Camera_Self-Calibration_from_Video_ICCV_2023_paper.pdf),
  [code](https://github.com/boschresearch/DroidCalib))
- 저장소 확인 사항: 왜곡 없는 영상에는 pinhole, 근사 방사 왜곡에는 통합 카메라 모델(`mei`),
  초점거리만 푸는 모델도 제공. 라이선스 **AGPL-3.0**.
- 판정: **미채택.** 세 가지 이유를 순서대로 든다. (1) **라이선스** — AGPL-3.0 은 이 저장소의
  공개 범위 정책과 충돌한다(판단은 조달 쪽 몫이지만 기본 의존성으로 들일 수는 없다).
  (2) DROID-SLAM 전체(딥 광류 + 번들조정)가 따라 들어오고 **GPU 전제**다 — 엣지 CPU 예산에
  들어가지 않는다. (3) Stuttgart 의 석사논문 하나가 어안 모델을 넣은 DROID-SLAM 번들조정에서
  "구현한 온라인 보정이 정확도를 개선하지 못했다" 고 보고했다
  ([개요](https://www.ifp.uni-stuttgart.de/lehre/masterarbeiten/640-Mueller/)) — 논문 결과를
  반박하는 증거는 아니지만 **설정 의존성이 크다**는 신호다. 비디오 시퀀스에서 번들조정으로
  내부 파라미터를 푸는 **발상**은 유효하므로, 설계 참고(등급 D)로 남긴다.

---

## 6. 광각·어안·360 — pinhole 모델이 틀리는 자리

`sensor.camera.360` (Insta360 Pro 2)은 다른 축의 문제다. **스티칭된 등장방형(equirectangular)
파노라마에는 자기 pinhole 내부 파라미터가 없다.** 조사한 세 가지 대응이 전부 "파노라마에
pinhole 을 씌우지 말라" 고 말한다.

1. **스티칭 전 렌즈별로 보정한다.** Samsung Gear 360 연구는 기기 내부가 만든 투영의 계측
   정확도가 낮았고, 두 렌즈의 내부 파라미터와 상대 자세를 보정해 **등장방형을 다시 생성**해야
   기하적으로 정확해졌다고 보고 ([Politecnico di Milano record](https://re.public.polimi.it/handle/11311/1060942)).
2. **구면 모델을 쓴다.** 픽셀 좌표를 각도로 먼저 환산하는 구면 정식화(Fangi & Nardinocchi 2013
   계열). 2026 의 lidar-카메라 보정 작업은 pinhole 투영 대신 등장방형 투영을 쓰는 쪽을 제안
   ([arXiv 2603.15767](https://arxiv.org/pdf/2603.15767)).
3. **원근 뷰를 뽑아 그걸 보정한다.** 등장방형 프레임마다 겹치는 원근 투영 여러 장을 추출해
   표준 SfM 으로 내부 파라미터를 푸는 경로 ([arXiv 2609.23425](https://arxiv.org/pdf/2609.23425)).

판정: **360 카메라는 이번 범위에서 보정 대상에 넣지 않는다.** 360 유닛은 현재 "제어 없음,
라이브 스트림 수신만" 으로 선언돼 있고, 렌즈별 원본에 접근하지 못하면 1번도 2번도 할 수 없다.
중요한 것은 **그 사실이 조용히 사라지지 않게 하는 것**이다: 360 소스에 pinhole 프로파일을
적용하는 일이 없어야 하고, 그러려면 `ApplicabilityScope` 가 카메라를 식별해야 한다. 3번(원근
뷰 추출 후 보정)이 나중의 확장 경로이고, provider 하나를 더하는 것으로 끝나야 한다.

---

## 7. 특성이 바뀐 것을 알아채기 — 이것이 절반이다

AI-E-02 는 보정을 **언제** 다시 하는지도 요구사항으로 적는다:

> "새로운 카메라가 등록되거나 해상도·crop·zoom·장착 상태 등 입력 조건이 바뀌거나 기존 보정의
> 유효성이 낮아진 경우"

### 7.1 해상도·crop·zoom — 변환 가능한 변화와 재추정이 필요한 변화

조사 결과에서 가장 실무적으로 유용한 구분이 이것이다:

- **순수 resize**: fx, fy, cx, cy 를 같은 배율로 **환산하면 그대로 쓸 수 있다.** 왜곡 계수는
  해상도 무관 ([OpenCV 포럼](https://answers.opencv.org/question/236918/does-the-resolution-of-an-image-affect-the-distortion-co-efficients)).
  MRPT 는 `scaleToResolution()` 로 이 환산을 API 로 제공
  ([MRPT docs](https://docs.mrpt.org/reference/2.3.0/class_mrpt_img_TCamera.html)).
- **crop**: 주점이 crop offset 만큼 **옮겨지고** 초점거리는 그대로다.
- **그러나 센서 readout 모드·binning·windowing 이 바뀐 경우는 단순 배율이 아니다.** 이때는
  재보정이 필요하다.

따라서 "입력 조건이 바뀌었다" 는 한 가지 사건이 아니라 **두 가지**다 — 기하적으로 환산 가능한
변화와 재추정을 요구하는 변화. 우리 `ApplicabilityScope` 는 `image_size` 와 `zoom_token` 을
따로 들고 있어서 이 구분을 표현할 자리가 있다. 지금 구현은 **보수적으로** 둘 다 부적합 판정과
재보정 신호로 보낸다 — 환산이 되는 경우를 환산해 주는 것은 다음 단계이고, 틀린 환산보다
"적용 불가" 가 안전하다.

### 7.2 보정이 현실을 더 이상 설명하지 않는 것 — 감시(monitoring) vs 추적(tracking)

카메라 단독 내부 파라미터 drift 를 다룬 문헌은 찾지 못했다. 가장 가까운 성숙한 문헌은
**lidar-카메라 외부 파라미터 온라인 감시**이고, 거기서 가져올 구분이 하나 있다.

- Moravec & Šára, OCAMO / LTO (IEEE T-RO, 2023 계열): **monitoring 은 기준 보정의 유효성
  검사**이고 **tracking 은 느린 drift 를 따라가는 것**이라고 둘을 분리한다. 그리고 OCAMO 는
  작은 decalibration 을 더 잘 잡고, LTO 는 **급격한** decalibration 에 더 빨리 반응한다고
  보고 ([CTU record](https://dspace.cvut.cz/handle/10467/113999),
  [Moravec 학위논문](https://dspace.cuni.cz/handle/20.500.11956/116608)). 핵심 신호는
  **재투영 오차**이고(lidar 에지 대 영상 에지 우도), 급격한 decalibration 을 수 초 내에
  잡는다고 보고.
- Peng et al. (*Chinese Journal of Mechanical Engineering*, 2024): 각 센서가 관측한 회전
  운동으로 프레임마다 miscalibration 을 검사
  ([article](https://cjme.springeropen.com/articles/10.1186/s10033-024-01035-3)).
- Rachman et al. (ICIP 2022): 차량 카메라 딥 자기보정을 **체커보드 재투영 오차로 검증**하고,
  타겟 없는 온라인 기법이 타겟 기반 대비 정확도 격차 때문에 채택이 더디다고 지적
  ([record](https://cris.fau.de/publications/332688635)).
- 번들조정 기반 온라인 재보정을 Kalman 필터로 평활하고 수렴 시 재보정하는 특허
  ([US 12065162](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12065162)).

**우리 신호 설계에 그대로 반영한 것**:

| 신호 | 문헌 근거 | 비고 |
|---|---|---|
| 앵커 재투영 오차 drift (N 윈도 **지속**) | 재투영 오차 기반 monitoring 전체. Moravec 의 "작은 decalibration" 축 | 한 프레임의 튐으로 재보정을 걸지 않는다 |
| 장착 교란 후 **급변** | Moravec 의 LTO 축(급격한 decalibration 에 빠른 반응) | 지속 판정과 **다른 신호**로 둔다. 하나로 합치면 둘 다 늦는다 |
| 입력 조건(해상도/zoom/장착) 변경 | §7.1 | 품질 저하가 아니라 **적용 범위 밖** — 다른 사유다 |
| 알려진 크기 물체가 틀리게 측정됨 | 교통 카메라 계열: Dubská, Sochor, Herout (BMVC 2014) 가 3D 박스 치수를 알려진 차량 치수 분포에 적합해 장면 스케일을 얻음 ([paper](https://bmva-archive.org.uk/bmvc/2014/papers/paper013/index.html)) | 역방향으로 쓰는 것이다: 스케일을 알 때 치수 오차가 보정 오류를 가리킨다 |
| 보정 기한 경과 | — | 운영 정책이고 문헌 근거가 필요한 항목이 아니다 |
| 프로파일 없음 | AI-E-02 의 fallback | 재보정 필요의 가장 단순한 사유 |
| **두 카메라가 한 객체 위치를 다르게 말함** | **문헌에서 찾지 못했다** | 아래 참조 |

마지막 줄은 정직하게 적어 둔다: **카메라 간 교차 일관성을 보정 유효성 신호로 쓰는 선행 연구를
찾지 못했다.** 교통 카메라 쪽 특허는 cross-ratio 불변량과 보정 패턴에 의존하고 교차 검증을
말하지 않는다. 우리가 이 신호를 두는 이유는 문헌이 아니라 구조다 — 우리는 이미
`spatial_evidence.py` 에서 **여러 출처의 불일치와 leave-one-out 영향도**를 계산하므로, 그
불일치가 보정 의심으로 올라올 통로를 공짜로 얻는다. 근거가 문헌이 아니라 우리 구조라는 점을
적어 두는 것이 나중에 이 신호의 임계값을 조정할 사람에게 필요한 정보다.

---

## 8. 선언과 관측이 모순되면 평균하지 않는다

`config/status_ui.fms.example.json` 은 센서 태그로 `sensor.camera.imx708`(수평 66°),
`imx708_wide`(102°), `360` 을 선언하고, `profiles/domains.example.json` 은 고정 카메라의
`pose`(yaw_deg, height_m)와 때로 `calibration.profile_version` 을 선언한다.

선언된 협각 카메라에서 추정값이 어안급 화각을 내면 그것은 **평균해 없앨 잡음이 아니라 모순**이다.
가능한 원인이 전부 운영자가 알아야 하는 것들이다: 태그가 틀렸거나, 렌즈가 교체됐거나, 추정이
퇴화했거나(§5.4 가 바로 그 경우다). AI-S-08 이 사전정보와 관측을 분리하라고 한 이유가 이것이고,

> "실제 관측과 충돌하는 사전정보만으로 객체·위험 상태를 확정해서는 안 된다"

는 반대 방향으로도 성립한다 — 관측 하나로 선언을 덮지도 않는다. 그래서 선언된 센서 종류와
추정 화각의 모순은 **검증 실패 사유로 기록하고 프로파일을 승격하지 않는** 방식으로 다룬다.
어느 쪽이 맞는지는 AI 가 판정하지 않는다(AI-C-19).

---

## 9. 채택 결론

provider 경계 뒤에 **지금 입력이 실제로 존재하는** 방법만 넣는다.

1. **보정판 기반 내부 파라미터** (Zhang / `cv2.calibrateCamera`) — 입력: 보정판 스펙 + 검출된
   코너. 데모 현장에서만 입력이 들어오지만, **정확도가 가장 믿을 만한 유일한 경로**라서
   기준선으로 반드시 있어야 한다.
2. **영상 시퀀스 자기보정(순수 회전 호모그래피)** — 입력: 미디어 경로로 온 프레임 2장 이상.
   보정판 없는 현장에서 입력이 들어오는 유일한 비학습 내부 파라미터 경로다. §5.4 의 실측대로
   가정이 깨지는 리그에서는 **검증기가 거부**하고 이전 프로파일이 유지된다.
3. **광선 대응 기반 내부 파라미터**(기존 `anycalib_style_recovery`) — 입력: 픽셀↔광선 대응.
   상류가 광선을 주는 배치(깊이 provider, 나중의 GeoCalib/AnyCalib 네트워크)에서 바로 쓰인다.
   이 자리가 비어 있지 않다는 것이 §4.5 의 후보가 **핵심 코드 수정 없이** 들어올 수 있다는 증거다.
4. **앵커 방위 기반 외부 파라미터** — 입력: 알려진 구역 로컬 좌표의 앵커 3개 이상과 그 영상
   방위. 내부 파라미터 기법 어느 것도 "카메라가 어디 있고 어디를 보는가" 를 주지 않으므로,
   §1 이 요구한 **측정된 정확도**를 낼 수 있는 유일한 축이다 — Jacobian 에서 공분산을 얻는
   표준 경로(Hartley Ch.7 계열, [슬라이드](https://www.ece.mcmaster.ca/~shirani/vision/hartley_ch7.pdf))를
   쓰고, 앵커가 3개 미만이거나 퇴화 배치면 **정확도를 미측정으로 남긴다.**

   > **2026-11-04 정정.** 이 줄은 처음에 "앵커가 공선이면 퇴화" 라고 적었고, 근거로 3D 점이
   > 공선일 때의 퇴화를 들었다. **그것은 3D PnP(6-DoF)의 조건이고 우리가 푸는 문제의
   > 조건이 아니다.** 측량된 앵커의 방위로 평면 자세(x, y, yaw)를 푸는 것은 3-DoF 교회법
   > (Snellius–Pothenot)이고, 그 퇴화는 **카메라가 앵커들을 지나는 원 위에 있을 때**다 —
   > 고전 측량에서 위험원(danger circle)으로 불린다. 공선 앵커는 오히려 잘 조건화된다:
   > 세 점의 외접원이 직선으로 퇴화하고 카메라는 그 직선 위에 거의 없기 때문이다.
   >
   > 구현(`edge/calibration_extrinsics.py`)의 합성 실측이 그 서술을 반증했다 — 공선 앵커
   > 4개에서 위치 오차 **0.016 m**(퍼진 6개는 0.092 m)로 가장 좋았고, 외접원에 2% 근접한
   > 직사각 배치가 오차 0.139 m · 낸 1σ 0.423 m 로 **거부**됐다. 그래서 퇴화 판정은
   > 공선성이 아니라 **위험원 근접도**로 하고, 공선성은 진단으로만 남긴다.

거절 요약: GeoCalib·AnyCalib 네트워크·CalibAnyView 는 **가중치 조달과 CPU 런타임 미검증**으로
보류(품질 때문이 아니다). DroidCalib 은 AGPL + GPU 전제 + 설정 의존성. CTRL-C·소실점·plumb-line
은 **장면 구조 의존**이라 하천·야외에서 같은 실패 모드. Scaramuzza·DeepCalib·Lopez 는 더 나은
후속이 같은 입력을 쓴다. 360 은 렌즈별 원본에 접근하지 못해 입력이 없다.

---

## 10. 요약표

| 기법 | 가정 | 현장에 필요한 것 | 채택 | 한 줄 사유 |
|---|---|---|---|---|
| Zhang 평면 타겟 (`cv2.calibrateCamera`) | 평면 패턴, 2+ 자세 | **보정판** | 예 | 정확도가 가장 믿을 만한 유일한 기준선. 단 대부분의 현장에 보정판이 없다 |
| 순수 회전 호모그래피 (Hartley 계열) | 광학 중심 축 회전, 특징 대응 | 프레임 2장 (미디어 경로) | 예 | 보정판 없이 입력이 실제로 들어오는 유일한 비학습 경로. 가정 위반은 검증기가 거부 |
| 광선 대응 선형해 (`anycalib_style_recovery`) | 픽셀↔광선 대응이 주어짐 | 상류 광선 제공자 | 예(기존) | 대수는 우리 것. 광선을 만드는 네트워크는 아직 아니다 |
| 앵커 방위 외부 파라미터 | 앵커 3+ 의 로컬 좌표, 영상 방위 | 측량된 앵커, 위험원 밖 | 예 | 외부 파라미터를 주는 유일한 축이고 공분산으로 정확도를 **측정**한다 |
| Scaramuzza OCamCalib | 단일 시점 중심 투영, Taylor 모델 | 보정판 + 코너 클릭 | 아니오 | 보정판 의존에 사람 개입이 더 붙고 MATLAB 원본 |
| DeepCalib (CVMP 2018) | 광각 영상 1장 | 학습 가중치 | 아니오 | 왜곡 계수 1개로는 모델 선택 문제가 안 풀리고 후속이 더 낫다 |
| Lopez et al. (CVPR 2019) | 영상 1장 | 학습 가중치 | 아니오 | 후속이 같은 입력에서 더 넓은 카메라 모델을 다룬다 |
| CTRL-C (ICCV 2021) | 선분 수렴 구조 | 가중치 + 직선 많은 장면 | 아니오 | 소실점 계열과 같은 실패 모드를 가중치 조달 비용까지 내고 떠안는다 |
| Perspective Fields (CVPR 2023) | 영상 1장, crop 강건 | 학습 가중치 | 아니오(설계 입력) | crop 민감성 지적이 `zoom_token` 의 근거가 됐다 |
| GeoCalib (ECCV 2024) | 영상 1장 + LM 최적화 | PyTorch 가중치 | 보류(1순위) | **불확실도를 함께 낸다** — 조달·CPU 검증만 남았다 |
| AnyCalib 네트워크 (ICCV 2025) | 영상 1장, 모델 무관 | PyTorch 가중치, 예제가 CUDA 고정 | 보류 | 하류 닫힌 형태만 이미 구현. 네트워크는 조달·런타임 미검증 |
| CalibAnyView (2026) | 희소 다시점 1카메라 | 가중치, 검증 없음 | 아니오(추적) | 입력 형태는 우리 회전 스캔과 맞지만 검증 전에는 선택 후보가 아니다 |
| DroidCalib (ICCV 2023) | 비디오, 번들조정 | DROID-SLAM + GPU | 아니오 | AGPL-3.0 + GPU 전제 + 설정 의존성 보고 |
| 소실점 / Manhattan | 직교 수렴 구조 | 실내형 장면 | 아니오 | 하천·야외에 수렴선이 없다. 도메인별로 되고 안 되면 기본 경로가 못 된다 |
| Plumb-line / 직선 왜곡 | 장면에 직선이 있고 직선임을 안다 | 검출 가능한 직선 | 아니오 | 왜곡만 주고 초점거리를 안 주며 구조 의존은 소실점과 같다 |
| 360 등장방형 직접 보정 | 파노라마에 pinhole 내부 파라미터가 있다 | — | 아니오 | 애초에 성립하지 않는다. 렌즈별 원본이나 원근 뷰 추출이 필요하고 접근권이 없다 |

---

## 11. 확인하지 못한 것

정직하게 남긴다. 아래는 이 조사가 **확정하지 못한** 항목이고, 뒤에 오는 사람이 여기서 시작하면 된다.

- **카메라 단독 내부 파라미터 drift 를 감시하는 전용 문헌을 찾지 못했다.** §7.2 의 근거는 전부
  lidar-카메라 외부 파라미터 감시에서 가져온 것이다. 재투영 오차 기반이라는 축은 이전 가능하지만
  수치(임계값·윈도 길이)는 그대로 가져오면 안 된다.
- **카메라 간 교차 일관성을 보정 유효성 신호로 쓰는 선행 연구를 찾지 못했다**(§7.2 마지막 줄).
- Camera Module 3 의 수평 화각 66°/102° 는 유통사·언론 제원표이고 Raspberry Pi 공식 페이지는
  대각값만 적는다. 화각 타당성 검사의 경계값을 조일 때는 **실측**으로 확정해야 한다.
- GeoCalib·AnyCalib 의 **CPU 추론 시간을 측정하지 않았다.** 두 저장소 모두 CPU 수치를 적지 않고
  AnyCalib 예제는 CUDA 를 하드코딩한다. "엣지 CPU 에서 돈다/안 돈다" 는 아직 미측정이며,
  AI-B-01 의 규칙대로 **다른 구성의 측정값을 가져다 쓰지 않는다.**
- Kannala–Brandt 를 "Brown–Conrady 의 확장" 으로 기술하는 2차 자료가 있었으나 다른 자료는
  독립적인 일반 모델로 기술한다. 원 논문(Kannala & Brandt, PAMI 2006)을 직접 확인하지 못했다.
- DroidCalib 의 정확도 개선 실패 보고는 석사논문 하나이고 ICCV 결과에 대한 반박으로 확인된
  것은 아니다.
- Devernay & Faugeras (MVA 2001), Caprile & Torre (IJCV 1990), Kannala & Brandt (PAMI 2006),
  Brown (1971) 은 **인용 문헌을 통해서만** 확인했고 원문을 직접 열지 못했다.
