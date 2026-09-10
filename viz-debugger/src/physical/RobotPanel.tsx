/**
 * src/physical/RobotPanel.tsx (260910 신설 — 화면 연결 §1 · §3 · §4)
 *
 * **시연에서 사람이 누르는 자리.** 누르는 순서가 곧 시연 대본이다.
 *
 *   0. 연결 확인 (`ping`)  — 발표 직전에만. 초록을 보고 무대에 오른다
 *   1. 발화/텍스트         — 이미 있다
 *   2. 승인                — 기존 승인 버튼. 거기서 스캔이 나간다
 *   3. **접근 시작**       — `door_turn` 뒤에 열린다. 자동으로 안 넘어간다
 *   4. **긴급 정지**       — 항상 보인다
 *
 * ## 연결이 끊긴 것과 로봇이 안 움직이는 것은 다르다 (§3)
 *
 * 둘을 같은 표시로 뭉치지 않는다. 브로커 연결 상태를 **따로** 보여 주는 자리를 위에 뒀다.
 * 「붙어 있는데 로봇이 거절했다」와 「아예 안 붙었다」는 고치는 방법이 전혀 다르다.
 */

import { useCallback, useEffect, useState } from 'react';
import { BROKER_PRESETS, presetReady } from './presets.ts';
import { PhysicalClient } from './PhysicalClient.ts';
import { canApproach, issueApproach, issuePing, stopFailureMessage } from './robotCommands.ts';
import { releaseStopped, setConnection, setPing, useRobotSession } from './robotSession.ts';
import { connectionAddress, connectionAddresses, connectionKey, saveConnections, useConnections } from '../shared/connections.ts';

export function RobotPanel({ client, params }: { client: PhysicalClient | null; params: Record<string, unknown> | null }) {
  const session = useRobotSession();
  const [busy, setBusy] = useState(false);
  // 주소를 구독한다 — 프리셋을 고르면 곧바로 칸이 따라와야 한다.
  useConnections();
  const address = connectionAddress('physical', 'ws');
  /** 한 칸만 바꾼다. 저장소는 통째로 받으므로 지금 값에 얹는다. */
  const setAddress = (value: string) => {
    saveConnections({ ...connectionAddresses(), [connectionKey('physical', 'ws')]: value });
  };

  useEffect(() => {
    if (client === null) return;
    return client.onStatus(setConnection);
  }, [client]);

  const onPing = useCallback(async () => {
    if (client === null) { setPing({ ok: false, roundTripMs: null, message: '브로커 연결 없음' }); return; }
    setBusy(true);
    if (client.getStatus().state !== 'open') await client.connect();
    setPing(await issuePing(client));
    setBusy(false);
  }, [client]);

  const stopped = session.stopped;
  const failure = stopped === null ? null : stopFailureMessage(stopped);

  return <section className="robot-panel">
    {/* 정지 실패는 가장 위에, 크게. **조용히 성공한 척하는 것이 최악이다.** */}
    {failure !== null && <p className="robot-stopfail" role="alert">{failure}</p>}
    {stopped !== null && <p className="robot-locked">
      <b>정지됨</b> {new Date(stopped.atIso).toLocaleTimeString()}
      {stopped.published && ' · 정지 명령을 보냈습니다'}
      <button type="button" className="robot-release" onClick={() => releaseStopped()}>
        정지 해제 — 다시 승인해야 합니다
      </button>
    </p>}

    <div className="robot-bar">
      {/* 브로커 연결 — 로봇이 안 움직이는 것과 **다른 축**이다 (§3). */}
      <span className={`robot-conn robot-conn--${session.connection.state}`}>
        브로커 {label(session.connection.state)}
        {session.connection.state === 'closed' && ` — ${session.connection.reason}`}
      </span>

      <select
        className="robot-preset"
        value={address}
        onChange={(event) => setAddress(event.target.value)}
      >
        {BROKER_PRESETS.filter(presetReady).map((preset) => (
          <option key={preset.id} value={preset.url}>{preset.label}{preset.url && ` — ${preset.url}`}</option>
        ))}
      </select>
      <input
        className="robot-address"
        value={address}
        onChange={(event) => setAddress(event.target.value)}
        placeholder="ws://…:9001"
      />

      <button type="button" className="robot-ping" disabled={busy} onClick={() => void onPing()}>
        연결 확인
      </button>
      {session.ping !== null && <span className={session.ping.ok ? 'robot-ping--ok' : 'robot-ping--fail'}>
        {session.ping.ok ? `✓ ${session.ping.roundTripMs} ms` : `✕ ${session.ping.message}`}
      </span>}

      {/* 진행률 — forward_m=0 이면 of 는 9다 (스캔 여덟 + door_turn 하나). */}
      {session.progress !== null && <span className="robot-progress">
        {session.progress.ack} / {session.progress.of}
      </span>}

      {/* 접근 시작 — **door_turn 뒤에만 열린다.** 자동으로 안 넘어간다 (§1). */}
      {canApproach() && client !== null && <button
        type="button"
        className="robot-approach"
        onClick={() => void issueApproach(client, params)}
      >
        접근 시작 — 문 쪽으로
      </button>}

      {/* **정지 버튼은 여기 없다.** 화면에 이미 있는 머리줄의 「■ 중단」을 살렸다
          (`AppShell`·`TopBar`) — 새로 만들지 않는다. 어느 화면에 있든 보여야 하는데
          머리줄은 늘 떠 있고 이 패널은 마일스톤 화면에만 있다. */}
    </div>

    {/* 로봇이 우리와 다른 방향을 보고 있다 — 시연 중에 알아야 하는 사실이다 (§5). */}
    {session.doorTurn?.mismatch != null && <p className="robot-yawoff">
      로봇이 {session.doorTurn.mismatch.robot}°, 화면이 고른 각도는 {session.doorTurn.mismatch.chosen}° —
      {' '}{Math.round(session.doorTurn.mismatch.diff)}° 어긋났습니다
    </p>}

    {/* 거절과 실패 — **코드와 문구를 그대로** 올린다 (§3). */}
    {Object.values(session.commands).filter((c) => c.state === 'failed').map((c) => (
      <p key={c.commandId} className="robot-reject" role="alert">
        {c.taskId} 실패 — <code>{c.code ?? '사유 없음'}</code> {c.message}
      </p>
    ))}
  </section>;
}

function label(state: string): string {
  if (state === 'open') return '연결됨';
  if (state === 'connecting') return '연결 중';
  if (state === 'closed') return '끊김';
  return '대기';
}
