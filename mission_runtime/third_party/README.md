# third_party/ — 다른 파트에서 **그대로 복사해 온** 것

여기 있는 것은 우리가 만든 코드가 아니다. 왜 두는지와 어디서 왔는지를 적어 두고,
**내용을 고치지 않는다** — 고쳐야 할 이유가 생기면 원본 쪽에 요청하는 것이 순서다.

| 디렉터리 | 무엇 | 출처 | 라이선스 |
|---|---|---|---|
| `data_stream/` | 실증 배치의 **입력·추론단** — 소스별 수집(10001~10012) · Redis(`camera_stream:*` · `vision_stream:*`) · 디스크 기록 · `vision/vision_infer.py` | `github.com/JNY03/physical_demo` · `data_stream` @ `b8a7fbe` (2026-11-20 복사) | **미정** — 상위 저장소에 라이선스 파일이 없다(아래) |
| `vz-web-dashboard/` | 가시화 파트의 운영 콘솔(React + Vite + 목 게이트웨이) | `github.com/choBottle/Physical-Project-mk2` · `main` @ `30f5ee9` · `visualization/web-dashboard` (2026-11-02 clone) | **MIT** — © 2026 Sysailab, Hanbat National University, and Physical-Project-mk2 contributors. 전문은 [`vz-web-dashboard/LICENSE`](vz-web-dashboard/LICENSE) |

## 라이선스 고지 (2026-11-03 복원)

상위 저장소는 **MIT** 이고, MIT 는 재배포 시 저작권 고지와 허가 문구를 함께 싣도록
요구한다. 처음 복사할 때 `visualization/web-dashboard` 하위 디렉터리만 가져오면서
저장소 루트의 `LICENSE` 가 빠졌고, 그 상태로 공개하면 **고지 없이 MIT 코드를
재배포하는 것**이 된다. 그래서 상위 전문을 `vz-web-dashboard/LICENSE` 에 그대로
복원했다(내용을 고치지 않았다).

하위 디렉터리만 복사할 때 루트 라이선스가 따라오지 않는 것은 흔한 사고다 — 다음에
무엇이든 복사해 오면 **그 저장소의 라이선스 파일을 같은 커밋에서 함께 가져온다.**

이 저장소 자체의 라이선스는 아직 정해지지 않았다(소유자 결정 대기). 그것이 정해져도
이 디렉터리의 MIT 고지는 그대로 남는다 — 상위 저작자의 권리는 우리 선택과 무관하다.

## 왜 복사해 왔나

우리 쪽 검토 페이지(`tools/snapshot_ui/`)는 **우리가 만든 계약이 화면에 올라가는
모양**만 확인한다. 실제 운영 화면은 가시화 파트가 만들고, 그쪽 화면을 눈으로 보며
맞춰 보려면 그 코드가 손에 있어야 한다. 그래서 읽기·실행용으로 한 벌 두었다.

## 두 가지를 혼동하지 않는다

| | `tools/snapshot_ui/` (우리 것) | `third_party/vz-web-dashboard/` (가시화 것) |
|---|---|---|
| 무엇 | 오늘 만든 계약을 한 장으로 확인 | 가시화 파트의 운영 콘솔 |
| 데이터 | 우리 `status_snapshot` + 이 기계 실측 | 자기 목 게이트웨이(WS) — 우리 채널을 아직 모른다 |
| 실행 | 파이썬 표준 라이브러리만 | **Node.js 22.6 이상 필요** |

두 화면이 아직 붙지 않는 이유는 분명하다 — 그쪽 게이트웨이 채널 목록에
`status_snapshot` 이 없고, 채널 개설은 백엔드 결정이다(`docs/integration-handover.md` §1·§2).
그 결정이 나면 어댑터 한 장으로 붙는다.

## 돌리는 법

이 기계에는 Node 가 설치되어 있지 않아 **여기서는 돌지 않는다.** Node 22.6 이상이
있는 기계에서:

```bash
cd third_party/vz-web-dashboard
npm install
npm run dev          # 목 게이트웨이 + Vite 동시 기동 → http://localhost:5173
```

`node_modules/` 와 `dist/` 는 커밋하지 않는다(`.gitignore`).

## 통합되면

통합 저장소에서는 이 앱이 `visualization/web-dashboard` 에 있다. 그때 이 디렉터리는
지우고 그쪽을 직접 참조한다 — 사본을 두 곳에 남기면 언젠가 어긋난다.

## `data_stream/` 을 왜 여기 두나 (2026-11-20)

역할이 갈렸다. **입력과 추론은 그쪽이 이미 완성했고**, 이 저장소가 더하는 것은 그 위의
MLOps 다 — 모델을 컨테이너로 싸서 여러 노드에 배정·배포·롤백하는 일. 백엔드 노트북
하나에 둘이 함께 도는 구성이므로, `git pull` 한 번에 둘 다 오도록 **코드만 복사**해
두었다(히스토리는 251MB 이고 작업 트리는 1.2MB 다).

규칙은 다른 벤더 트리와 같다 — **내용을 고치지 않는다.** 고쳐야 할 이유가 생기면
상위 저장소에 요청하고, 여기 사본을 그 커밋으로 다시 맞춘다.

우리 쪽에서 이 트리를 부르는 자리는 셋이고 전부 `PD_DATA_STREAM` 으로 자리를 푼다 —
`tools/hazard_card.py` · `tools/label_review/draft_vision.py` · `tools/label_review/propagate.py`.

**라이선스가 아직 없다.** 상위 저장소는 public 이지만 `LICENSE` 파일이 없어서, 기본
저작권 아래에 있다(= 명시적 허락 없이는 재배포 권리가 없다). 소유자가 같은 사람이므로
막는 것은 아니지만, **공개 배포 전에 상위 저장소에 라이선스를 정해야 한다.** 그 전까지
이 디렉터리는 배포물에서 뺀다(`.dockerignore` · `MANIFEST.in`).

### 공개 검사에서 벤더 트리를 빼는 이유

`tests/test_publishable_surface.py` 의 **홈 경로·개인 메일** 검사는 벤더 트리를 보지
않는다. 그 안에는 `/home/khw67/data_stream/models/…` 처럼 만든 쪽 기계의 경로가 있고
(`vision/vision_config.yaml`), 우리는 그것을 **고칠 수 없다** — 고치는 순간 사본이
상위와 달라진다. 고칠 수 없는 것을 실패로 두면 시험이 무시된다. 대신 그 사실을 여기
적어 두고, 받는 쪽은 자기 기계의 자리로 그 설정을 바꾼다(그쪽 `배포_가이드.md`).
비밀값·비공개 트리 검사는 **벤더 트리에도 그대로 적용된다** — 그것은 고칠 수 없는
것이 아니라 애초에 들어오면 안 되는 것이다.
