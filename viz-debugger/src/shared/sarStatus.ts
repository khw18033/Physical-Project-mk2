/**
 * src/shared/sarStatus.ts (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **드론 SAR 패스 실행기의 마지막 보고.** 받는 쪽(`physical/PhysicalClient.ts` → `sarFeed.ts`)이 밀어 넣고
 * 그리는 쪽(`src/sar/`)은 여기만 읽는다 — `deviceTelemetry.ts` 와 같은 모양이고 같은 이유다.
 *
 * 장비 상태 표(`stateRows`)에 섞지 않는다. 그 표는 1Hz `state` 본문을 줄로 바꾸는 것이고, 패스 기록·계획처럼
 * 배열과 묶음이 많은 이 보고를 줄로 펴면 읽을 수 없다.
 */

import { useSyncExternalStore } from 'react';

export type SarState =
  | 'idle' | 'preflight' | 'transit' | 'gap' | 'accel' | 'capture' | 'decel' | 'returning'
  | 'done' | 'incomplete' | 'aborted' | 'failed';

/** 끝난 상태. 이때는 새 임무를 시작할 수 있다. */
export const SAR_FINISHED: readonly SarState[] = ['idle', 'done', 'incomplete', 'aborted', 'failed'];

export type SarPassRecord = {
  passNo: number;
  /** 드론의 `time.time()`. **우리 시계가 아니다.** */
  startUnix: number | null;
  endUnix: number | null;
  durationS: number | null;
  captured: boolean;
  meanSpeedMps: number | null;
  maxSpeedErrMps: number | null;
  maxCrossTrackM: number | null;
  maxAltErrM: number | null;
  maxHeadingErrDeg: number | null;
  alongAtStartM: number | null;
  /** 같은 순간의 FC(GPS) 시각 — `.ulg` 와 맞출 때 쓴다. 시계 오차를 몰랐으면 null. */
  fcStartUnix: number | null;
  fcEndUnix: number | null;
  /** 캡처 중 가장 나빴던 GPS fix (`RTK_FIXED` 가 아니었던 순간이 있었는가). */
  worstFix: string | null;
  /** 품질 판정 — 무효면 드론이 그 자리에서 다시 난다. null 은 아직 판정 전. */
  valid: boolean | null;
  reasons: readonly string[];
  /** 레이더 확인(CAP_ACK): 실제 기록 시작 · 멈춤과 지연. 레이더가 확인을 안 주면 null. */
  ackStartUnix: number | null;
  ackEndUnix: number | null;
  ackOnLatencyS: number | null;
  /** 이 패스에 쓴 선행 트리거(초)와 가속 구간(m). 둘 다 드론이 배워서 늘린다. */
  capLeadS: number | null;
  leadInM: number | null;
  /** 실제 기록이 선 위 어디서 어디까지였나(m). 목표는 0 ~ 구간 길이. */
  effStartAlongM: number | null;
  effEndAlongM: number | null;
  trajCsv: string | null;
  metaJson: string | null;
  note: string | null;
};

export type SarStatus = {
  deviceId: string;
  state: SarState;
  passNo: number;
  passesTotal: number | null;
  /** CAP_ON 파일이 지금 있는가 — 드론이 직접 확인한 값이다. */
  capturing: boolean;
  plan: {
    startLat: number | null; startLon: number | null; endLat: number | null; endLon: number | null;
    altM: number | null; speedMps: number | null; passes: number | null; gapS: number | null;
    leadInM: number | null; lengthM: number | null; headingDeg: number | null; requireRtk: boolean;
  } | null;
  live: {
    groundSpeedMps: number | null; altRelM: number | null; yawDeg: number | null; headingErrDeg: number | null;
    alongM: number | null; crossTrackM: number | null; gpsFix: string | null; flightMode: string | null;
  } | null;
  passes: readonly SarPassRecord[];
  /** 유효 패스 수와 허용된 최대 시도 수(필요 + 재비행). */
  validPasses: number | null;
  maxAttempts: number | null;
  /** 레이더가 지금 「기록 중」이라고 확인하고 있나. null = 확인 경로가 없다. */
  capAck: boolean | null;
  ekf2HgtRef: number | null;
  /** 다음 패스 전에 드론이 어림한 배터리 — 남은 % · 다음 패스와 복귀에 쓸 % · 잰 소모율(%/s). */
  battery: { batteryPct: number; needPct: number; drainPctS: number } | null;
  /** 이 컴퓨터(파이) 시계 − FC(GPS) 시각, 초. null 은 모름. */
  clockOffsetS: number | null;
  /** 실행기가 남긴 주의 문장(시계를 모름 · 지난 CAP_ON 을 지움 등). 드론이 쓴 글자 그대로다. */
  warnings: readonly string[];
  message: string | null;
  error: string | null;
  deviceTime: number | null;
  timestamp: string | null;
};

export type SarReport = SarStatus & { origin: string; receivedAtMs: number };

let reports: Readonly<Record<string, SarReport>> = {};
const listeners = new Set<() => void>();

export function noteSarStatus(status: SarStatus, origin = '', atMs = Date.now()): void {
  reports = { ...reports, [status.deviceId]: { ...status, origin, receivedAtMs: atMs } };
  for (const listener of listeners) listener();
}

export function sarReports(): Readonly<Record<string, SarReport>> {
  return reports;
}

/** 보고가 이만큼 끊기면 「낡았다」로 적는다. 실행기는 0.5초마다 보낸다. */
export const SAR_STALE_MS = 5_000;

export function isSarStale(report: SarReport, nowMs = Date.now()): boolean {
  return nowMs - report.receivedAtMs > SAR_STALE_MS;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useSarReports(): Readonly<Record<string, SarReport>> {
  return useSyncExternalStore(subscribe, sarReports, sarReports);
}

export function resetSarStatus(): void {
  reports = {};
  for (const listener of listeners) listener();
}
