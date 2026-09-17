# 가시화 파트 전달: 기능 상태 검토 UI

작성일: 2026-09-17. 관련 요구사항: AI-C-19(가시화 경계), AI-B-05(선택 인프라 장애 시 폴백).

## 목적과 적용 범위

프레임워크가 계산하는 기능 가용성, 제공 계층, 자원 요구량, 기능 불가 사유를 가시화 담당자가 직접 확인하고 운영 화면의 데이터 계약을 검토하는 로컬 도구다. 설정과 provider manifest를 입력으로 상태를 계산한다. 화면의 ACTIVE는 실제 카메라 스트리밍·모델 추론·로봇 동작 성공을 측정한 결과가 아니다. 운영 UI로 이관할 때 실측 상태와 설정 기반 판정을 구분해야 한다.

구현은 `perception-framework/tools/status_ui/serve.py`(표준 라이브러리 HTTP 서버)와 `index.html`(화면)이며 CDN이나 외부 폰트를 사용하지 않는다. 서버는 프레임워크 소스를 직접 불러온다.

## 화면 내용

| 화면 | 전달하는 정보 |
|---|---|
| 기능(기본) | 기능별 가능·일부만 가능·불가, 필수/선택 capability, 제공 계층과 provider, 부족한 capability와 보충 사유 |
| 계층·자원 | 계층별 노드, 태그·예산, provider 제외, What-if, 배치 액션·바인딩·이벤트 |
| 개발자 | 원본 CapabilityState, 사유 토큰, 대안 provider 탈락 사유, 비용·우선순위·nodeSelector, 라벨 누락 |
| KO / EN | 동일한 응답 ID를 한국어·영어 라벨로 표시, 선택 언어는 브라우저에 저장 |

표현의 기본 축은 기능 → 계층·자원 → 노드 상세다. 색과 텍스트를 함께 표시한다. READY/DEGRADED/MISSING/STALE/BLOCKED는 UI의 파생 등급이며 프레임워크 CapabilityState와 별도 필드로 취급한다. 자원 수치는 manifest의 요구 비용을 집계한 것으로 CPU/GPU 실시간 사용률이 아니다.

현재 예제의 계층은 다음과 같다. `role`은 자유 문자열이므로 운영 화면에서 고정 enum으로 제한하지 않는다.

- `ondevice`: `go1-onboard`, Go1 탑재 연산기·전방 카메라를 가정한 미실측 설정. 이동 제어 provider를 제공한다.
- `fixed_camera`: `pi6`(imx708), `pi4`(imx708_wide), 고정 카메라 인프라. 이동 제어 역할과 분리한다.
- `edge`: `edge-dev`, `edge-gpu`, 구역 연산과 미디어 입력.
- `server`: `server-1`, 중앙 연산과 미디어 입력.

## 실행 방법

저장소 루트에서 실행한다. 기본 확인에는 클러스터나 모델 가중치가 필요하지 않다.

```bash
cd perception-framework
python3 tools/status_ui/serve.py \
  --config config/status_ui.example.json \
  --control local --host 127.0.0.1 --port 8765
```

브라우저에서 `http://127.0.0.1:8765/`를 연다. 포트가 사용 중이면 `--port 8766` 또는 `--port 0`으로 바꾸고 터미널에 출력된 주소를 연다. 종료는 `Ctrl+C`다. 접속 주소는 서버가 실행되는 환경 기준이며 원격 개발 환경에서는 해당 포트를 전달해야 한다.

설정 파일:

- `config/status_ui.example.json`: 기능의 필수/선택 capability, 노드·role·태그·예산.
- `config/providers.status_ui.example.json`: provider의 요구 태그·비용·우선순위·배치 정의.
- `config/status_ui.labels.json`: 기능·계층·사유 등의 한국어/영어 표현.

설정 변경 후 서버를 재시작한다. 현장 주소나 인증정보가 필요한 설정은 별도의 로컬 파일로 관리하고 커밋하지 않는다.

## API 연결 기준

서버 주소를 기준으로 아래 경로를 호출한다. 응답은 언어 중립 ID 중심이며 라벨은 별도 조회한다.

| 요청 | 용도 |
|---|---|
| `GET /api/config` | 기능·노드·role·provider·control 모드·라벨 누락 |
| `GET /api/labels` | 한국어/영어 표시 문자열 |
| `GET /api/functions` | 기능 상태, required/optional, resources, supplement |
| `GET /api/fleet` | 노드별 계산 결과와 kind별 제공 목록 |
| `GET /api/resolve?node_id=pi6` | 노드별 capability와 alternatives |
| `GET /api/vocabulary` | 상태·파생 등급·사유 어휘 |
| `POST /api/functions/whatif` | 가상 태그·예산·provider 제외에 따른 before/after/diff |
| `GET /api/placement?node_id=edge-gpu` | 현재 배치 바인딩·감사 로그 |
| `POST /api/placement` | 지정 노드의 배치 적용 |
| `GET /api/events` | 배치·폴백·초기화 이벤트 |
| `POST /api/reset` | 검토 도구의 배치·이벤트·control 상태 초기화 |

```bash
curl -s http://127.0.0.1:8765/api/functions
curl -s -X POST http://127.0.0.1:8765/api/functions/whatif \
  -H 'Content-Type: application/json' \
  -d '{"overrides":{"*":{"exclude_providers":["unidepth"]}}}'
```

What-if는 가상 조건 비교이며 배치 적용과 별개다. `overrides`의 `"*"`는 전체 기본값, 노드 ID 항목은 개별 덮어쓰기다. 예산 일부만 넘기면 나머지는 기존 설정을 유지한다.

`required[]`/`optional[]`의 `missing`, `activated`, `served_by`, `why`를 함께 해석한다. `activated: false`는 프로파일 비활성 상태다. `supplement[]`는 부족한 kind를 계층별 사유와 함께 제공한다. 사유는 `reason_token`과 `reason_data`로 처리하고 번역 문구를 조건식에 사용하지 않는다. 알 수 없는 ID는 원문을 표시하며 신규 role·kind에도 화면이 유지되도록 한다.

## 가시화 담당자 확인 순서

1. local 모드에서 기능 탭을 열어 `local_safety`, `door_detection`, `go_to_door`의 가능 상태와 `risk_analysis`의 불가 사유를 확인한다.
2. 이동 기능 상세에서 이동 제어 제공자가 `go1-onboard`이며 고정 카메라는 해당 역할을 제공하지 않는지 확인한다.
3. What-if로 전체 노드에서 `unidepth`를 제외한다. `go_to_door`는 불가, `local_safety`는 일부만 가능으로 바뀌는 비교를 확인한다.
4. KO/EN을 바꿔 동일한 상태·사유가 번역되고 개발자 탭에 누락 라벨이 없는지 확인한다.
5. 운영 화면에서는 인증·권한, 실시간 상태 수집과 갱신 정책, 제어 권한, 감사 저장, 배포 환경의 통신 경계를 별도로 설계한다. 이 서버에는 사용자 인증 기능이 없으므로 로컬 검토 범위로 사용한다.

## 배치 모드와 한계

기본 `local`은 로컬 control provider를 사용한다. `--control k3s --namespace <namespace>`는 실제 클러스터 Deployment 변경을 수행할 수 있으므로 단순 화면 검토에는 필요하지 않다. 예시 이미지 주소는 `example.invalid`이며 실제 서비스 배포용 이미지가 아니다. kubectl 또는 클러스터 사용이 불가능하면 local로 폴백하고 `/api/config`의 `control.requested`, `control.active`, `control.reason`에 표시한다.

한 프로세스가 control provider 하나를 공유하므로 서로 다른 노드가 같은 provider ID를 배치할 때 target이 겹칠 수 있다. 기능 가용성은 여러 노드의 제공 kind를 합쳐 계산하며 실제 노드 간 데이터 전달·지연·경로 성립까지 검증하지 않는다. 실측 운영 가능 판정에는 추가 연결 검증이 필요하다.

## 관련 자료와 검증

- [도구 README 및 상세 API](../../perception-framework/tools/status_ui/README.md)
- [가시화·오케스트레이션 설계](design/capability-ui-orchestration-plan.md)
- [요구사항 추적](requirement-traceability.md)

```bash
cd perception-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_status_ui.py
```

테스트 의존성이 없으면 가상환경에서 `python3 -m pip install -e '.[dev]'`로 설치한다. 위 명령은 UI 계약 검증이며 하드웨어 실험을 실행하지 않는다.
