/**
 * src/detect/scan/parse.ts (261123 신설 — 스캔 탐지를 data_stream 으로)
 *
 * **받은 JSON 을 검사해서 모양을 씌운다.** 타입만 씌우면 빠진 칸이 undefined 인 채 화면까지 간다
 * (옛 `detect/parse.ts` 와 같은 이유). 모양이 틀리면 null — 부르는 쪽이 「응답 모양이 다름」으로 멈춘다.
 * 이동을 정하는 칸(`best` 의 방위 · 거리 · `distance_valid`)은 특히 **지어내지 않는다.**
 */

import type {
  ScanBest, ScanCue, ScanFrameResult, ScanMarkAnswer, ScanPrepareAnswer, ScanResult, ScanState, ScanStatusAnswer, ScanTarget,
} from './types.ts';

const STATES: readonly ScanState[] = ['loading', 'ready', 'collecting', 'running', 'done', 'failed', 'cancelled'];
const TARGETS: readonly ScanTarget[] = ['door', 'box', 'object'];

type Obj = Record<string, unknown>;
const isObj = (value: unknown): value is Obj => value !== null && typeof value === 'object' && !Array.isArray(value);
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const state = (value: unknown): ScanState | null => (STATES.includes(value as ScanState) ? value as ScanState : null);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);

export function parsePrepare(body: unknown): ScanPrepareAnswer | null {
  if (!isObj(body)) return null;
  const scanId = str(body.scan_id);
  const st = state(body.state);
  if (scanId === null || st === null) return null;
  return { scan_id: scanId, state: st, stream: str(body.stream), model: str(body.model), targets: strings(body.targets), profile_version: num(body.profile_version), error: str(body.error) };
}

export function parseStatus(body: unknown): ScanStatusAnswer | null {
  if (!isObj(body)) return null;
  const scanId = str(body.scan_id);
  const st = state(body.state);
  if (scanId === null || st === null) return null;
  const angles = Array.isArray(body.angles_captured) ? body.angles_captured.map(num).filter((v): v is number => v !== null) : [];
  return { scan_id: scanId, state: st, angles_captured: angles, profile_version: num(body.profile_version), error: str(body.error) };
}

export function parseMark(body: unknown): ScanMarkAnswer | null {
  if (!isObj(body)) return null;
  const scanId = str(body.scan_id);
  const deg = num(body.rotation_deg);
  if (scanId === null || deg === null || typeof body.frame_captured !== 'boolean') return null;
  return { scan_id: scanId, rotation_deg: deg, frame_captured: body.frame_captured, frame_n: num(body.frame_n), captured_at: str(body.captured_at) };
}

function parseBox(value: unknown): [number, number, number, number] | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const nums = value.map(num);
  return nums.every((v) => v !== null) ? nums as [number, number, number, number] : null;
}

function parseFrame(value: unknown): ScanFrameResult | null {
  if (!isObj(value)) return null;
  const deg = num(value.rotation_deg);
  if (deg === null || typeof value.found !== 'boolean') return null;
  return {
    rotation_deg: deg, frame_n: num(value.frame_n), found: value.found, score: num(value.score), box_xyxy: parseBox(value.box_xyxy),
    reason: str(value.reason), bearing_deg: num(value.bearing_deg), distance_m: num(value.distance_m),
    distance_valid: typeof value.distance_valid === 'boolean' ? value.distance_valid : null, distance_source: str(value.distance_source),
  };
}

/** `best` 는 null(찾지 못함)이거나 이동에 필요한 칸이 다 있는 것. 반쯤 있는 것은 **모양이 틀린 것**이다. */
function parseBest(value: unknown): ScanBest | null | undefined {
  if (value === null) return null;
  if (!isObj(value)) return undefined;
  const deg = num(value.rotation_deg);
  const bearing = num(value.bearing_deg);
  if (deg === null || bearing === null || typeof value.distance_valid !== 'boolean') return undefined;
  return {
    rotation_deg: deg, bearing_deg: bearing, distance_m: num(value.distance_m), distance_valid: value.distance_valid,
    distance_source: str(value.distance_source), distance_note: str(value.distance_note), provisional: value.provisional === true,
  };
}

function parseCues(value: unknown): ScanCue[] {
  if (!Array.isArray(value)) return [];
  const out: ScanCue[] = [];
  for (const row of value) {
    if (!Array.isArray(row) || typeof row[0] !== 'string') continue;
    out.push({ name: row[0], value: num(row[1]), note: str(row[2]) ?? '' });
  }
  return out;
}

/**
 * 결과. 아직 끝나지 않았으면(`running` 등) 칸이 비어 있어도 된다 — 상태만 본다.
 * 끝났는데(`done`) `frames` 나 `best` 가 틀리면 null.
 */
export function parseResult(body: unknown): ScanResult | null {
  if (!isObj(body)) return null;
  const scanId = str(body.scan_id);
  const st = state(body.state);
  if (scanId === null || st === null) return null;
  const frames = Array.isArray(body.frames) ? body.frames.map(parseFrame) : [];
  const best = parseBest(body.best ?? null);
  if (st === 'done') {
    if (!Array.isArray(body.frames) || frames.some((frame) => frame === null) || best === undefined) return null;
  }
  const evidence = isObj(body.evidence) ? body.evidence : {};
  const target = TARGETS.includes(body.target as ScanTarget) ? body.target as ScanTarget : null;
  return {
    scan_id: scanId, state: st, target, query: str(body.query), targets: strings(body.targets),
    frames: frames.filter((frame): frame is ScanFrameResult => frame !== null),
    best: best ?? null, cues: parseCues(evidence.cues), enough: evidence.enough === true,
    reason: str(body.reason) ?? '', model: str(body.model), profile_version: num(body.profile_version),
    score_basis: body.score_basis === 'frame' || body.score_basis === 'track' ? body.score_basis : null,
    computed_at: str(body.computed_at), error: str(body.error),
  };
}
