# 2026-08-25 15:15 — Phase 1 정합 종료 · Phase 2 판단/알림/계층 뷰 구현

**직전 보고서**: `2026-08-25_1506_stt-model-comparison-lab.md`
**기준**: `구현계획서.md` Phase 1·2 · `작업계획_260824.md` §3
**범위**: 문서 원본 정합 상태 확정 + `VZ-I-08`·`VZ-I-10`·`VZ-O-04`·`VZ-U-03`

## 결과

계획 순서대로 Phase 1의 활성 Markdown 정합을 먼저 닫고, Phase 2의 잔여 표시 4건을
`web-dashboard`에 구현했다. 구현 완료 수는 **22/33(67%) → 26/33(79%)**, 웹 화면은
5개에서 6개가 됐다.

Phase 1은 Mermaid와 Markdown 원본 기준으로 `device_id`, 업무·관측·미디어 3평면,
인지 출처 분리가 일치한다. 쉬운 설명 PDF도 재생성돼 있다. T3·DF-1 PNG와 프로토타입
설명서 PDF는 이 환경에 Mermaid/PDF 조판 도구가 없어 생성하지 않았으며, 구판은 이미
`_archive`에 격리돼 있다. 원본과 생성물을 섞어 현행으로 오인하지 않도록 계획서에 이
상태를 명시했다.

## Phase 2 구현

### VZ-I-08 — 위험도 상태와 근거

`risk_state` 채널에 평시·관찰·경보·복구, 0~100 점수, 기여 근거, 권고 조치, 판정 시각을
분리해 실었다. 화면은 이 값을 다시 계산하지 않고 그대로 표시한다. 목 게이트웨이에서
네 단계 전이를 즉시 재생할 수 있다.

위험 상태를 기존 재접속 캐시에 추가하지 않았다. `BE-T-06`이 허용한 캐시 7개 채널을
임의로 넓히면 상대 계약과 어긋나기 때문이다. 대신 판정 주체가 현재값을 5초마다 다시
발행하고 단계가 바뀌는 순간에는 즉시 발행한다.

### VZ-I-10 — AI 실패 즉시 알림

`ai_failure`는 컴포넌트, 모델 버전, 입력 참조, 오류 코드, 상세 사유, 발생 시각을 담는다.
지표 질의와 분리된 WS 이벤트로 도착 즉시 표시한다. 실패 이벤트는 비캐시다. 재접속 때
과거 실패가 방금 발생한 경보처럼 다시 울리는 것을 막고, 과거 이력은 별도 조회 경로의
책임으로 남긴다.

### VZ-O-04 — 자체 관측 지표

브라우저가 받은 봉투의 서버 시각과 적용 시각 차이를 수집해 60초 창마다 건수·평균·최대
지연을 `/observability/client-metrics`에 발행한다. 목 게이트웨이는 수신 실물을 `/health`에
노출한다. 실제 배치에서는 이 HTTP 대체 경로를 OTel Collector 경로로 교체하면 된다.

### VZ-U-03 — 추상화 계층 뷰

`판단·알림` 탭에 세 깊이를 구현했다.

| 계층 | 표시 |
|---|---|
| 결심자 | 위험 단계·점수·권고 조치 |
| 운영자 | 판단 근거·기여도와 대상별 상태 |
| 개발자 | 위 내용과 원본 봉투·집약 표기·시각·품질 |

탭과 계층을 바꿔도 데이터 레이어는 앱 수명 동안 한 번만 구독한다. 공간 드릴다운과
추상화 축을 섞지 않고, 같은 원본의 표시 깊이만 바꾼다.

## 산출물

| 파일 | 내용 |
|---|---|
| `mock-gateway/protocol.ts` · `src/transport/types.ts` | 위험도·AI 실패 와이어 타입 |
| `mock-gateway/config.ts` | 두 채널의 명시적 비캐시 정책 |
| `mock-gateway/server.ts` | 위험도/실패 발생, 자체 지표 수신·점검 경로 |
| `src/data/store.ts` | 두 채널 원본 봉투 보존과 즉시 반영 |
| `src/data/selfObservability.ts` | 60초 자체 처리 지연 집계·발행 |
| `src/views/InsightView.tsx` | 위험도·실패·세 추상화 계층 화면 |
| `src/App.tsx` · `src/views/styles.css` | 여섯 번째 탭과 표현 |
| 계획·현황·README | 26/33, 화면 6개, Phase 2 완료 반영 |

## 검증

```text
npm.cmd run typecheck       통과
npm.cmd run build           통과 · Vite 59 modules · JS 286.74 kB
npm.cmd run verify:cache    통과
  스냅샷 20건
  금지 채널 재생 0건
  허용 밖 채널 0건
  cache violations 0건
```

HTTP 실물 검증:

```text
POST /insight/risk-alert                    200
POST /insight/ai-failure                    200
POST /observability/client-metrics          202
/health client_metrics.received             1
/health latest.source                       web-dashboard-test
```

첫 구현에서는 `risk_state`를 캐시에 넣었고 캐시 회귀 검사가 이를 허용 목록 밖 채널로
잡아 실패했다. 정책을 비캐시+주기 재발행으로 바꾼 뒤 전체 검증이 통과했다. 검증을 새
채널에 맞춰 느슨하게 바꾸지 않고 기존 확정 계약을 보존한 것이 핵심이다.

## 다음 단계와 대기 조건

계획상 다음은 Phase 3 `VZ-L-01`~`04` 음성·LLM 4건이다. STT 실험 하네스는 준비됐지만
운영 구현은 다음 네 합의가 필요하다.

1. `AI-C-09 task_type=intent_parse` 호출 주체
2. 의도 해석 결과 스키마 소유자와 필드
3. GenAI provider 부재 시 비-GenAI 경로 또는 기능 비활성 정책
4. `DISABLED`·`DEGRADED` capability 상태의 가시화 전달 경로

이 값들을 임의로 고정하면 실제 AI·백엔드 계약과 다시 어긋나므로 Phase 3은 합의 전까지
구현 대기 상태를 유지한다.
