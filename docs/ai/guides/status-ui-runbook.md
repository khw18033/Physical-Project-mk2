# 검토용 상태 UI — 실행·확인·확장·되돌리기

작성 2026-09-17. 대상: `perception-framework/tools/status_ui/` (P1~P4 구현 확인용
로컬 도구). **운영 UI가 아니다** — 운영 화면은 가시화 파트 몫이고, 이 도구는 우리
코드가 실제로 내는 값(선택 결과·대안·사유·배치 동작)을 눈으로 확인하기 위한 것이다.

## 1. 실행

```bash
cd perception-framework
.venv/bin/python tools/status_ui/serve.py --config config/status_ui.example.json
# → http://127.0.0.1:8765  (브라우저에서 열기; WSL2면 Windows 브라우저에서 같은 주소)
```

| 항목 | 값 |
|---|---|
| 실행 파일 | `perception-framework/tools/status_ui/serve.py` (stdlib만 사용, 추가 설치 없음) |
| 화면 | `perception-framework/tools/status_ui/index.html` (외부 리소스 0 — 폐쇄망에서도 렌더) |
| 기본 주소 | `http://127.0.0.1:8765` — `--host`, `--port`로 변경. `--port 0`은 빈 포트 자동 선택 |
| 설정 파일 | `perception-framework/config/status_ui.example.json` (노드·배포 프로파일·capability 목록) |
| provider 목록 | 설정 파일의 `providers_manifest`가 가리키는 manifest — 기본 `config/providers.status_ui.example.json` |
| 배치 백엔드 | `--control local`(기본, `LocalControlSupervisor` 인메모리) / `--control k3s [--namespace default]` |

`--control k3s`는 `kubectl`이 없거나 클러스터에 못 붙으면 **예외 없이 local로 폴백**하고
`/api/config`의 `control.reason`에 `orchestrator_unavailable`을 남긴다(AI-B-05: 오케스트레이터
부재가 기능을 막지 않는다).

## 2. 화면에서 확인할 것 — 각 P가 어디에 보이는가

| 확인 항목 | 화면 위치 | 무엇을 증명하나 |
|---|---|---|
| 노드 바꾸면 같은 레지스트리가 다르게 풀림 | 상단 노드 버튼 (pi6 / edge-dev / edge-gpu) | `ZoneApplication.resolve()` — 태그·예산이 선택을 바꾼다 |
| 행마다 "대안 N" 펼치기 | capability 행 | **P1** `alternatives` — 탈락 후보와 사유(`required_hw_tag_missing:compute.gpu`, `over_budget`, `compatible`) |
| 사유의 굵은 토큰 + 회색 데이터 | capability 행 reason | **P2** `STATE_CHANGE_REASONS` 통제 어휘 + `:data` 접미 |
| "표시 등급(파생)" 칩 | capability 행 | READY/BLOCKED/MISSING/STALE이 **상태가 아니라 (상태, 사유)에서 파생**된다는 것(계획 §3-2) |
| provider 목록·비용·priority | 행의 provider/cost | **P3** manifest에서 읽힘 — `config/providers.status_ui.example.json` 편집 → 재시작 → 반영 |
| What-if: 태그 체크 해제 / 예산 축소 / provider 제외 | 좌측 패널 | 축소 순서(degrade_rank), 대체 provider로 자동 전환, "before → after" |
| "배치 적용" 버튼 | 하단 배치 패널 | **P4** `PlacementReconciler` — 첫 적용은 start, 두 번째는 변화 없음, provider 제외 후 적용은 stop→start. 각 provider의 `node_selector`(`aif.io/<tag>: "true"`) 표시 |
| 이벤트 로그 | 하단 | `placement_applied` 이벤트 — AI-O-02 구조화 사건 |

## 3. API (curl로 직접 확인)

```bash
B=http://127.0.0.1:8765
curl -s $B/api/config | python3 -m json.tool        # 노드·control 모드·manifest 경로
curl -s $B/api/vocabulary                            # STATE_CHANGE_REASONS, 파생 등급 매핑
curl -s "$B/api/resolve?node_id=pi6"                 # 기준선 해석 결과(+alternatives)
curl -s -X POST $B/api/whatif -H 'content-type: application/json' \
  -d '{"node_id":"pi6","tags":["compute.cpu","compute.gpu"]}'   # GPU가 생기면?
curl -s -X POST $B/api/whatif -H 'content-type: application/json' \
  -d '{"node_id":"edge-gpu","exclude_providers":["clip-dictionary-cuda"]}'  # provider 소실
curl -s -X POST $B/api/placement -H 'content-type: application/json' -d '{"node_id":"edge-gpu"}'
curl -s "$B/api/placement?node_id=edge-gpu"          # 바인딩 + node_selector + audit tail
curl -s $B/api/events
curl -s -X POST $B/api/reset
```

## 4. 확장 시 고칠 파일 (코드는 안 고친다)

| 하고 싶은 것 | 고칠 파일 | 어디를 |
|---|---|---|
| 노드 추가(예: 실제 pi6 태그) | `config/status_ui.example.json` | `nodes[]`에 `{node_id, label, tags, budget}` 한 항목. 태그는 `providers/compute.py::discover_node_tags()`가 돌려주는 문자열과 같은 어휘(`compute.cpu`, `compute.gpu`, `media.hw_decode`, …) |
| provider 추가/비용·우선순위 변경 | `config/providers.status_ui.example.json` | `providers[]`에 항목 추가. 필수 키는 `capability_kind/provider_id/version`뿐. priority 숫자가 작을수록 먼저 선택. 컨테이너로 띄우는 것이면 `deployment: {image, command}` |
| capability kind 추가/core 지정/축소 순서 | `config/status_ui.example.json` | `deployment.active_capability_kinds`에 kind 추가 + `capabilities[]`에 `{kind, is_core, degrade_rank, requirement}` |
| 폐쇄망으로 검사 | `config/status_ui.example.json` | `deployment.closed_network: true` — 외부 endpoint를 선언한 provider가 `external_connection_*` 사유로 탈락하는지 확인 |
| 실제 클러스터에 배치 | 실행 인자 | `--control k3s --namespace <ns>`; manifest의 `deployment.image`가 실제로 pull 가능한 이미지여야 함(`example.invalid/...` 기본값은 의도적으로 실패한다 — `image_pull` 거부가 그대로 사유로 보인다) |

### 4-1. 실기기 인벤토리 (2026-09-17 SSH 실측, Tailscale `*.tailcb6bfb.ts.net`)

| 노드 | 보드 | 카메라 | 확인 방법 |
|---|---|---|---|
| pi6 (100.76.251.100) | Raspberry Pi 5 Model B Rev 1.0 | **Camera Module 3** — `imx708`, 4608×2592 10-bit RGGB, 모드 1536×864@120 / 2304×1296@56 / 4608×2592@14.35 | `rpicam-hello --list-cameras`, `rpicam-still` 720p 촬영 성공 |
| pi4 (100.81.196.55) | Raspberry Pi 5 Model B Rev 1.0 (이름만 pi4) | **Camera Module 3 Wide** — `imx708_wide`, 같은 해상도·모드(렌즈만 광각) | 동일 |

둘 다 `camera_auto_detect=1`, `/dev/video0` 존재. `config/status_ui.example.json`의 `nodes[]`에
`sensor.camera.imx708` / `sensor.camera.imx708_wide` 태그로 반영해 두었다 — 광각 전용
provider(예: 넓은 시야가 필요한 기능)를 `required_hw_tags: ["sensor.camera.imx708_wide"]`로
등록하면 pi4에서만 선택된다.

## 5. k3s 실측 절차 (선택)

**이 개발 기기(WSL2) 현황(2026-09-17 확인)**: `/usr/local/bin/k3s server`가 이미 떠 있고
`kubectl`도 설치돼 있으나, `/etc/rancher/k3s/k3s.yaml`이 root 전용이라 일반 사용자
`kubectl`이 `permission denied`로 실패한다 → 그래서 `tests/test_k3s_control.py`의
클러스터 테스트 6건이 skip되고 `--control k3s`도 local로 폴백한다. 둘 중 하나로 푼다
(sudo가 필요하므로 사용자 결정):

```bash
# (a) 읽기 권한 부여 — 가장 간단. 이 기기의 kubeconfig에는 클러스터 admin 토큰이 들어 있으므로
#     공용 기기라면 (b)를 쓴다.
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
# (b) 사용자 전용 복사본
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config && sudo chown $USER ~/.kube/config
```

**(b)를 했는데도 `permission denied`가 나면**: `~/.bashrc`(이 기기는 121행)에
`export KUBECONFIG=/etc/rancher/k3s/k3s.yaml`이 있어 복사본을 무시한다. 그 줄을
`export KUBECONFIG=$HOME/.kube/config`로 바꾸고 `source ~/.bashrc`. (2026-09-17 실측: 이 조치
후 `tests/test_k3s_control.py` 14건 전부 실행·통과, `--control k3s`로 실제 Deployment 생성 확인.)

**2026-09-17 실측 결과(이 기기, 노드 `desktop-0ib285f`에 `aif.io/compute.cpu=true`·`aif.io/tier.edge=true` 라벨)**:
edge-dev에 배치 적용 → `aif-grounding-dino` Running, `aif-clip-dictionary-cuda`는 nodeSelector
`aif.io/compute.gpu=true`를 만족하는 노드가 없어 **Pending**(P4 의도대로 — 선택기가 배제한 노드에
Pod가 떨어지지 않는다). `grounding-dino` 제외 후 재적용 → 클러스터에서 `aif-grounding-dino` 0/0,
`aif-yolo-world` 1/1. 이미지는 manifest의 `example.invalid/...`를 `busybox:latest`로 바꾼 임시
사본으로 실험했고, 끝나고 Deployment 3개 삭제.

1. `kubectl get nodes`가 되는지 확인.
2. 노드에 라벨: `kubectl label node <node> aif.io/compute.gpu=true` (manifest의 `required_hw_tags`와 같은 이름).
3. manifest의 `deployment.image`를 실제 이미지로 바꾼다.
4. `serve.py --control k3s` 실행 → 배치 적용 → `kubectl get deploy -n <ns>`에서 `aif-<provider_id>` 확인, `kubectl get pod -o yaml | grep -A2 nodeSelector`로 라벨 반영 확인.
5. 끝나면 `kubectl delete deploy -l app=aif-*` 또는 UI "초기화"(local 모드에서만 상태를 지운다 — k3s 리소스는 직접 삭제).

## 6. 되돌리기

각 작업이 별도 커밋이다. `git log --oneline` 기준:

| 되돌릴 것 | 명령 |
|---|---|
| UI만 | `git revert 498e901` |
| P4 배치 | `git revert 36477cb` |
| P3 manifest | `git revert 3e371ae` (UI가 manifest에 의존하므로 UI 커밋도 함께) |
| P2 어휘 | `git revert db06925` |
| P1 대안 | `git revert b6f0b38 21d44e9` (P2 테스트가 selector 상수를 참조하므로 P2도 함께) |
| 전부 | `git reset --hard 98e7792` (P1 착수 직전 체크포인트) |

## 7. 테스트

```bash
cd perception-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_selector.py tests/test_application_alternatives.py tests/test_data_dictionary.py \
  tests/test_provider_manifest.py tests/test_placement.py tests/test_status_ui.py 2>/dev/null
```
(stderr의 `Failed to export metrics to 127.0.0.1:4317`는 OTel collector가 없어서 나는 소음이며 실패가 아니다.)
