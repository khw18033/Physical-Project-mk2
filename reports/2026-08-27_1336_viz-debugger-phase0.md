# 가시화 디버거 0단계 완료 보고

**작업일**: 2026-08-27
**기준 커밋**: `605eb73`
**범위**: 새 골격, 통신·데이터 유틸 이식, 3계층 계약 초안, 어댑터 프로파일, 0단계 검증

## 결과 요약

- `viz-debugger/`를 새로 만들었고 `web-dashboard`와 겹치지 않는 Vite 5174 / 목 게이트웨이 8790 포트를 사용한다.
- 화면은 빈 본문과 `목 게이트웨이 연결` 배너만 둬 1단계 화면 범위를 당겨오지 않았다.
- 이식한 `WsTransport`로 최초 연결, 게이트웨이 종료 후 재연결, 게이트웨이 재기동 후 기존 구독의 데이터 재수신을 자동 검증했다.
- 신규 계약 6종과 각 유효 예시 1건을 추가했다. 전체 계약 예시 26건이 `contracts/validate_examples.py`를 통과한다.
- 상위 계층 하드웨어 어휘 주입 2건(`motor_speed`, `joint_angle`)이 거부되는 것을 `verify:hierarchy`가 확인한다.
- 기존 주요 폴더의 파일은 수정하지 않았다. 예외적으로 명세에 따라 `contracts/`에는 신규 스키마·예시만 추가했다.

## 기준선 검증

### 작업 전

| 검증 | 결과 | 비고 |
|---|---|---|
| `verify:cache` | 통과 | 금지 채널 재생 0건 |
| `verify:pipeline` | 통과 | |
| `verify:mission-graph` | 통과 | |
| `verify:contract-roundtrip` | 실행환경 실패 | 샌드박스가 Node의 Python 하위 프로세스 생성을 막아 `no-python`으로 판정 |
| `verify:catalog-derived` | 통과 | |
| `typecheck` | 통과 | |
| `build` | 실행환경 실패 | esbuild 하위 프로세스 생성이 `spawn EPERM`으로 차단 |

작업 전 Git 상태는 깨끗했다. 두 실행환경 실패는 원본 기대값을 바꾸지 않고 완료 후 샌드박스 밖에서 같은 npm 명령으로 재확인했다.

### 완료 후

| 검증 | 결과 |
|---|---|
| 기존 `verify:cache` | 통과 |
| 기존 `verify:pipeline` | 통과 |
| 기존 `verify:mission-graph` | 통과 |
| 기존 `verify:contract-roundtrip` | 통과 |
| 기존 `verify:catalog-derived` | 통과 |
| 기존 `typecheck` | 통과 |
| 기존 `build` | 통과 |
| 신규 `validate_examples.py` | 통과 — 전체 26건, 실패 0건 |
| 신규 `verify:hierarchy` | 통과 — 의도적 경계 위반 2건 거부 포함 |
| 신규 `verify:adapter-swap` | 통과 — 1프로파일 스켈레톤 |
| 신규 `verify:transport` | 통과 — 재연결·구독 복원 포함 |
| 신규 `typecheck` / `build` | 통과 |
| 신규 `npm run dev` | 목 서버와 Vite 동시 기동 확인 |

완료 후 첫 기존 검증 묶음에서는 오래 실행 중이던 작업 전 목 서버의 이전 계획 진행 캐시 때문에 `verify:mission-graph`가 한 번 실패했다. 해당 서버를 종료하고 깨끗한 서버에서 7종 전체를 같은 순서로 다시 실행해 모두 통과했다.

## 이식 판단표 변경

- 기준 커밋 표기를 문서와 코드 주석 모두 `605eb73`으로 맞췄다.
- `src/transport/index.ts`는 기본 게이트웨이 포트를 8787에서 8790으로 바꿨으므로 무수정 이식이 아니라 개조 이식으로 옮겼다.
- `vite.config.ts`도 개발 서버 포트를 5173에서 5174로 바꿨으므로 개조 이식으로 옮겼다.
- `tsconfig.json`은 새 폴더에 같은 검사 규칙을 적용했으므로 무수정 쪽에 남겼다.

## 합의와 어긋나거나 확인할 지점

- 작업 프롬프트는 연결 상태가 `connected`가 된다고 표현하지만, 기준 커밋의 `ConnectionState` 실제 열거는 `open`이다. 이식 코드를 바꾸지 않기 위해 배너와 검증은 `open`을 사용했다. 상태 용어를 계약에서 통일할지는 1단계 전에 합의가 필요하다.
- 신규 스키마의 외부 `$ref`는 현재 각 최소 예시가 빈 하위 배열 또는 `null`이라 기존 검증기로 통과한다. 실제 중첩 임무 예시를 넣기 전에는 `validate_examples.py`의 로컬 스키마 레지스트리 지원 또는 번들 스키마 전략을 합의해야 한다. 기존 검증 스크립트는 0단계 제약 때문에 수정하지 않았다.

## 1단계로 넘길 미결 사항

- 실제 데이터가 들어 있는 완전 중첩 mission 예시와 로컬 `$ref` 해석 방식 확정
- 마일스톤·태스크·액션 아이템 모델 타입 및 append-only 기록 저장소 구현
- 두 번째 어댑터 프로파일이 들어올 때 `verify:adapter-swap`의 Git 기준선 비교를 실제 판정으로 활성화
- 화면 5종과 시점 되감기·실패 경로 격리는 1단계 이후 범위로 유지
