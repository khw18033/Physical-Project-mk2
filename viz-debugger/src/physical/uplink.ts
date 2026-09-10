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
 * `door_turn` 의 `yaw_deg` 가 화면이 고른 각도와 맞는가 (§5).
 *
 * 어긋나면 로봇이 우리와 다른 방향을 보고 있다는 뜻이고, **시연 중에 알아야 하는 사실**이다.
 * 어긋났을 때 무엇을 할지는 정하지 않았다 — 지시서가 「일단 기록만 남긴다」고 했다.
 */
export function yawMismatch(
  detail: StatusDetail | null,
  chosenAngleDeg: number | null,
  toleranceDeg = 15,
): { robot: number; chosen: number; diff: number } | null {
  if (detail === null || detail.yaw_deg === null || chosenAngleDeg === null) return null;
  // 각도는 360 으로 감긴다 — 350 도와 10 도의 차이는 340 이 아니라 20 이다.
  const raw = Math.abs(detail.yaw_deg - chosenAngleDeg) % 360;
  const diff = raw > 180 ? 360 - raw : raw;
  return diff > toleranceDeg ? { robot: detail.yaw_deg, chosen: chosenAngleDeg, diff } : null;
}
