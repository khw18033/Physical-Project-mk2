/**
 * src/physical/scanDetectRun.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S3)
 *
 * **새 흐름(`robotFlow: 'scan-detect'`)의 순서.** 계획서 §2-2 · §2-3 그대로다.
 *
 * ```
 * T-A0  prepare → status 폴링(ready, 60초)          ┐ 둘 다 끝나야 돈다
 * T-A2  시작 방위(장치가 주면, 못 주면 모름)        ┘
 * T-A3  mark(0) → [turn 45 → 완료 → mark(45)] ×7 → turn 45 → 완료   (마지막 회전 뒤 mark 없음)
 * T-A5  finish → result 폴링(done | failed, 30초)
 * ```
 *
 * - `mark` 는 **해당 turn 의 완료 응답 뒤에만** 나간다. 완료가 안 오면(시간 초과 · 거절) 멈춘다 — 로봇이 어디를
 *   보는지 모르는 채로 다음 각도를 표시하면 안 된다.
 * - `mark` 가 「프레임 없음」이면 그 각도만 비고 회전은 계속한다.
 * - 정지는 매 걸음 앞에서 본다. 멈추면 `cancel` 을 보내고 더 아무것도 안 낸다.
 *
 * **순수한 순서 제어다** — 창구 · 회전 · 방위 · 노드 칠하기 · 시계를 전부 받는다(`ScanRunDeps`). 화면 쪽 연결은
 * `scanDetectLink.ts` 가 하고, 검사(`verify:scan-detect`)는 가짜 창구 + 가짜 회전으로 이 함수를 그대로 돈다.
 */

import type { TaskStatus } from '../model/types.ts';
import type { ScanCall, ScanClient } from '../detect/scan/ScanClient.ts';
import type { ScanEvent, ScanStage } from '../detect/scan/scanStore.ts';
import type { ScanResult, ScanTarget } from '../detect/scan/types.ts';

export const SCAN_PREPARE_LIMIT_MS = 60_000;
export const SCAN_RESULT_LIMIT_MS = 30_000;
export const SCAN_POLL_MS = 1000;

export type ScanRunSpec = {
  scanId: string;
  missionId: string;
  device: string;
  target: ScanTarget;
  query: string | null;
  queryKo: string | null;
  /** 번역을 버린 사유(261124) — 깨진 번역이라 query 를 비우고 query_ko 만 보냈다. 없으면 null. */
  queryNote?: string | null;
  steps: number;
  stepDeg: number;
  prepareLimitMs?: number;
  resultLimitMs?: number;
  pollMs?: number;
};

/** data_stream 에 낸 요청 한 건 — 명령 기록에 남긴다(노드는 T-A0 · T-A4-n · T-A5). */
export type ScanCallRecord = {
  taskId: string;
  call: 'prepare' | 'mark' | 'finish' | 'cancel';
  body: Record<string, unknown>;
  ok: boolean;
  answer: string;
  angleIndex?: number;
};

export type TurnOutcome = { ok: true } | { ok: false; reason: string };

export type ScanRunDeps = {
  client: ScanClient;
  /** `turn` 하나를 보내고 **완료 응답까지** 기다린다. */
  turn(deg: number, angleIndex: number): Promise<TurnOutcome>;
  /** 시작 방위를 기다린다(T-A2). 못 주는 장치면 null. */
  startHeading(): Promise<number | null>;
  /** 지금 방위. 못 주면 null. */
  heading(): number | null;
  /** 노드 칠하기. */
  emit(taskId: string, status: TaskStatus, payload?: Record<string, unknown>): void;
  /** 상태 저장소로 가는 사건. */
  event(event: ScanEvent): void;
  record(entry: ScanCallRecord): void;
  stopped(): boolean;
  sleep(ms: number): Promise<void>;
  now(): number;
};

export type ScanRunOutcome =
  | { ok: true; result: ScanResult; headingStartDeg: number | null; headingEndDeg: number | null }
  | { ok: false; stage: ScanStage; code: string; detail: string };

/** 각도 칸 노드 이름 — 옛 흐름과 같다. */
export const angleTaskId = (index: number) => `T-A4-${index}`;

const describe = <T>(call: ScanCall<T>, ok: (value: T) => string): string => (call.ok ? ok(call.value) : `${call.code} ${call.detail}`);

export async function runScanDetect(spec: ScanRunSpec, deps: ScanRunDeps): Promise<ScanRunOutcome> {
  const { client } = deps;
  const scanId = spec.scanId;
  const pollMs = spec.pollMs ?? SCAN_POLL_MS;

  const failed = (stage: ScanStage, code: string, detail: string, taskId: string): ScanRunOutcome => {
    deps.event({ kind: 'fail', scanId, failure: { stage, code, detail } });
    deps.emit(taskId, 'failed', { stage, code, detail });
    return { ok: false, stage, code, detail };
  };
  const stoppedNow = async (): Promise<ScanRunOutcome | null> => {
    if (!deps.stopped()) return null;
    const answer = await client.cancel(scanId);
    deps.record({ taskId: 'T-A0', call: 'cancel', body: { scan_id: scanId }, ok: answer.ok, answer: describe(answer, (v) => v.state) });
    deps.event({ kind: 'cancel', scanId });
    return { ok: false, stage: 'turn', code: 'stopped', detail: '' };
  };

  deps.event({
    kind: 'begin', scanId, missionId: spec.missionId, device: spec.device, base: client.base, target: spec.target,
    query: spec.query, queryKo: spec.queryKo, queryNote: spec.queryNote ?? null, steps: spec.steps, stepDeg: spec.stepDeg,
  });

  // ── T-A0 준비 · T-A2 방위 ───────────────────────────────────────────
  deps.emit('T-A0', 'running', { device: spec.device, target: spec.target, query: spec.query, query_ko: spec.queryKo, base: client.base });
  const body = {
    scan_id: scanId, device: spec.device, target: spec.target, query: spec.query, query_ko: spec.queryKo,
    steps: spec.steps, step_deg: spec.stepDeg,
  };
  const headingPromise = deps.startHeading();
  const prepared = await client.prepare(body);
  deps.record({ taskId: 'T-A0', call: 'prepare', body, ok: prepared.ok, answer: describe(prepared, (v) => `${v.state}${v.error ? ` ${v.error}` : ''}`) });
  if (!prepared.ok) return failed('prepare', prepared.code, prepared.busyScanId ?? prepared.detail, 'T-A0');
  deps.event({ kind: 'prepare', scanId, answer: prepared.value });
  let state = prepared.value.state;
  let error = prepared.value.error;
  const prepareUntil = deps.now() + (spec.prepareLimitMs ?? SCAN_PREPARE_LIMIT_MS);
  while (state === 'loading') {
    const stop = await stoppedNow();
    if (stop !== null) return stop;
    if (deps.now() >= prepareUntil) return failed('prepare', 'timeout', `${spec.prepareLimitMs ?? SCAN_PREPARE_LIMIT_MS}ms`, 'T-A0');
    await deps.sleep(pollMs);
    const status = await client.status(scanId);
    if (!status.ok) continue; // 한 번 못 받은 것은 다음 폴링이 메운다 — 한도가 끊는다
    deps.event({ kind: 'status', scanId, answer: status.value });
    state = status.value.state;
    error = status.value.error;
  }
  if (state !== 'ready') return failed('prepare', error ?? state, state, 'T-A0');
  deps.emit('T-A0', 'done', { stream: prepared.value.stream, targets: prepared.value.targets });

  const headingStartDeg = await headingPromise;
  deps.event({ kind: 'heading', scanId, which: 'start', deg: headingStartDeg });

  // ── T-A3 회전 · T-A4-n 각도 표시 ─────────────────────────────────────
  deps.emit('T-A3', 'running', { steps: spec.steps, step_deg: spec.stepDeg });
  for (let index = 0; index < spec.steps; index += 1) {
    const stop = await stoppedNow();
    if (stop !== null) return stop;
    const deg = index * spec.stepDeg;
    const taskId = angleTaskId(index);
    deps.emit(taskId, 'running', { rotation_deg: deg });
    const mark = await client.mark(scanId, deg);
    deps.record({
      taskId, call: 'mark', body: { scan_id: scanId, rotation_deg: deg }, ok: mark.ok, angleIndex: index,
      answer: describe(mark, (v) => (v.frame_captured ? `frame ${v.frame_n}` : 'no frame')),
    });
    deps.event({ kind: 'mark', scanId, index, answer: mark.ok ? mark.value : null });
    // 표시 못 함 · 프레임 없음은 그 각도만 빈다 — 회전은 계속한다(계획서 §2-3).
    deps.emit(taskId, mark.ok && mark.value.frame_captured ? 'done' : 'failed', mark.ok
      ? { rotation_deg: deg, frame_n: mark.value.frame_n, frame_captured: mark.value.frame_captured }
      : { rotation_deg: deg, error: `${mark.code} ${mark.detail}` });

    const stopBeforeTurn = await stoppedNow();
    if (stopBeforeTurn !== null) return stopBeforeTurn;
    const turned = await deps.turn(spec.stepDeg, index);
    if (!turned.ok) return failed('turn', 'turn_failed', turned.reason, 'T-A3');
  }
  deps.emit('T-A3', 'done', {});
  const headingEndDeg = deps.heading();
  deps.event({ kind: 'heading', scanId, which: 'end', deg: headingEndDeg });

  // ── T-A5 산출 ───────────────────────────────────────────────────────
  const stopBeforeFinish = await stoppedNow();
  if (stopBeforeFinish !== null) return stopBeforeFinish;
  deps.emit('T-A5', 'running', {});
  const finished = await client.finish(scanId);
  deps.record({ taskId: 'T-A5', call: 'finish', body: { scan_id: scanId }, ok: finished.ok, answer: describe(finished, (v) => v.state) });
  if (!finished.ok) return failed('finish', finished.code, finished.detail, 'T-A5');
  const resultUntil = deps.now() + (spec.resultLimitMs ?? SCAN_RESULT_LIMIT_MS);
  for (;;) {
    const stop = await stoppedNow();
    if (stop !== null) return stop;
    if (deps.now() >= resultUntil) return failed('result', 'timeout', `${spec.resultLimitMs ?? SCAN_RESULT_LIMIT_MS}ms`, 'T-A5');
    await deps.sleep(pollMs);
    const answer = await client.result(scanId);
    if (!answer.ok) {
      if (answer.code === 'shape') return failed('result', 'shape', answer.detail, 'T-A5');
      continue;
    }
    const result = answer.value;
    if (result.scan_id !== scanId) continue; // 지난 판의 답 — 버린다
    if (result.state === 'running' || result.state === 'collecting') continue;
    deps.event({ kind: 'result', scanId, result });
    if (result.state !== 'done') return failed('result', result.error ?? result.state, result.reason, 'T-A5');
    return { ok: true, result, headingStartDeg, headingEndDeg };
  }
}

/**
 * 결과를 받은 뒤의 판정 — 판 도중 프로필이 바뀌었으면(결과의 번호 ≠ ready 때 번호) 그 결과로 움직이지 않는다
 * (요청 문서 §7). 둘 중 하나라도 모르면 따지지 않는다.
 */
export function profileChanged(readyVersion: number | null, result: ScanResult): boolean {
  return readyVersion !== null && result.profile_version !== null && readyVersion !== result.profile_version;
}
