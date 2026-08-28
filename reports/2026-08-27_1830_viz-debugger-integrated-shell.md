# viz-debugger 통합 셸·공유 계층 구현

## 결과

`viz-debugger/`를 그릇으로 삼아 6탭 통합 셸을 만들었다. 사용자 요청에 따라 탭① 「임무 설계 및 디버깅」을 첫 번째에 배치했으며 기존 1단계 화면 다섯 개를 그대로 유지한다. 탭②~⑥은 모두 `이식 예정 — 기존 프로토타입에서 동작 중` placeholder다. `web-dashboard/`에는 코드 변경이 없다.

작업 후 렌더 기준 화면: `reports/assets/2026-08-27_통합앱_6탭_기준화면.png`

## 기준선과 완료 후 검증

### 작업 전

- `web-dashboard`: cache, pipeline, mission-graph는 통과했다. contract-roundtrip은 샌드박스에서 Node 자식 `python` 탐색이 막혀 중단됐다.
- `viz-debugger`: hierarchy, adapter-swap은 통과했다. transport는 샌드박스의 자식 프로세스 `EPERM`으로 중단됐다.
- 작업 트리에는 사용자 소유의 추적되지 않은 `가시화_요구사항_쉬운설명_NEW.pdf` 한 개가 있었고 건드리지 않았다.

### 작업 후

- `web-dashboard`: `verify:cache`, `verify:pipeline`, `verify:mission-graph`, `verify:contract-roundtrip`, `verify:catalog-derived`, `typecheck`, `build` 통과.
  - mission-graph는 8787 목 서버를 깨끗하게 재기동한 뒤 승인 전 진행 0건, 진행 이벤트 8건을 확인했다.
  - 빌드: JS 307.17 kB (gzip 96.09 kB).
- `viz-debugger`: 기존 `verify:hierarchy`, `verify:adapter-swap`, `verify:transport`, `verify:scenario`, `verify:layout`, `typecheck`, `build` 통과.
- 신규 `verify:single-egress`: 앱 명령 출구 1개 확인. 두 번째 `.publishCommand()`를 가상 주입한 음성 대조군도 2개로 검출함.
- 신규 `verify:standalone`: 단독 빌드 후 의존 그래프 17개 파일에서 `shell/` 및 다른 탭 import 0건 확인.
- `git diff --check` 오류 없음. `git diff -- web-dashboard` 내용 없음.

## 공유 계층 경계

셸은 `src/shell/AppShell.tsx`에서 탭 상태, 상단 임무 제어, 이력, 통합 알림만 소유한다. 탭① 컴포넌트는 `src/main.tsx`에 남겨 기존 화면 내부 상태·DAG·재생·모달을 계속 소유한다. 탭 전환은 탭①을 언마운트하지 않고 CSS로 표시만 바꾸므로 배정, 화면, 그래프 위치 상태와 구독 생명주기가 유지된다.

탭①에서 꺼낸 것은 다음과 같다.

- 명령 발행: `src/shared/commandEgress.ts`만 `getTransport().publishCommand()`를 호출한다. 공통 바와 액션 모달은 `issueCommand()`만 호출한다.
- 레지스트리 원천: `src/shared/registry.ts`가 탭① 하드웨어 배정 풀과 향후 탭②의 공통 원천 경계를 만든다.
- 알림: `src/shared/notifications.ts`에서 외부 AI 실패(VZ-I-10), 임무 생성 실패(F15), 명령 실패를 한 목록으로 합친다.
- 권한·표기·자체 관측: `permissions.ts`, `presentation.ts`, `observability.ts`에 탭 비종속 경계를 만들었다.
- 상태 어휘: `DeviceDisplayStatus` 4종과 `MissionTaskStatus` 8종을 별도 타입으로 선언했다.

store는 합치지 않았다. `LatestValueStore`는 향후 탭②~⑥의 채널별 최신값을, `TraceStore`는 탭①의 기록 열을 맡는다. 전송 연결은 기존 singleton transport 하나를 공유한다.

## 단독 빌드

- 명령: `npm run build:standalone`
- 산출 위치: `viz-debugger/dist-standalone/`
- JS: 217.17 kB (gzip 69.32 kB)
- CSS: 7.52 kB (gzip 2.37 kB)
- 통합 앱 JS 참고값: 220.44 kB (gzip 70.45 kB)

## 남은 탭 5개 이식과 걸림돌

1. 구역 현황판: 장치 4상태를 탭①의 태스크 8상태와 섞지 않고 `LatestValueStore`에 연결해야 한다.
2. 제어 패널: 원본의 발행 코드를 직접 가져오지 말고 `issueCommand()`로 치환해야 한다.
3. 지표 조회: 하드웨어 export 60초와 15초 질의의 반복점을 구분하고 지표별 원천 주기를 표시해야 한다.
4. 영상 오버레이: 메시지/관측 평면과 별도인 미디어 경로를 유지해야 한다.
5. 파이프라인 편집기: 데이터 파이프라인 모드만 이식하고 구 임무 관제 모드는 제외한다. 동결·시연용이므로 기능을 추가하지 않는다.

## 요구사항정의서 §3.1 대조

구조와 경계는 §3.1과 일치한다. 단, 탭 순서는 후속 사용자 요청에 따라 임무 디버거를 ⑥에서 ①로 옮겼다. 따라서 실제 탭②~⑥ 이식은 10월 범위에 남는다.
