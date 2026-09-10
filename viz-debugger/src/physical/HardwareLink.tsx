/**
 * src/physical/HardwareLink.tsx (260910 신설 — 하드웨어 카드에 연결 상태 반영)
 *
 * **하드웨어 카드가 아는 만큼만 말한다.**
 *
 * 8/31 결정(`VZ-D-07`)은 registry 장비의 **실측값**을 지어내지 않는다는 것이었고 그건
 * 그대로다 — 배터리·RSSI 는 로봇이 보내 주는 채널이 아직 없어서 자리표시로 남는다.
 *
 * 그런데 **연결은 이제 우리가 안다.** 브로커에 붙었는지, 단말이 `ping` 에 답하는지는
 * 실제로 재고 있는 값이다. 그걸 「연결 예정」이라고 적어 두는 것은 아는 것을 모른다고
 * 말하는 것이라 고쳤다.
 *
 * ## 세 층을 뭉치지 않는다
 *
 *   브로커  우리가 붙었는가          — 주소·포트·망
 *   단말    라즈베리파이가 답하는가  — ping 왕복
 *   로봇    개가 살아 있는가         — **모른다.** ping 은 단말까지만 증명한다
 *
 * 로봇 층을 초록으로 칠하면 「로봇이 살아 있다」는 거짓말이다. 단말이 답해도 로봇은
 * 모른다 — 그 사실을 카드에도 그대로 적는다.
 */

import { PendingSource } from '../shared/PendingSource.tsx';
import { healthOf, useConnectionHealth } from '../shared/connectionHealth.ts';
import { useRobotSession } from './robotSession.ts';

/** 이 장비가 로봇인가. 로봇이 아닌 장비는 예전 그대로 자리표시다. */
function isRobot(entityId: string): boolean {
  return entityId === 'robot-01';
}

export function HardwareLink({ entityId }: { entityId: string }) {
  useConnectionHealth();
  const session = useRobotSession();

  if (!isRobot(entityId)) {
    return <span><PendingSource id="hardware-pool-status" inline>상태 3행 — 연결 예정</PendingSource></span>;
  }

  const lines = healthOf('physical').lines;
  const broker = lines.find((l) => l.id === 'broker');
  const agent = lines.find((l) => l.id === 'agent');
  // 확인을 안 눌러 봤어도 소켓이 열려 있으면 그건 아는 사실이다.
  const brokerOk = broker?.ok ?? (session.connection.state === 'open' ? true : null);

  return <span className="hw-link">
    <em className={`hw-dot hw-dot--${mark(brokerOk)}`}>브로커 {glyph(brokerOk)}</em>
    <em className={`hw-dot hw-dot--${mark(agent?.ok ?? null)}`}>
      단말 {glyph(agent?.ok ?? null)}{agent?.roundTripMs != null && ` ${agent.roundTripMs}ms`}
    </em>
    {/* **로봇은 모른다.** ping 은 단말까지만 증명한다 — 초록으로 칠하지 않는다. */}
    <em className="hw-dot hw-dot--unknown" title="ping 은 단말까지만 증명합니다 — 로봇은 명령을 보내야 압니다">로봇 ?</em>
    {/* 실측 두 행은 여전히 남이 줄 데이터다 (VZ-D-07). */}
    <PendingSource id="hardware-pool-status" inline>배터리 · RSSI — 연결 예정</PendingSource>
  </span>;
}

function mark(ok: boolean | null): string {
  return ok === true ? 'ok' : ok === false ? 'bad' : 'unknown';
}
function glyph(ok: boolean | null): string {
  return ok === true ? '✓' : ok === false ? '✕' : '?';
}
