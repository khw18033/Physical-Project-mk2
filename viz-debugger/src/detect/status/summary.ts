/**
 * src/detect/status/summary.ts (261124 신설 — 객체 탐지 상태판)
 *
 * **포트마다 카드 한 장.** 「기능」 판 자리에 서는 객체 탐지 상태판이 그리는 줄을 계산한다. 순수 함수다 —
 * 값은 `src/vision/store.ts` 가 1~2초마다 받은 `/health` 이고, 여기서는 세고 가르고 줄 세우기만 한다.
 *
 * ## 판은 장비 목록을 보지 않는다
 *
 * 카드는 **연결 관리의 포트 줄**에서 나온다(`visionBases()`). 그래서 하드웨어가 0대여도 판이 그대로 뜬다(요구 3).
 * 장비는 오른쪽 위의 「→ go1-001」로만 붙는다 — 하드웨어 카드의 포트 묶음(`binding.ts`)을 거꾸로 읽은 것이다.
 *
 * ## 모델 수
 *
 * **살아 있는(`modelLive`) (포트, 모델) 쌍의 수**다. 같은 `targeted` 가 두 포트에서 돌면 2 로 센다 — 화면이 아는 것은
 * 포트마다의 결과뿐이고, 비전 프로세스가 몇 개인지는 모른다.
 *
 * 계획: `documents/작업프롬프트/작업프롬프트_탐지모델상태판_개발계획_261124.md` §3-1 · §3-2.
 */

import { modelLive, modelStale, type VisionModelSummary } from '../../vision/visionClient.ts';
import type { VisionSourceState } from '../../vision/store.ts';

/**
 * 카드의 상태 점.
 *   models   모델 결과가 들어온다 (초록)
 *   raw      원본만 들어오고 돌고 있는 모델이 없다 (회색)
 *   noVideo  `/health` 는 답하는데 원본이 안 들어온다 (노랑)
 *   waiting  아직 한 번도 못 받았다 (회색)
 *   down     `/health` 가 실패했다 — 옛 값이 있어도 이것이다 (빨강)
 */
export type DetectSourceState = 'models' | 'raw' | 'noVideo' | 'waiting' | 'down';

export type DetectSourceRow = {
  base: string;
  /** 서버가 밝힌 소스 이름, 모르면 null. */
  source: string | null;
  port: number | null;
  state: DetectSourceState;
  /** 살아 있는 모델 — 멎은 듯한 것(`modelStale`)도 든다. 이름 순. */
  live: readonly VisionModelSummary[];
  /** 모델별 처리 속도(장/초). */
  rate: Readonly<Record<string, number>>;
  frameRate: number | null;
  stateRate: number | null;
  /** 이 포트에 묶인 장비들(하드웨어 카드). 없으면 빈 배열. */
  devices: readonly string[];
  error: string | null;
  visionError: string | null;
  /** 스캔 창구가 판을 쥐고 있으면 그 번호. */
  busyScanId: string | null;
  /** 마지막으로 받은 시각(이 브라우저 시계). */
  receivedAtMs: number | null;
};

export type DetectTotals = {
  ports: number;
  /** `/health` 가 지금 답하는 포트. */
  connected: number;
  down: number;
  /** 살아 있는 (포트, 모델) 쌍. */
  models: number;
  /** `targeted` 가 살아 있는 포트. */
  targeted: number;
};

const ORDER: Record<DetectSourceState, number> = { models: 0, raw: 1, noVideo: 2, waiting: 3, down: 4 };

/** 서버의 연결 문장이 끊김을 말하는가 — 서버가 쓴 한국어 그대로다(「끊김 (…) — 다시 붙는 중」). */
const SAYS_CUT = /끊김|disconnected/i;

export function rowState(state: VisionSourceState | null): DetectSourceState {
  if (state === null || (state.health === null && state.error === null)) return 'waiting';
  if (state.error !== null) return 'down';
  const health = state.health;
  if (health === null) return 'waiting';
  if (health.models.some(modelLive)) return 'models';
  const frameRate = state.sourceRate?.frames ?? null;
  if (frameRate !== null) return frameRate > 0 ? 'raw' : 'noVideo';
  // 처음 한 번은 속도를 모른다 — 받은 장이 있고 서버가 끊겼다고 안 하면 원본이 오는 것으로 본다.
  return (health.frames ?? 0) > 0 && !(health.video !== null && SAYS_CUT.test(health.video)) ? 'raw' : 'noVideo';
}

/** 장비 → 포트 묶음을 포트 → 장비들로 뒤집는다. */
export function devicesByBase(bindings: Readonly<Record<string, string | null>>): Readonly<Record<string, readonly string[]>> {
  const out: Record<string, string[]> = {};
  for (const [device, base] of Object.entries(bindings)) {
    if (base === null) continue;
    (out[base] ??= []).push(device);
  }
  for (const list of Object.values(out)) list.sort();
  return out;
}

/** 카드 줄과 머리 숫자. 순서: 모델이 도는 것 → 원본만 → 원본 끊김 → 기다림 → 응답 없음, 같으면 연결 관리 순서. */
export function summarizeDetectSources(
  bases: readonly string[],
  sources: Readonly<Record<string, VisionSourceState>>,
  devices: Readonly<Record<string, readonly string[]>> = {},
): { rows: DetectSourceRow[]; totals: DetectTotals } {
  const rows = bases.map((base, index) => {
    const state = sources[base] ?? null;
    const health = state?.health ?? null;
    const row: DetectSourceRow = {
      base,
      source: health?.source ?? null,
      port: health?.port ?? null,
      state: rowState(state),
      live: (health?.models ?? []).filter(modelLive),
      rate: state?.rate ?? {},
      frameRate: state?.sourceRate?.frames ?? null,
      stateRate: state?.sourceRate?.states ?? null,
      devices: devices[base] ?? [],
      error: state?.error ?? null,
      visionError: health?.visionError ?? null,
      busyScanId: health?.scan?.busyScanId ?? null,
      receivedAtMs: state?.receivedAtMs ?? null,
    };
    return { row, index };
  });
  rows.sort((a, b) => ORDER[a.row.state] - ORDER[b.row.state] || a.index - b.index);
  const list = rows.map(({ row }) => row);
  return {
    rows: list,
    totals: {
      ports: list.length,
      connected: list.filter((row) => row.state !== 'down' && row.state !== 'waiting').length,
      down: list.filter((row) => row.state === 'down').length,
      models: list.reduce((sum, row) => sum + (row.state === 'down' ? 0 : row.live.length), 0),
      targeted: list.filter((row) => row.state !== 'down' && row.live.some((m) => m.model === TARGETED)).length,
    },
  };
}

/** 지정 클래스 탐지 모델 이름 (data_stream `vision_infer.py`). */
export const TARGETED = 'targeted';

/** 칩 색 — 멎은 듯하면 노랑. */
export function modelChipTone(model: VisionModelSummary): 'ok' | 'warn' {
  return modelStale(model) ? 'warn' : 'ok';
}
