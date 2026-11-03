# third_party/ — 다른 파트에서 **그대로 복사해 온** 것

여기 있는 것은 우리가 만든 코드가 아니다. 왜 두는지와 어디서 왔는지를 적어 두고,
**내용을 고치지 않는다** — 고쳐야 할 이유가 생기면 원본 쪽에 요청하는 것이 순서다.

| 디렉터리 | 무엇 | 출처 | 라이선스 |
|---|---|---|---|
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
