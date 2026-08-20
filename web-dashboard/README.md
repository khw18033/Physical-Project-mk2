# 가시화 대시보드 — 데이터 레이어 + 목 게이트웨이

다른 파트의 계약이 확정되기 전에도 **화면이 실제로 움직이게** 하기 위한 구성이다.
목 데이터는 브라우저 안에 있지 않고 **별도 프로세스의 WebSocket 서버**로 돌아간다.
진짜 백엔드 게이트웨이가 나오면 접속 주소만 바꿔 붙인다.

관련 요구사항: `VZ-I-01`~`03`, `VZ-I-11`, `VZ-U-01`, `VZ-C-03`~`05`
(`REQ-201`·`203`·`204`·`205`, `REQ-301`~`305`, `REQ-702`·`704`, `REQ-903`·`909`)

---

## 빠른 시작

```bash
cd web-dashboard
npm install
npm run dev          # 목 게이트웨이 + Vite 동시 기동
```

브라우저에서 **http://localhost:5173** 을 연다.
(Vite가 IPv6 localhost에 바인딩하므로 `127.0.0.1`이 아니라 `localhost`로 접속한다.)

따로 띄우려면:

```bash
npm run dev:mock     # 목 게이트웨이만 — ws://127.0.0.1:8787
npm run dev:web      # 프런트만
```

`npm install` 뒤 Vite가 `esbuild` 바이너리를 찾지 못하면 한 번만:

```bash
npm rebuild esbuild
```

> Node 22.6+ 필요 (목 게이트웨이를 `.ts` 그대로 실행한다). Node 24 LTS에서 확인했다.

### 접속 주소 바꾸기 — 실제 게이트웨이로 전환

`web-dashboard/.env.local` 에 두 줄이면 끝난다. 코드 변경은 없다.

```
VITE_GATEWAY_WS=ws://<백엔드-호스트>:<포트>
VITE_GATEWAY_HTTP=http://<백엔드-호스트>:<포트>
```

백엔드가 **논리 구독 대신 토픽 문자열 방식**을 고르면 `src/transport/` 폴더에
`TopicTransport.ts` 를 추가하고 `src/transport/index.ts` 의 팩토리 한 줄만 바꾼다.
`src/data/` 와 `src/views/` 는 한 줄도 건드리지 않는다.

---

## 시나리오 재생

상태 전이는 **재생해 봐야** 화면이 전이 순간에 맞는지 확인할 수 있다. 세 가지 방법:

**① 화면 하단 버튼** — 대시보드 아래 "시나리오 재생" 패널에서 클릭

**② CLI**

```bash
npm run scenario                    # 목록과 각 시나리오의 기대 동작 출력
npm run scenario -- sensor-surge
```

**③ HTTP**

```bash
curl -X POST http://127.0.0.1:8787/scenario/camera-silence
```

| 이름 | 무엇이 일어나는가 | 화면에서 볼 것 |
|---|---|---|
| `camera-silence` | camera-02 발행 중지 | **60초 뒤** 판단 불가 뱃지. `availability`만 `stale`이 되고 `device_status`는 `ok` 그대로 |
| `camera-resume` | camera-02 발행 재개 | 다음 재판정에서 정상 복귀 |
| `sensor-offline` | sensor-02 연결 두절 주입 | **즉시** 장애 전환(5초 주기를 기다리지 않는다) → 20초 뒤 자동 복구 |
| `sensor-surge` | sensor-01 수위 +0.62m 급변 | 평시 1분을 기다리지 않고 **즉시** 값 변경 + 이벤트 모드(1초 주기) 30초 유지 |
| `actuator-command` | 수문 개도 70% 명령 | 대기 → (ACK) → **동작 중(100ms 진행률)** → 완료 |
| `robot-idle` / `robot-mission` | robot-01 임무 토글 | 50ms(20Hz) ↔ 5초. 임무 중에도 리렌더는 초당 10회 이하 |

---

## 구조

```
web-dashboard/
├─ mock-gateway/            별도 프로세스 · Node + ws
│  ├─ config.ts             ★ 모든 주기 상수와 규모 가정이 여기 한 곳에
│  ├─ protocol.ts           와이어 계약 (봉투 · 구독 메시지)
│  ├─ registry.json         ★ 존재해야 할 목록 (미배포 대상 포함)
│  ├─ hub.ts                구독 매칭 · 마지막 값 캐시 · 상태 3층 조합 · stale 판정
│  ├─ devices.ts            가짜 장치들 (요구사항이 정한 실제 주기로 발행)
│  ├─ scenarios.ts          상태 전이 재생 스크립트
│  └─ server.ts             진입점 (WS + HTTP 같은 포트)
└─ src/
   ├─ transport/            ★ 전송 방식을 아는 유일한 폴더
   │  ├─ index.ts           출입구 + 접속 주소. 상위는 여기서만 import
   │  ├─ Transport.ts       상위가 보는 인터페이스 (WS·토픽 개념 없음)
   │  ├─ WsTransport.ts     WS 구현 + 재연결 + 구독 자동 복원
   │  └─ types.ts           봉투 · 상태 3층 타입
   ├─ data/
   │  ├─ store.ts           채널별 마지막 봉투 보관 (3층 원본 그대로)
   │  ├─ mergeScheduler.ts  ★ 렌더 병합 100ms 창
   │  ├─ statusModel.ts     3층 → 4종 파생 (판정이 아니라 파생)
   │  ├─ actuatorModel.ts   액추에이터 도메인 어휘 (3층과 별개)
   │  ├─ aggregation.ts     ★ 재집약 방지 검사
   │  ├─ summary.ts         구역 요약 5초 (오프라인 전이는 즉시)
   │  ├─ registry.ts        레지스트리 조회
   │  └─ hooks.ts           React 바인딩 (useSyncExternalStore만)
   └─ views/
      ├─ DeviceGrid.tsx     구역 장치 현황판 — 이번 범위의 전부
      └─ DeviceCard.tsx     카드 한 장
```

### 목 게이트웨이 엔드포인트

| 경로 | 용도 |
|---|---|
| `ws://127.0.0.1:8787` | 구독 · 데이터 푸시 · 역할 조회 · 시나리오 |
| `GET /registry` | 레지스트리 (VZ-I-03) |
| `GET /scenarios` | 시나리오 목록과 기대 동작 |
| `POST /scenario/:name` | 시나리오 재생 |
| `GET /health` | 서버 시각 · 접속 수 · stale 임계 · 규모 가정 |

---

## 지켜야 하는 규칙

이걸 어기면 실제 게이트웨이로 갈아탈 때 전부 다시 짜야 한다.

**1. `stale` 판정은 서버가 한다.**
클라이언트가 계산하면 사용자 PC 시계에 의존한다. 화면의 "최근 수신 N초 전"도
`envelope.ts - last_seen` 으로 구하는데 **둘 다 서버 시각**이다. `Date.now()`가
상태 판정에 쓰이는 코드는 잘못된 코드다.

**2. 상태를 단일 값으로 뭉치지 않는다.**
`device_status` / `availability` / `deployment` 3층을 원본 그대로 보관하고
표시값(정상/장애/미배포/판단 불가)은 `deriveDisplayStatus()`로 **파생**시킨다.
뭉치면 "연결은 됐는데 기기가 fault"와 "값이 오래됨"을 표현할 수 없다.

**3. 전송 방식은 `src/transport/` 밖으로 새지 않는다.**
`src/data/`·`src/views/`에 `WebSocket`이나 토픽 문자열이 나타나면 격리가 깨진 것이다.

**4. 데이터는 전량 받되 화면 반영만 병합한다.**
병합은 **그리는 부하**만 줄인다. 받는 양은 그대로다. 대상이 늘어 수신 대역이
문제가 되면 구독 단계에서 좁혀야 한다 → `VZ-I-11`의 `scope`.

---

## 계약에 자리만 열어 둔 것 (값은 고정, **경로는 살아 있다**)

자리를 열어놓고 코드가 무시하면 나중에 결국 같은 공사를 하게 되므로,
셋 다 실제로 왕복시킨다.

| 필드 | 어디에 | 현 값 | 확인 방법 |
|---|---|---|---|
| `scope` (VZ-I-11) | 구독 요청 + 봉투 | `"all"` | 개발자 도구 → WS 프레임에서 `subscribe`와 모든 `data` 봉투 |
| `aggregation` (VZ-C-03) | 봉투 | `"raw"` / 집약값은 `{mode:"aggregated", layer:"edge", …}` | `edge-node-a`의 `metrics` 봉투(15초 주기) |
| 권한 `scope` (VZ-C-04) | 역할 응답 | `["*"]` | 화면 하단 "계약 자리 확인" 칩 |

**재집약 검사**: 화면 하단 "집약값에 평균 적용 시도" 버튼을 누르면 개발 모드에서
콘솔 경고가 뜨고 계산 결과는 `null`이 된다. 집약 연산은 반드시 `guardedMean()` /
`guardedSum()` 을 거치게 해서 검사를 빠뜨릴 수 없게 만들었다.

---

## 규모 가정 (VZ-C-05 — 정식 숫자는 팀 합의 대기)

`mock-gateway/config.ts` 의 `SCALE_ASSUMPTIONS`:

| 항목 | 값 |
|---|---|
| 구역 수 | 1 |
| 동시 표시 대상 상한 | 20 |
| 동시 관제 사용자 | 1 |

현재 모든 주기·구독 방식이 이 전제 위에서 산정되어 있다. 부하 한계를 실측할 때
이 값이 기준선이 된다. 이 규모를 넘기면 `VZ-I-11`(구독 범위 한정)과
`VZ-C-03`(집약 계층)을 실제로 켜야 한다.

---

## 이번 범위에 **없는** 것

- **실제 제어 명령 발행 경로** — 백엔드 시트가 비어 있다. 액추에이터는 목 서버 안에서만 왕복한다.
- **감사 필드** — `input.mode`·`decision.source` 두 축 분리를 백엔드에 요청 중이라 유동적이다.
- **좌표 변환** — 로컬→글로벌 변환과 축 변환은 백엔드 책임이다. 목 서버가 이미 변환된 전역 좌표를 준다.
- **프레임 참조·영상 스트림** — 범위 밖. 카메라는 메타데이터만 발행한다.
- 트윈 3D 렌더, 추상화 계층 뷰, 노드 편집기, 음성·LLM — 다음 범위.

`prototype.html` 은 이관 전 단일 파일 프로토타입이다. 참고용으로 남겨 두었으며 코드는 재사용하지 않았다.
