/**
 * src/physical/uplink.ts (260910 신설 — 하드웨어 연동 §4 · §5)
 *
 * **로봇이 보내온 봉투를 화면이 읽는 모양으로 바꾸는 자리.**
 *
 * 응답 세 종이 모두 uplink 하나로 오고 종류는 `oneof body` 가 구분한다. 여기서 갈라
 * 화면에는 이미 갈라진 것만 넘긴다.
 *
 * ## step 은 1부터, 인덱스는 0부터
 *
 * **이 작업에서 가장 흔하게 날 실수다.** 로봇의 `step` 은 1~8 이고 우리 노드 인덱스는
 * 0~7 이다. `index = step - 1`. 한 칸 밀려도 화면은 그럴싸하게 돌아가서 눈으로는 못 잡는다.
 * 그래서 **변환하는 자리를 이 파일의 함수 하나로 묶었고**(`viewpointIndexOf`),
 * `verify:status-index` 가 그것부터 본다.
 *
 * ## 노드를 채우는 코드는 출처를 모른다
 *
 * `detail` 을 파싱해 인덱스를 내놓는 것이 여기까지이고, 그 인덱스가 로봇에서 왔는지
 * 대본에서 왔는지는 `src/viewpoint/fill.ts` 가 모른다 (260909 §6 과 같은 규칙).
 */

import { physical } from './protocol.js';

/** `CommandStatus.detail` 안의 JSON. 하드웨어가 보내는 그대로다. */
export type StatusDetail = {
  ack: number;
  of: number;
  event: 'scan_turn' | 'door_turn' | 'forward' | 'aborted' | string;
  step: number;
  steps: number;
  /** 그 시점 방위(도). **모를 수 있다 — null 이 정상이다.** 노드를 고르는 데 쓰지 않는다. */
  yaw_deg: number | null;
  note: string;
};

export type UplinkMessage =
  | { kind: 'acceptance'; commandId: string; accepted: boolean; code: string | null; message: string | null }
  | { kind: 'status'; commandId: string; state: string; detail: StatusDetail | null; raw: string }
  | { kind: 'result'; commandId: string; status: string; result: Record<string, number>; code: string | null; message: string | null };

/**
 * 봉투 하나 → 화면이 읽는 모양. **형식에 안 맞으면 null 이다** — 지어 채우지 않는다.
 * 우리가 안 쓰는 body(취소 응답·Capability)도 null 이다.
 */
export function decodeUplink(payload: Uint8Array): UplinkMessage | null {
  let envelope;
  try {
    envelope = physical.PhysicalCommandEnvelope.decode(payload);
  } catch {
    return null;
  }
  if (envelope.acceptance) {
    const a = envelope.acceptance;
    return {
      kind: 'acceptance',
      commandId: a.commandId ?? '',
      accepted: a.accepted === true,
      // 거절 사유를 **버리지 않는다.** robot_state_dead 가 실제로 나온 응답이고,
      // 로봇을 안 켜면 시연 당일에도 이게 뜬다 (§4).
      code: a.rejection?.code ?? null,
      message: a.rejection?.message ?? null,
    };
  }
  if (envelope.status) {
    const s = envelope.status;
    const raw = s.detail ?? '';
    return { kind: 'status', commandId: s.commandId ?? '', state: s.state ?? '', detail: parseDetail(raw), raw };
  }
  if (envelope.result) {
    const r = envelope.result;
    const names = physical.TerminalStatus;
    const status = Object.keys(names).find((key) => names[key as keyof typeof names] === r.status) ?? 'TERMINAL_STATUS_UNSPECIFIED';
    return {
      kind: 'result',
      commandId: r.commandId ?? '',
      status,
      result: Object.fromEntries(Object.entries(r.result ?? {}).map(([k, v]) => [k, Number(v)])),
      code: r.failure?.code ?? null,
      message: r.failure?.message ?? null,
    };
  }
  return null;
}

/** `detail` 은 JSON 문자열로 온다. 깨져 있으면 null — 그 사실이 화면에 남아야 한다. */
export function parseDetail(raw: string): StatusDetail | null {
  if (!raw.trim()) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const d = parsed as Record<string, unknown>;
  if (typeof d.step !== 'number' || typeof d.event !== 'string') return null;
  return {
    ack: typeof d.ack === 'number' ? d.ack : 0,
    of: typeof d.of === 'number' ? d.of : 0,
    event: d.event,
    step: d.step,
    steps: typeof d.steps === 'number' ? d.steps : 0,
    // **null 이 정상이다.** 모를 수 있다고 하드웨어가 못박았다.
    yaw_deg: typeof d.yaw_deg === 'number' ? d.yaw_deg : null,
    note: typeof d.note === 'string' ? d.note : 'ok',
  };
}

/**
 * **step(1부터) → 뷰포인트 노드 인덱스(0부터).** 변환은 여기 한 곳뿐이다.
 *
 * `scan_turn` 만 뷰포인트를 건드린다 (§5 ㉡). `door_turn` 은 마일스톤이 넘어가는 계기이지
 * 노드가 아니고, `forward` 는 `T-B2`, `aborted` 는 임무 중단이다.
 *
 * 범위 밖의 step 은 null 이다 — 없는 칸을 만들어 그리면 화면이 대본보다 커진다.
 */
export function viewpointIndexOf(detail: StatusDetail | null, count = 8): number | null {
  if (detail === null) return null;
  if (detail.event !== 'scan_turn') return null;
  const index = detail.step - 1;
  if (!Number.isInteger(index) || index < 0 || index >= count) return null;
  return index;
}

/**
 * **로봇이 일어서는 중인지 알려 주는 자리** (연동 가이드 §4-3).
 *
 * 구동 브리지는 평시에 내려가 있다 — 기동하는 순간 로봇이 일어서기 때문이다. 이동 명령은
 * 필요하면 스스로 브리지를 띄우고, 그 사이 진행 보고가 두 건 더 온다.
 *
 *     수락 → sdk_starting → sdk_ready → executing → (임무 ACK…) → 종료
 *
 * 가이드가 「`sdk_starting` 이 보이면 로봇이 지금 일어서는 중이다. 화면에 그대로 드러내야
 * 한다」고 못박았다. 몇 초 동안 아무 일도 안 일어나는 것처럼 보이는 구간이라, 안 그리면
 * 발표장에서 「왜 안 가지」가 된다.
 */
export const SDK_STARTING = 'sdk_starting';
export const SDK_READY = 'sdk_ready';

/**
 * 임무 ACK 가 아닌 **단계 보고**를 읽는다. 못 읽으면 null 이다.
 *
 * `detail` 은 한 종류가 아니다. 실측으로 셋을 봤다:
 *
 *     ""                                          빈 것 — 아무 말도 안 한다
 *     "executing"                                 맨 문자열로 온 단계 이름
 *     {"ack":3,"of":10,"event":"scan_turn",…}     임무 ACK (JSON)
 *
 * 그래서 `parseDetail` 하나로 다 받으면 안 된다 — 그것은 `step` 을 요구해서 앞의 둘을
 * **조용히 버린다.** 실제로 `diag` 의 단계 둘이 그렇게 사라졌다. 임무 ACK 인 것은 여기서
 * null 을 돌려주고 `parseDetail` 에게 맡긴다 — 한 봉투가 두 뜻이 되면 안 된다.
 */
export function stageOf(raw: string): string | null {
  const text = raw.trim();
  if (text === '') return null;
  // 맨 문자열이면 그것이 단계 이름이다.
  if (!text.startsWith('{')) return text;
  // 임무 ACK 면 단계가 아니다 — 저쪽 함수의 몫이다.
  if (parseDetail(raw) !== null) return null;
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return null; }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const event = (parsed as Record<string, unknown>).event;
  return typeof event === 'string' && event !== '' ? event : null;
}

/** 이 단계에서 **로봇이 일어서는 중**인가. */
export function isStanding(stage: string | null): boolean {
  return stage === SDK_STARTING;
}

/** `note` 가 `ok` 가 아니면 경고다. 조용히 정상으로 칠하지 않는다 (§5 ㉢). */
export function warningOf(detail: StatusDetail | null): string | null {
  if (detail === null) return null;
  return detail.note === 'ok' ? null : detail.note;
}

/** 진행률 — `ack/of`. `of` 가 0 이면 모른다는 뜻이라 null 이다. */
export function progressOf(detail: StatusDetail | null): { ack: number; of: number } | null {
  if (detail === null || detail.of <= 0) return null;
  return { ack: detail.ack, of: detail.of };
}

/**
 * `door_turn` 인가 — **마일스톤이 넘어가는 계기다** (§5). 새 노드를 만들지 않는다.
 * 초록 노드에서 「문에 접근한다」로 선이 이어지는 자리가 순서도의 그 지점이다.
 */
export function isDoorTurn(detail: StatusDetail | null): boolean {
  return detail?.event === 'door_turn';
}

/**
 * `door_turn` 이 고른 걸음이 몇 번째인가 (260910 — 「로봇이 고른 각도가 곧 화면이 고른 각도」).
 *
 * 예전에는 화면이 대본으로 고른 각도와 로봇의 `yaw_deg` 를 **대조해 어긋남을 표시**했다.
 * 그걸 없앴다 — 어긋남을 보여 줄 것이 아니라 **로봇이 고른 쪽을 따라야** 한다. 로봇이 문이
 * 있다고 판단해 몸을 돌린 그 방향이 곧 초록 칸이다.
 *
 * ## 절대 각도로 고르지 않는다
 *
 * 로봇의 `yaw_deg` 는 기준점이 움직인다(연동 가이드 §5-3) — 시뮬레이터는 회차가 이월되고
 * 실물은 출발 자세에 맞춰 재보정된다. 그래서 **그 판의 회전 걸음들이 실제로 보고한 yaw**
 * 와 견준다. 같은 판의 값끼리 견주므로 기준점이 어디든 상관없다.
 *
 * 걸음을 하나도 못 봤으면 null 이다 — 지어 고르지 않는다.
 */
export function chosenIndexOf(
  detail: StatusDetail | null,
  seenYawByIndex: ReadonlyMap<number, number> = new Map(),
): number | null {
  if (detail === null || !isDoorTurn(detail)) return null;
  const seen = seenYawByIndex ?? new Map();

  // **`step` 을 믿지 않는다** (260910 실측). `door_turn` 의 `step` 은 고른 걸음이 아니라
  // **늘 1** 이다 — 실제 로그:
  //
  //   ack 129 step 8 scan_turn  yaw 180
  //   ack 130 step 1 door_turn  yaw 225   ← 고른 것은 yaw 225 인 7번째 걸음이다
  //
  // 그래서 **방위로 견준다.** 같은 판의 회전 걸음들이 보고한 yaw 와 맞춰 보면 기준점이
  // 어디든 상관없다(연동 가이드 §5-3 — 절대 각도는 기준점이 움직인다).
  if (detail.yaw_deg !== null && seen.size > 0) {
    return closestIndex(seen, detail.yaw_deg);
  }

  // 방위를 모를 때만 걸음 번호를 쓴다 — 그마저 없으면 안 고른다.
  const byStep = detail.step - 1;
  if (Number.isInteger(byStep) && seen.has(byStep)) return byStep;
  return null;
}

/** 본 방위들 중 가장 가까운 걸음. 각도는 360 으로 감긴다. */
function closestIndex(seen: ReadonlyMap<number, number>, yawDeg: number): number | null {
  let best: number | null = null;
  let closest = Number.POSITIVE_INFINITY;
  for (const [index, yaw] of seen) {
    const raw = Math.abs(yaw - yawDeg) % 360;
    const diff = raw > 180 ? 360 - raw : raw;
    if (diff < closest) { closest = diff; best = index; }
  }
  return best;
}
