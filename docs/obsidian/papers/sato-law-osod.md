# A Mobile Robot Framework for Learning to Detect New Objects With Large Language Models

## 메타데이터
- categories: Open Set Object Detection, LLM 기반 미확인 객체 의미 라벨링, MobileCLIP 기반 반복 미확인 객체 재식별, 엣지 증분학습(Incremental Learning) 파이프라인
- domain: [[객체 탐지·분할]], [[엣지 실행·자원]]
- source: Sato, Matthew M., Law, Kincho H. "A Mobile Robot Framework for Learning to Detect New Objects With Large Language Models." *Journal of Computing and Information Science in Engineering*, Vol. 26, No. 6, Article 061007, 2026 (online 2026-05-20). DOI: 10.1115/1.4071863. — 확장 전 학회논문: Sato, M. M., Law, K. H. "A Mobile Robot Framework for Learning to Detect New Objects With Large Language Models." Proceedings of the ASME 2025 IDETC/CIE, Paper DETC2025-164474, Anaheim, CA, Aug 17-20, 2025. DOI: 10.1115/detc2025-164474.
- url: 학회논문 원문 PDF https://eil.stanford.edu/sites/g/files/sbiybj34491/files/media/file/osod_llm.pdf ; 저널판 https://doi.org/10.1115/1.4071863 (ASME Digital Collection, 페이월) ; 공식 코드 https://github.com/satomm1/robot_new_objects
- year: 2025 (학회) → 2026 (저널, 확장판)
- authors: Matthew M. Sato, Kincho H. Law (Stanford University, Department of Civil and Environmental Engineering, Engineering Informatics Group)
- venue: ASME Journal of Computing and Information Science in Engineering (2026, Vol. 26 No. 6, Art. 061007) — 원 학회: ASME 2025 International Design Engineering Technical Conferences & Computers and Information in Engineering Conference (IDETC/CIE2025)

## 1. 핵심 요약
- 이동형 로봇이 학습된 known object뿐 아니라 미확인(unknown) 객체까지 실시간으로 탐지하는 fast open set object detector(OSOD)를 제안한다. 핵심은 작은 YOLO 모델(YOLOv11n, 약 260만 파라미터)에 multimodal LLM(Gemini 1.5 Flash)이 생성한 pseudolabel로 unknown class를 학습시킨 것이다.
- 배포 후 미확인 객체가 탐지되면, 전통적으로 사람이 담당하던 이름·속성 부여 역할을 Gemini 1.5 Flash가 실시간 "oracle"로 대신한다. 객체명, 정지 여부(is_static), 주의 수준(caution level: low/medium/high) 3가지 의미 정보를 구조화된 출력으로 얻는다.
- 동일한 미확인 객체가 반복 관측될 때 매번 느린 LLM을 호출하지 않도록, 더 가벼운 MobileCLIP-S0 모델로 이미지 임베딩과 기존에 이름이 부여된 객체들의 텍스트 임베딩 사이 코사인 유사도를 비교해 재식별한다.
- 로봇이 미확인 객체의 이미지·레이블을 DDS(publish-subscribe) 기반으로 중앙 workstation에 축적하다가 충분한 인스턴스가 모이면(예: cone 441개 인스턴스) 원본 YOLOv11n의 마지막 5개 레이어만 미세조정하는 방식으로 재학습해 새로운 known class로 승격한다.
- 학회판(ASME IDETC/CIE 2025, DETC2025-164474)이 2026년 ASME Journal of Computing and Information Science in Engineering(Vol. 26, No. 6, Art. 061007)에 확장판으로 게재된 것을 CrossRef 메타데이터로 확인했다. 다만 저널판 본문은 ASME Digital Collection이 403(페이월)을 반환해 직접 읽지 못했으며, 저널판이 학회판과 구체적으로 어떻게 달라졌는지는 원문 확인 안 됨이다.

## 2. 문서 목적
- 해결하려는 문제: 표준 객체 탐지기는 학습 데이터셋에 없는 객체를 인식하지 못하고, 기존 open world object detection(OWOD) 연구는 대형 Faster-RCNN/transformer 백본과 사람이 큐레이션한 새 데이터셋을 전제해 자원이 제한된 엣지 로봇에 적용하기 어렵다.
- 기술적 목표: (1) 엣지에서 실시간 동작 가능한 경량 OSOD를 만들고, (2) 미확인 객체의 이름·의미를 사람 대신 multimodal LLM이 실시간으로 제공하게 하며, (3) 반복 관측되는 미확인 객체를 LLM보다 훨씬 빠른 비전-언어 모델(MobileCLIP)로 재식별하고, (4) 로봇이 스스로 수집한 데이터로 사람 개입 없이 OSOD를 증분 재학습시키는 것.
- 다루는 범위: YOLOv11n 기반 OSOD 설계와 LLM pseudolabel을 이용한 학습, 배포 후 LLM 의미 라벨링 절차, MobileCLIP 기반 반복 미확인 객체 분류 휴리스틱, DDS 기반 데이터 수집·증분학습 파이프라인, 실제 커스텀 이동 로봇(Nvidia Jetson Orin Nano 탑재)에서의 실험 검증.

## 3. 핵심 개념 상세

### Open Set Object Detection (OSOD) via YOLOv11n + LLM Pseudolabels
- 원문 표현: "To reduce latency, the YOLO (single-stage CNN-based) architecture [15] is chosen for the OSOD due to the small model size compared to other typical object detection backbones. For example, the YOLOv11n architecture has approximately 2.6 million parameters [18] and is notably smaller and faster than the ResNet-50 model, which has approximately 25 million parameters..."
- 정의: 알려진 K개 클래스(1..K)와 그 외 모든 객체를 하나의 "unknown"(class 0)으로 묶어 함께 탐지하도록 학습된 단일 단계(single-stage) CNN 탐지기. 기존 OSOD/OWOD 연구가 쓰는 Faster-RCNN의 region proposal network(낮은 분류 신뢰도의 박스를 unknown pseudolabel로 사용)와 달리, YOLO는 구조상 모든 객체에 대한 박스를 자동 생성하지 않으므로 대신 multimodal LLM(Gemini 1.5 Flash)에게 학습 이미지 전체에 대해 bounding box를 요청해 pseudolabel로 사용한다.
- 역할: 기존 ground-truth 박스와 IoU > 0.7로 겹치는 LLM 박스는 버리고 나머지는 "unknown" 정답으로 채택해, 사람이 새 데이터셋을 큐레이션하지 않고도 unknown class 학습 데이터를 확보한다. 이 pseudolabeling은 학습 전 1회만 수행되고 별도의 실시간 연산을 요구하지 않는다. 정확한 프롬프트: "Provide the bounding boxes for any and all objects in this image that an object detector may be interested in using the [ymin, xmin, ymax, xmax] format." — 이는 원문(§3.1, §4.2)과 실제 공개 코드(`tools/get_gemini_boxes.py`)의 `PROMPT` 상수가 문자 그대로 일치함을 확인했다.

### LLM 기반 실시간 의미 오라클 (Object Identification and Semantics Using LLMs)
- 원문 표현: "Our procedure for obtaining object semantics from an LLM involves three steps: 1. Draw a distinctly colored bounding box around each unknown object in an image. 2. Query the LLM for the semantics of each object, sorting the results by bounding box color. 3. Structure the output to guide the output into a machine-readable format."
- 정의: 배포된 OSOD가 미확인 객체를 탐지하면, 한 이미지 안의 미확인 객체마다 최대 7가지 색상(red, green, blue, purple, pink, orange, yellow) 중 하나로 구분되는 bounding box를 그려 이미지 1장당 단 1회의 Gemini 1.5 Flash 쿼리로 여러 객체를 동시에 질의한다. 출력은 Pydantic 구조화 스키마(`UnknownObject`: object_name, bounding_box_color, is_static, caution_level)로 강제해 기계 판독 가능하게 만든다.
- 역할: caution_level(낮음/중간/높음)은 각각 "객체는 안전함", "탐색 시 약간의 버퍼 필요", "해당 구역 회피"를 의미하도록 프롬프트에 명시적으로 정의해 LLM 출력의 일관성을 높였다. LLM은 또한 박스 안에 실제 객체가 없다고 판단하면 이를 표시할 수 있어 OSOD의 false positive를 줄이는 검증기 역할도 겸한다. 미확인 객체가 7개를 넘는 밀집 장면은 확률이 높은 상위 7개만 처리되어 일부가 라벨링되지 않을 수 있음을 저자들이 명시했다.

### MobileCLIP 기반 반복 미확인 객체 재식별
- 원문 표현: "The MobileCLIP prediction is used if the ratio from Eq. (2) is greater than 1.4, (i.e., 𝜙 > 1.4). Otherwise, the object remains classified as unknown and is forwarded to the LLM for identification."
- 정의: 이미 LLM이 이름을 부여한 객체마다 "a photo of a {object_name}" 문구로 텍스트 임베딩(v_text)을 1회만 계산해 리스트에 보관한다. 새로 탐지된 unknown 영역을 크롭해 MobileCLIP-S0(표준 CLIP 대비 약 5배 빠르고 정확도는 유사)로 이미지 임베딩(v_image)을 계산하고, 모든 저장된 텍스트 임베딩과 코사인 유사도 s_i = (v_text_i · v_image)/(‖v_text_i‖‖v_image‖)를 구한다.
- 역할: 최고 유사도 s(1)와 두 번째 유사도 s(2)의 비율 φ = s(1)/s(2)을 계산해, 경험적으로 정한 임계값 c=1.4를 넘으면 최고 유사도 객체로 즉시 분류(LLM 호출 생략)하고, 넘지 못하면 여전히 "unknown"으로 두고 Gemini에 전달한다. 이 방식은 클러스터링과 달리 known/unknown 클래스 수가 늘어도 객체당 계산 복잡도가 일정(constant)하다는 점을 저자들이 명시적 장점으로 제시했다. Jetson Orin Nano의 Ampere GPU에서 MobileCLIP 평균 실행 시간은 객체당 0.0390초로, 1초 이상 걸리는 LLM 쿼리보다 훨씬 빠르다(원문: "MobileCLIP is still substantially faster than an LLM query which often takes over one second.").

### DDS 기반 분산 데이터 수집과 증분 재학습
- 원문 표현: "we propose a decentralized communication platform based on the Data Distribution Service (DDS) protocol [20]... Once a sufficient number of images are collected for a novel class, the retraining process is initiated."
- 정의: 로봇 자체는 저장 용량이 제한적이므로 미확인 객체 이미지·레이블을 DDS publish-subscribe로 중앙 데이터 저장 클라이언트(workstation)에 오프로드한다. 한 로봇이 새 객체를 학습하면 이름·의미 정보가 다른 로봇에도 전파되어, 다른 로봇이 해당 객체를 처음 만나도 MobileCLIP 텍스트 인코딩 리스트에 이미 반영되어 있어 즉시 재식별에 활용할 수 있다.
- 역할: 재학습은 원본 OSOD 가중치에서 시작해 마지막 5개 레이어만 학습 가능(trainable) 상태로 두고 나머지는 고정한 채 100 epoch 미세조정하는 방식이며, 원본 COCO 데이터 전체 + 새로 수집한 데이터를 함께 사용해(데이터 효율성은 이 논문의 초점이 아니라고 명시) 기존 known/unknown 성능을 유지하면서 새 클래스를 추가한다.

## 4. 구조 및 흐름
1. **오프라인 학습 데이터 준비**: COCO 2017에서 사무공간에 흔한 10개 클래스(사람, 배낭, 가방, 의자, 벤치, 화분, 노트북, 마우스, 키보드, 휴대폰)만 선별(66,904 학습/7,434 검증 이미지). Gemini 1.5 Flash에 학습 이미지를 보내 모든 객체의 bounding box를 요청하고, 기존 ground truth와 IoU>0.7로 겹치는 박스는 버려 나머지를 "unknown" pseudolabel로 채택.
2. **OSOD 학습**: YOLOv11n을 known 10클래스 + unknown class로 배치 크기 32, 200 epoch 학습(손실: box regression + classification + distribution focal loss).
3. **배포 및 실시간 탐지**: 커스텀 이동 로봇(LiDAR + RGB-D, 온보드 연산은 Nvidia Jetson Orin Nano)에서 OSOD가 프레임마다 known/unknown 객체를 탐지(Ampere GPU에서 0.033초/프레임, 약 30fps).
4. **반복 객체 재식별**: 탐지된 unknown 영역마다 MobileCLIP-S0로 이미지 임베딩을 구해 기존에 이름이 부여된 객체들의 텍스트 임베딩과 비교(φ = s(1)/s(2) > 1.4면 즉시 분류).
5. **LLM 의미 오라클 호출**: MobileCLIP이 분류하지 못한(φ ≤ 1.4) unknown 객체들은 색상 구분된 bounding box로 표시되어 이미지 1장당 1회 Gemini 1.5 Flash 쿼리로 이름·정지여부·주의수준을 구조화된 형식으로 획득. 새 객체명은 MobileCLIP 텍스트 인코딩 리스트에 추가.
6. **데이터 축적 및 증분 재학습**: 미확인 객체의 이미지·레이블이 DDS를 통해 중앙 workstation 데이터베이스에 전송·축적. 예시(cone 클래스)로 두 로봇이 222개 이미지(cone 441 인스턴스)를 모으자 재학습이 트리거되어, 원본 가중치에서 마지막 5개 레이어만 100 epoch 미세조정. 갱신된 모델 가중치는 다시 DDS로 로봇들에 배포되어 이후 cone은 LLM 없이 자동 탐지된다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 파라미터 수가 훨씬 적은 YOLOv11n(약 260만) 기반 OSOD도 기존 대형 OWOD 백본(ResNet-50 기반 약 2500만 파라미터)과 견줄 만한 unknown 탐지 성능을 낸다 | COCO 10-known-class 설정에서 mAP50 48.3, mAP50-95 41.3, U-Recall 30.7(다른 OWOD들이 보고하는 U-Recall 범위 1.5–60.9와 비교 가능한 수준), 연산시간 0.033초/프레임(Ampere GPU, 약 30fps) |
| LLM 기반 pseudolabeling만으로 unknown class 학습이 유효하다 | 사람이 만든 unknown ground-truth 없이 Gemini 생성 박스만으로 학습했음에도 U-Recall 30.7 확보; 저자는 false negative(미검출)가 false positive보다 흔하다고 관찰해, LLM 박스가 모든 unknown을 완전히 커버하지 못함을 인정하면서도 방법이 "sufficient for unknown object identification"이라고 결론 |
| MobileCLIP 재식별이 LLM 호출 빈도를 줄이면서 실시간성을 확보한다 | MobileCLIP-S0 평균 실행시간 0.0390초/객체 vs. LLM 쿼리 "often takes over one second"; φ=s(1)/s(2)>1.4 휴리스틱으로 cone(φ=1.6)은 LLM 없이 분류, water bottle(φ=1.1)은 정확히 unknown으로 남겨 LLM에 전달되는 사례를 제시 |
| 마지막 5개 레이어만 미세조정하는 소규모 증분 재학습으로도 새 클래스를 기존 성능 저하 없이 추가할 수 있다 | cone 재학습 후 mAP50(전체) 50.2, mAP50-95(전체) 34.7, Cone AP50 72.0, Cone AP50-95 50.5, U-Recall 30.1 — 재학습 전 U-Recall(30.7)과 거의 동일하게 유지되어 기존 unknown 탐지력을 크게 훼손하지 않으면서 cone을 known class로 추가 |

## 6. 한계 및 부족한 점
- 학회판(ASME IDETC/CIE 2025, DETC2025-164474) 원문 PDF 10페이지 전체를 직접 읽고 위 내용을 확인했다. 저널 확장판(J. Comput. Inf. Sci. Eng. 26(6):061007, DOI 10.1115/1.4071863)은 CrossRef 메타데이터(발행일 2026-05-20)로 존재와 서지사항만 확인했을 뿐, ASME Digital Collection 초록·본문 페이지가 403(페이월)을 반환해 실제 확장 내용(추가 실험, 추가 분석 등)은 원문 확인 안 됨이다. 학회판과 저널판이 동일한 제목·저자를 쓰는 것은 확인했지만 두 버전의 차이는 검증하지 못했다.
- 공식 코드 저장소(`robot_new_objects`, main 브랜치) 자체의 README는 여전히 "This is the source code for the DETC2025-164474 paper submitted to the ASME 2025 IDETC-CIE conference"라고만 명시하며, 2026 저널판에 대한 언급은 없다.
- **코드 완성도는 부분적이다**: `robot_new_objects` 저장소에는 `create_data.sh`, `train.sh`/`train.py`, `eval.sh`/`eval.py`, `retrain.sh`/`retrain.py`, `eval_retrained.sh`/`eval_retrained.py`, `tools/get_gemini_boxes.py`(논문 3.1절의 프롬프트·Pydantic 스키마와 문자 그대로 일치함을 직접 대조 확인) 등 오프라인 학습·평가·재학습 파이프라인은 실제로 존재하고 기능적으로 완전해 보인다. 그러나 실제 로봇에서 MobileCLIP 재식별과 실시간 LLM 오라클 호출이 동작하는 배포 코드는 README가 안내하는 별도 저장소 `image_detection_with_unknowns`(ROS noetic 패키지)에 있다고 되어 있는데, GitHub API로 직접 확인한 결과 이 저장소는 LICENSE 파일과 31바이트짜리 README("# image_detection_with_unknowns"만 존재)뿐인 사실상 빈 스텁이다. 또한 실시간 LLM 질의 API용으로 언급된 세 번째 저장소 `gemini_api`는 GitHub API 조회 시 404(존재하지 않음/비공개)로 확인되어, MobileCLIP 재식별과 LLM 오라클 호출의 실제 배포 구현은 공개 코드로 검증할 수 없다.
- 단일 커스텀 로봇·단일 건물(academic office building) 실험에 한정되고, 증분학습 사례도 단 하나의 새 클래스(orange cone, 균일한 색상·형태)로만 시연되어 다양성이 큰 객체 클래스에 대한 일반화는 검증되지 않았다. 저자들도 "classes with large variation may need more images"라고 명시.
- 저자가 인정한 한계: 재학습된 모델은 학습 데이터 분포 밖의 변형(예: 옆으로 누운 cone)은 자동 탐지하지 못하며, LLM은 한 이미지당 최대 7개 색상 박스로 제한되어 밀집 장면에서는 일부 unknown 객체가 라벨링되지 않을 수 있고, MobileCLIP 휴리스틱은 known 객체 수가 많아질수록 성능이 저하된다고 관찰됨.
- 향후 과제로 저자들은 (1) 여러 LLM의 합의(consensus)를 통한 신뢰도 개선과 (2) LLM을 엣지 디바이스에서 직접 실행해 네트워크 의존성을 제거하는 방향을 명시했으며, 두 가지 모두 본 논문에서는 다루지 않았다.

## 7. 원문 기반 핵심 문장
> "By leveraging a small YOLO model with pseudolabels provided by a multimodal large language model (LLM), we develop an effective open set object detector for edge devices."

> "To reduce latency, the YOLO (single-stage CNN-based) architecture [15] is chosen for the OSOD due to the small model size compared to other typical object detection backbones. For example, the YOLOv11n architecture has approximately 2.6 million parameters [18]..."

> "High level processing and decision making are executed on an Nvidia Jetson Orin Nano, a compact edge device with 8 GB RAM, a 6-core ARM CPU, and an Ampere GPU."

> "The average execution time for MobileCLIP on the Ampere GPU is 0.0390 seconds per unknown object... MobileCLIP is still substantially faster than an LLM query which often takes over one second."

> "This `main` branch contains code for training the open set object detector that is deployed on mobile robots... Other git repos that are required include a [ROS noetic image detection package]... for deploying on a mobile robot [and] a repo that serves as the api for the LLM queries." (robot_new_objects README — 배포용 ROS 저장소는 실제로는 빈 스텁이고, LLM API 저장소는 존재하지 않음을 확인)
