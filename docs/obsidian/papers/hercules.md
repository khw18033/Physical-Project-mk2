# HERCULES: An Open-Source Simulation Framework for Heterogeneous Multi-Robot SLAM, Collaborative Perception, and Exploration

## 메타데이터
- categories: Unreal Engine 5 기반 로봇 시뮬레이터, UAV-UGV 이종 다중로봇 협업, 동기화 멀티로봇 센서 로깅, V2X 스타일 협업 인지
- domain: [[로보틱스·다중로봇]], [[협력 인지]]
- source: Garimella, Sandilya Sai, Butterfield, Daniel Chase, Wilson, Sean, Gan, Lu. "HERCULES: An Open-Source Simulation Framework for Heterogeneous Multi-Robot SLAM, Collaborative Perception, and Exploration." arXiv preprint arXiv:2606.22756 [cs.RO], 2026.
- url: https://arxiv.org/abs/2606.22756 (code: https://github.com/lunarlab-gatech/HERCULES)
- year: 2026
- authors: Sandilya Sai Garimella, Daniel Chase Butterfield, Sean Wilson, Lu Gan (Georgia Institute of Technology; Wilson also Georgia Tech Research Institute)
- venue: arXiv preprint (submitted 22 Jun 2026, cs.RO). GitHub README/paper 어디에도 학회·저널 게재(accepted) 표시는 없다 — 검증 시점 기준 preprint 단계.

## 1. 핵심 요약
- HERCULES는 Microsoft AirSim/Cosys-AirSim(Unreal Engine 5 기반)을 포크해 만든 오픈소스 시뮬레이터로, 기존 프레임워크가 세션당 한 종류의 vehicle(SimMode)만 지원하던 구조적 한계를 재설계해 UAV(멀티로터)와 UGV(Husky형 차동구동, SUV)가 하나의 시뮬레이션 세션에서 동시에 동작하도록 만든 것이 핵심 기여다.
- UAV의 `moveToPositionAsync` 계열 인터페이스를 거울상으로 미러링한 waypoint-tracking UGV 컨트롤러(pure-pursuit 기반, 논문 4.3절/부록 D)를 새로 구현해 이종 플랫폼을 동일한 상위 API로 명령할 수 있게 했고, 전역 시뮬레이션 clock에 기반한 pause-step-resume 방식으로 여러 로봇의 센서 로깅을 동기화하는 데이터 수집 파이프라인을 제공한다.
- 논문은 이 시뮬레이터로 생성한 데이터 위에서 기존 오픈소스 방법(ROMAN+LIO-SAM+CLIPPER 협업 SLAM, PointPillars 기반 late-fusion 협업 인지)을 "벤치마크"로 실행해 결과를 보였으나, 이 벤치마크를 재현할 평가 스크립트·베이스라인 코드 자체는 저장소 README의 Roadmap 섹션에 **미출시(체크박스 미완료) 상태**로 명시되어 있다 — 즉 "시뮬레이터가 협업 SLAM/인지를 지원한다"는 것은 필요한 동기화 멀티모달 데이터를 생성할 수 있다는 의미이지, 저장소에 바로 실행 가능한 협업 SLAM/인지 파이프라인이 포함되어 있다는 뜻이 아니다(검증 시점 기준).
- 저장소는 2026-02-09 생성, 마지막 push 2026-08-27로 약 7개월차의 신생·소규모 프로젝트(★21, fork 2, open issue 0)이며, LWIR 열화상·야간투시(NVG) 센서, 사막/숲/도시 3개 대형 환경, 산불·홍수·작물병 확산 같은 동적 현상 Blueprint 등 부가 기능도 포함한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 UE5 기반 로봇 시뮬레이터(AirSim/Cosys-AirSim)는 물리 엔진 SimMode가 세션당 하나의 vehicle 타입만 허용해 UAV-UGV 이종 팀을 하나의 세션에서 동시에 운용할 수 없었고, UGV에는 UAV와 대칭적인 고수준 waypoint 제어 인터페이스가 없었다.
- 기술적 목표: (1) SimMode 계층을 재설계해 UAV/UGV 동시 운용을 가능하게 하고, (2) UAV와 동일한 API로 조작 가능한 UGV waypoint 컨트롤러를 제공하고, (3) 여러 로봇에 걸친 시간 동기화된 멀티모달 센서 로깅 파이프라인을 구축하고, (4) 이를 바탕으로 협업 SLAM·협업 인지·탐사(exploration) 연구를 위한 재현 가능한 벤치마크 샌드박스를 제공하는 것.
- 다루는 범위: 아키텍처 재설계(SimMode 통합), 신규 UGV 컨트롤러 설계, LWIR/NVG 신규 센서 모델링, 동적 환경 현상(산불/홍수/작물병) Blueprint, 데이터 수집 파이프라인(수동/능동 모드), ROMAN 협업 SLAM 및 DAIR-V2X 스타일 협업 인지를 이용한 실험적 검증.

## 3. 핵심 개념 상세

### SimMode 통합 아키텍처 (이종 동시 운용)
- 원문 표현(README): "We re-architect the AirSim/Cosys-AirSim SimMode layer to enable concurrent UAV–UGV operation within a single simulation session, resolving a fundamental physics-engine conflict that previously restricted each session to one vehicle type."
- 정의: AirSim은 세션 전체의 물리·스폰·API 디스패치를 결정하는 전역 SimMode 파라미터로 멀티로터 또는 차량 중 하나만 선택하도록 강제했는데, HERCULES는 이를 재구성해 각 플랫폼을 적절한 물리 백엔드로 라우팅하면서 world state와 시뮬레이션 clock은 공유하도록 만들었다.
- 역할: 이 재구성이 없으면 UAV와 UGV를 같은 환경에서 동시에 띄우는 것 자체가 불가능하므로, 이후의 waypoint 통합 인터페이스와 멀티로봇 센서 동기화는 모두 이 아키텍처 변경 위에 성립한다.

### 통합 waypoint 명령 인터페이스 + UGV pure-pursuit 컨트롤러
- 원문 표현(README/paper): "we implement a waypoint-level command interface that abstracts platform-specific control so that high-level planners can issue commands to UAVs and UGVs through the same API." UGV 컨트롤러는 "a geometric pure-pursuit path tracker with proportional steering and speed control"으로 "mirrors UAV moveToPositionAsync interface"라고 기술된다(논문 4.3절, 부록 D).
- 정의: 기존 UAV의 `moveToPositionAsync` 류 API와 대칭되는 형태로 UGV용 pure-pursuit 경로 추종기를 새로 구현하고, 두 플랫폼을 동일한 상위 waypoint API로 명령할 수 있게 한 것.
- 확인된 사실과 한계: 이 인터페이스는 코드 수준에서 실제로 존재하는 것으로 보이나(README 하이라이트, 논문 4.3절 수식·부록에 구체 서술), README·PythonClient 예제로 확인 가능한 코드는 `hello_car.py`처럼 기존 AirSim에서 상속된 범용 예제뿐이며, waypoint 인터페이스 자체를 호출하는 구체적 코드 스니펫은 README 본문에는 제시되어 있지 않다(별도 `PythonClient/README.md`, `docs/` 하위 문서를 봐야 함). 즉 "존재는 확인되나 README 표면에서 바로 보이는 사용 예시는 아니다."

### 동기화 멀티로봇 센서 로깅 파이프라인
- 원문 표현(paper 5.1절 요약): 데이터 수집 도구는 "deterministic pause–step–resume cycles governed by a single global simulation clock"으로 시뮬레이터를 구동하며, 모든 센서 캡처와 pose 로깅이 이 clock에 게이팅된다.
- 정의: 여러 로봇의 센서 스트림이 공통 시간 기준을 공유하도록 강제하는 결정론적 clock 동기화 메커니즘. LiDAR 같은 센서가 pause/resume 중간에 회전이 끊기지 않도록 하는 등 단일 vehicle 가정을 깨는 저수준 수정도 포함한다.
- 확인된 사실: 실제 export 포맷은 ROS/ROS 2 bag(동기화된 `/clock` 토픽 포함), KITTI 스타일 변환기, PNG/TXT/NPY/CSV 원시 파일 세트로 구체적이며, README의 "Multimodal Dataset" 섹션에 로봇별 RGB/depth/semantic/LiDAR를 보여주는 실제 대시보드 GIF가 첨부되어 있어 단순 서술이 아니라 실제로 데이터가 생성됨을 뒷받침한다. 다만 알고리즘 의사코드 수준의 상세는 논문에 제시되지 않는다.

### 협업 SLAM 벤치마크 (ROMAN + LIO-SAM + CLIPPER)
- 원문 표현(README): "We benchmark ROMAN collaborative SLAM on a City Block sequence with two UAVs and two UGVs. Each robot runs LIO-SAM odometry with an open-set ROMAN object map; inter-robot loop closures are registered pairwise via CLIPPER."
- 정의: HERCULES 자체는 협업 SLAM 알고리즘을 구현하지 않으며, 시뮬레이터가 생성한 동기화 멀티모달 데이터(2 UAV + 2 UGV) 위에서 기존 오픈소스 방법인 ROMAN(객체 지도 기반 SLAM, MIT ACL)·LIO-SAM(LiDAR-관성 오도메트리)·CLIPPER(pairwise loop closure 정합)를 실행해 성능을 보여주는 벤치마크 시나리오다.
- 확인된 사실: README에 실제 Live Mapping·Final Map·Loop-Closure Alignment GIF가 UAV 2대·Husky UGV 2대에 대해 각각 첨부되어 있어 결과 자체는 실제로 생성된 것으로 보인다. 그러나 Roadmap 섹션은 "Collaborative SLAM benchmark — release the ROMAN evaluation scripts and configs"를 **미완료 체크박스**로 명시해, 이 벤치마크를 그대로 재현할 스크립트·설정 파일은 검증 시점 기준 저장소에 아직 공개되지 않았다. Overview 섹션의 "ships ready-to-run baselines" 표현과 Roadmap의 "release … (예정)" 표현이 서로 배치되는 문서 내 불일치가 있다.

### 협업 인지 (V2X 스타일, DAIR-V2X 벤치마크)
- 원문 표현(README): "HERCULES supports V2X-style collaborative perception: a vehicle-side agent (a UGV on the sidewalk) and an infrastructure-side agent (an overhead UAV) observe a shared city intersection from complementary viewpoints. Each exports time-synchronized RGB and LiDAR."
- 정의: 차량측(UGV)과 인프라측(UAV)이 동일 교차로를 서로 다른 시점에서 관측하도록 배치하고, 각각 시간 동기화된 RGB·LiDAR를 export해 DAIR-V2X 스타일의 multi-view 3D object detection(예: late-fusion PointPillars)에 쓸 수 있는 데이터를 생성하는 시나리오. 논문은 이 데이터로 sim-to-sim late-fusion 실험과 실제 DAIR-V2X 데이터로의 sim-to-real fine-tuning 실험(IoU=0.70에서 AP40 +4.11 개선)을 수행했다고 보고한다.
- 확인된 사실: 이 역시 시뮬레이터는 동기화된 다시점 데이터 생성기 역할을 하고, 실제 fusion 알고리즘(PointPillars 등)은 외부 구현을 사용한다. Roadmap의 "Cooperative perception baselines — release the DAIR-V2X-style multi-view 3D detection code"도 미완료로 표시되어, 위 SLAM 벤치마크와 동일하게 "결과는 논문에 존재하지만 재현용 베이스라인 코드는 저장소에 아직 없음" 상태다.

### 신규 센서: LWIR 열화상 · 야간투시(NVG)
- 정의: LWIR는 Planck 법칙 기반 스펙트럼 복사 휘도와 재질 방사율·온도 프라이어를 이용해 8–14 μm 대역 열화상을 물리 기반으로 합성하는 카메라이고, NVG는 경험적 광도 변환 함수(적응형 게인, 감마 보정, 센서 노이즈, 그린 포스퍼 컬러맵)로 이미지 인텐시파이어 동작을 근사하는 모드다. 둘 다 기존 RGB/depth 출력 위의 경량 후처리 레이어로 계산되어 렌더링 파이프라인 수정 없이 런타임 재구성이 가능하다.
- 역할: Cosys-AirSim이 원래 제공하던 RGB/depth/semantic/LiDAR/GPU-LiDAR/echo·radar/IMU/GPS/기압계/자력계/초음파/UWB 센서 스위트에 저조도·열영상 조건에서의 인지 연구를 위한 두 가지 모달리티를 추가한 것.

## 4. 구조 및 흐름
1. AirSim/Cosys-AirSim 포크 후 SimMode 계층을 재설계해 UAV(멀티로터)와 UGV(Husky형 차동구동, SUV)를 하나의 world state·clock 아래 동시 스폰 가능하게 만든다.
2. UAV의 `moveToPositionAsync` 인터페이스에 대응하는 pure-pursuit 기반 UGV waypoint 컨트롤러를 구현해, 상위 planner가 플랫폼 종류와 무관하게 동일한 waypoint API로 명령을 내릴 수 있게 한다.
3. 전역 시뮬레이션 clock에 기반한 pause-step-resume 방식으로 데이터 수집 도구가 각 로봇의 RGB/depth/semantic/LiDAR/IMU/GPS(+ 신규 LWIR/NVG)를 동기화 캡처하고, ROS 2 bag·KITTI 스타일·PNG/NPY/CSV로 export한다.
4. 두 가지 실행 모드 지원: 수동(passive) 모드는 오프라인 설계된 궤적을 재생해 재현 가능한 데이터셋을 생성하고, 능동(active) 모드는 실시간 관측으로부터 온라인 planner를 closed-loop로 구동한다.
5. 이렇게 생성한 데이터 위에서 기존 오픈소스 방법(ROMAN+LIO-SAM+CLIPPER 협업 SLAM, PointPillars late-fusion 협업 인지)을 실행해 사막/숲/도시 대형 환경과 City Block 교차로 시나리오에 대한 벤치마크 결과를 논문 실험으로 제시한다. 이 벤치마크의 재현용 평가 스크립트·베이스라인 코드는 README Roadmap에 별도 공개 예정 항목으로 남아 있다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| HERCULES는 기존 UE5 시뮬레이터의 SimMode 제약을 해소해 UAV-UGV를 한 세션에서 동시 운용할 수 있게 한다 | README/논문 모두 "concurrent UAV–UGV operation within a single simulation session"을 아키텍처 재설계의 핵심 기여로 명시; README의 UAV+UGV 이종 팀 주행 GIF(사막/숲/도시)로 실제 동작을 시각적으로 뒷받침 |
| UGV용 waypoint 컨트롤러가 UAV 인터페이스를 거울상으로 지원해 상위 코드가 플랫폼을 구분하지 않아도 된다 | 논문 4.3절/부록 D에 pure-pursuit 정식화 제공, README Highlights에 "a unified waypoint-level command interface, an autonomous UGV controller" 명시. 다만 README 표면에는 이 API를 직접 호출하는 코드 스니펫이 없어 구체 사용법은 별도 문서(`PythonClient/README.md`, `docs/`) 확인이 필요 |
| 시뮬레이터가 생성한 동기화 데이터로 협업 SLAM·협업 인지 벤치마크를 재현할 수 있다 | 논문은 ROMAN 협업 SLAM(2 UAV+2 UGV, City Block)과 DAIR-V2X 스타일 협업 인지(UGV+UAV 교차로) 실험 결과를 제시하고 README에 대응 GIF를 첨부; 그러나 이 두 벤치마크의 평가 스크립트·베이스라인 코드는 README Roadmap에서 "release … (예정)"으로 표시되어 있어 검증 시점 기준 저장소에서 바로 재현할 수는 없다 — "지원"은 데이터 생성 능력의 의미이지 즉시 실행 가능한 파이프라인 배포를 뜻하지 않는다 |
| 저장소는 MIT 라이선스이다 | README 상단에 "License: MIT" 배지가 있고 LICENSE 파일 내용은 Microsoft AirSim(2022)·Codex Laboratories LLC(2022)·University of Antwerp Cosys-Lab(2024) 세 개의 MIT 라이선스 고지가 이어 붙은 형태로, 모두 MIT 표준 문구다. 다만 GitHub API가 반환하는 자동 감지 결과는 `license.spdx_id = NOASSERTION`(name: "Other")인데, 이는 파일에 저작권자가 다른 MIT 고지가 여러 개 겹쳐 있어 GitHub의 자동 분류기가 단일 표준 MIT 템플릿으로 인식하지 못했기 때문으로 보인다. 실질 라이선스 문구는 MIT이지만 GitHub UI/API 표시상으로는 "Other"로 나타나는 점을 구분해야 한다 |
| 시뮬레이터는 아직 초기 단계이지만 활발히 개발 중이다 | GitHub API 기준 저장소 생성일 2026-02-09, 마지막 push 2026-08-27(약 7개월, 최근 활동 있음), ★21/fork 2/open issue 0으로 커뮤니티 규모는 작음. 최근 커밋은 "Doc corrections and Build fixes", "Add guide for downloading the Fab environment packs"(2026-08 초) 등 문서·빌드 수정 위주이며, README에 보이는 "5,254 commits"는 AirSim/Cosys-AirSim 포크 이력을 그대로 유지한 숫자로 HERCULES 고유 개발량을 나타내지 않는다. README Roadmap은 협업 SLAM/인지 베이스라인 코드, 전체 데이터셋 업로드, 커스텀 phenomenon Blueprint 공개 등 핵심 항목을 "미완료"로 명시하고 있어, 문서화된 청사진과 사용 가능한 예제는 있지만 다수 핵심 산출물이 아직 배포 전인 초기 공개 단계다 |

## 6. 한계 및 부족한 점
- 이 요약은 GitHub 저장소(README, LICENSE, GitHub REST API 메타데이터·커밋 로그)와 arXiv HTML/abs 페이지(2606.22756)를 웹 조회 도구로 확인해 작성했으며, PDF 전체 본문을 직접 파싱하지는 않았다 — 논문 부록(D)의 pure-pursuit 수식 전체나 실험 표의 정량 수치 원문은 웹 요약을 통해서만 확인했으므로 세부 수치 인용은 별도 원문 대조가 필요하다.
- "협업 SLAM/협업 인지 지원"의 의미는 검증 결과 (1) 시뮬레이터의 동기화 멀티로봇 데이터 생성 능력, (2) 그 데이터 위에서 논문 저자가 별도로 실행한 외부 오픈소스 방법(ROMAN/LIO-SAM/CLIPPER, PointPillars)의 실험 결과 두 가지로 구성되며, (3) 이를 그대로 재현할 평가 스크립트·설정·베이스라인 코드는 README Roadmap에 아직 미공개로 남아 있다. README Overview의 "ships ready-to-run baselines" 문구와 Roadmap의 "release … (예정)" 체크박스가 서로 어긋나는 문서 내 불일치가 있어, 사용자가 실제로 기대할 수 있는 즉시 재현성은 README만 보고 판단하면 과대평가될 수 있다.
- 라이선스는 문구상 MIT이지만 GitHub의 자동 라이선스 감지(API `license.spdx_id`)는 NOASSERTION/"Other"로 나온다. 이는 여러 저작권자의 MIT 고지가 중첩된 LICENSE 파일 구조 때문으로 추정되며, 재배포·상용 이용 시에는 배지만 보지 말고 LICENSE 파일의 세 고지 전체(Microsoft, Codex Laboratories, University of Antwerp)를 확인할 필요가 있다.
- README에 등장하는 사막(호주 아웃백)·숲·도시 대형 사진실사 환경은 저장소에 기본 포함된 것이 아니라 Epic Fab 마켓플레이스에서 별도로 내려받아야 하며, 최근 커밋("Add guide for downloading the Fab environment packs")이 "버전 workaround가 필요한 3개 무료 환경"이라고 언급한 점에서 이 부분의 설치 경험이 아직 매끄럽지 않을 가능성이 있다. 저장소에 기본 포함된 것은 `Blocks`(최소 환경)와 `DynamicObjects`뿐이다.
- 빌드에는 Unreal Engine 5.2.1 소스 빌드, clang-12, ROS 2 Humble, Python 3.10 가상환경 등 무거운 사전 요구사항이 필요해 "오늘 당장 가볍게 써볼 수 있는" 수준은 아니며, ★21/fork 2/open issue 0이라는 작은 커뮤니티 규모는 실전 검증(다양한 환경에서의 버그 리포트, 서드파티 사용 사례)이 아직 축적되지 않았음을 시사한다.

## 7. 원문 기반 핵심 문장
> "HERCULES resolves key architectural limitations of prior frameworks to enable concurrent unmanned aerial and ground vehicle (UAV-UGV) operation in large-scale, photorealistic, dynamic environments. It introduces a new waypoint-tracking UGV controller that mirrors existing UAV control interfaces..." (arXiv:2606.22756 abstract)

> "As a benchmark sandbox, HERCULES ships ready-to-run baselines for collaborative SLAM (ROMAN) and collaborative perception (DAIR-V2X-style multi-view 3D detection)." (GitHub README, Overview)

> "Collaborative SLAM benchmark — release the ROMAN evaluation scripts and configs. / Cooperative perception baselines — release the DAIR-V2X-style multi-view 3D detection code." (GitHub README, Roadmap — 검증 시점 기준 미완료 체크박스)
