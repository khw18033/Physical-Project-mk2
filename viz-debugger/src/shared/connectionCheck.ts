/**
 * src/shared/connectionCheck.ts (260910 신설 — 연결 관리 통합 §2 · §3)
 *
 * **눌러서 실제로 왕복시키는 자리.** 대상마다 확인 방법이 다르고, 그 다름이 여기 한 곳에 있다.
 *
 * | 대상 | 확인 |
 * |---|---|
 * | `physical` | 브로커 연결 + `ping` 왕복 — **두 줄로 나눈다** |
 * | `detect` | `GET /health` — 2단계-B 에서 잇는다. 지금은 자리만 |
 * | `stt` | `SttClient.probe()` — 기존 |
 * | `generate` | `LlmClient.probe()` — 기존 |
 *
 * `stt`·`generate` 는 **기존 동작을 바꾸지 않는다**(§7). 이미 있는 `probe()` 를 부르기만 한다.
 */

import { probe as generateProbe } from '../generate/LlmClient.ts';
import { probe as sttProbe } from '../stt/SttClient.ts';
import type { ConnectionTargetId } from './connections.ts';
import { line, setChecking, setHealth, type HealthLine } from './connectionHealth.ts';

/**
 * `physical` 을 확인할 때 쓸 것. 로봇 경계를 이 파일이 직접 열지 않는다 —
 * 주소·토픽을 아는 면은 `src/physical/` 하나여야 한다(`verify:physical-port`).
 * 화면이 클라이언트를 넘긴다.
 */
export type PhysicalProbe = {
  connect(): Promise<{ state: string; reason?: string }>;
  getStatus(): { state: string; reason?: string };
  ping(): Promise<{ ok: boolean; roundTripMs: number | null; message: string }>;
};

async function timed<T>(run: () => Promise<T>): Promise<{ value: T; ms: number }> {
  const startedAt = Date.now();
  const value = await run();
  return { value, ms: Date.now() - startedAt };
}

/**
 * **`physical` 은 줄이 둘이다** (§3).
 *
 * 브로커에 붙는 것과 로봇이 답하는 것은 별개다. 브로커는 살아 있는데 로봇이 꺼져 있으면
 * **연결은 성공이고 왕복은 실패다.** 뭉치면 주소를 봐야 하는지 로봇 전원을 봐야 하는지
 * 발표 직전에 못 가른다.
 */
export async function checkPhysical(client: PhysicalProbe | null): Promise<readonly HealthLine[]> {
  if (client === null) {
    return [line('broker', '브로커', false, { reason: '클라이언트가 없습니다' })];
  }
  const status = client.getStatus().state === 'open'
    ? client.getStatus()
    : (await timed(() => client.connect())).value;

  const broker = status.state === 'open'
    ? line('broker', '브로커', true)
    : line('broker', '브로커', false, { reason: status.reason ?? status.state });

  // 브로커가 안 붙었으면 로봇 줄은 **확인할 수 없다** — 실패가 아니라 못 물어본 것이다.
  if (!broker.ok) {
    return [broker, line('robot', '로봇', false, { reason: '브로커가 없어 물어보지 못했습니다' })];
  }

  const { value: ping, ms } = await timed(() => client.ping());
  return [
    broker,
    ping.ok
      ? line('robot', '로봇', true, { roundTripMs: ping.roundTripMs ?? ms })
      : line('robot', '로봇', false, { reason: ping.message }),
  ];
}

/**
 * `detect` — **자리만 만든다** (§7 「detect 의 실제 확인 로직 — 2단계-B에서 잇는다」).
 *
 * 여기서 `GET /health` 를 지금 부르면, 붙을 곳이 없는 주소에 매번 실패 로그가 쌓이고
 * 「빨간 줄」이 늘 하나 켜져 있게 된다. 그러면 발표 직전 점검에서 「넷 다 초록」이
 * 애초에 불가능해진다. **못 물어봤다고 말한다.**
 */
export async function checkDetect(): Promise<readonly HealthLine[]> {
  return [line('health', 'GET /health', false, { reason: '2단계-B 에서 잇습니다 — 아직 확인하지 않습니다' })];
}

export async function checkStt(): Promise<readonly HealthLine[]> {
  const { value, ms } = await timed(() => sttProbe());
  return [value.alive
    ? line('probe', '서비스', true, { roundTripMs: ms })
    : line('probe', '서비스', false, { reason: value.reason })];
}

export async function checkGenerate(): Promise<readonly HealthLine[]> {
  const { value, ms } = await timed(() => generateProbe());
  return [value.alive
    ? line('probe', '서비스', true, { roundTripMs: ms })
    : line('probe', '서비스', false, { reason: value.reason })];
}

/**
 * 대상 하나를 확인한다. **던지지 않는다** — 여기서 예외가 새면 팝업이 통째로 날아간다.
 * 예외도 결과이고, 그 사유가 화면에 남아야 한다.
 */
export async function checkTarget(target: ConnectionTargetId, physical: PhysicalProbe | null): Promise<void> {
  setChecking(target, true);
  try {
    if (target === 'physical') setHealth(target, await checkPhysical(physical));
    else if (target === 'detect') setHealth(target, await checkDetect());
    else if (target === 'stt') setHealth(target, await checkStt());
    else if (target === 'generate') setHealth(target, await checkGenerate());
    else setHealth(target, [line('none', '확인', false, { reason: '이 대상은 확인 방법이 없습니다' })]);
  } catch (error) {
    setHealth(target, [line('error', '확인', false, {
      reason: error instanceof Error ? error.message : String(error),
    })]);
  }
}
