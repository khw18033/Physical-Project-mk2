/**
 * src/shell/ConnectionsPanel.tsx (260904 — `VZ-C-07` 연결 대상 설정)
 *
 * **접속 주소를 화면에서 정한다.** 지금까지는 빌드 시점 환경변수라 바꾸려면 다시 빌드해야
 * 했고, 현장에서 게이트웨이·제어 노드 IP가 바뀔 때마다 빌드할 수는 없었다.
 *
 * 화면은 **대상 목록을 그린다** — 손으로 넷을 적지 않는다. 목록의 원천은
 * `shared/connections.ts` 하나이고, 대상이 늘거나 줄면 이 파일은 그대로다.
 *
 * `live: false` 인 대상(제어 노드 · 디지털 트윈)은 **주소를 넣어도 붙을 곳이 없다.**
 * 칸을 잠그고 「연결 예정」으로 둔다 — 없는 것을 있는 척하지 않는다(다른 자리표시와 같은 규칙).
 *
 * ## 설정만이 아니라 확인까지 (260910 — 연결 관리 통합)
 *
 * 260904 에는 이 판이 **설정**(어디에 붙을 것인가)만 하고 상태는 상단 배지가 말했다.
 * 그 가름이 하드웨어가 붙으면서 깨졌다 — 로봇은 「주소가 맞는가」와 「로봇이 답하는가」가
 * 따로 놀고, 둘 다 무대에 오르기 전에 확인해야 하는 것이다. 그래서 대상마다 **네 줄**을 둔다:
 * 주소 · 상태 · 확인 버튼 · 마지막 확인.
 *
 * **「붙었다」와 「답한다」는 다르다.** 브로커는 살아 있는데 로봇이 꺼져 있으면 연결은
 * 성공이고 왕복은 실패다. `physical` 이 줄을 둘 갖는 이유가 그것이다.
 *
 * 상단의 `conn` 배지는 여전히 게이트웨이 연결 하나를 말한다 — 그건 늘 붙어 있어야 하는
 * 것이라 성격이 다르다.
 */

import { useState } from 'react';
import { BROKER_PRESETS, presetReady } from '../physical/presets.ts';
import { checkTarget, type PhysicalProbe } from '../shared/connectionCheck.ts';
import { robotFacts } from '../physical/robotFacts.ts';
import { useDeviceStates } from '../physical/deviceState.ts';
import { CHECKED_TARGETS, useConnectionHealth, type TargetHealth } from '../shared/connectionHealth.ts';
import type { ConnectionTargetId } from '../shared/connections.ts';
import {
  CONNECTION_TARGETS,
  connectionKey,
  connectionsWritable,
  resetConnections,
  saveConnections,
  useConnections,
} from '../shared/connections.ts';

export function ConnectionsPanel({ onClose, physical }: { onClose(): void; physical?: PhysicalProbe | null }) {
  const current = useConnections();
  /** 편집 중인 값. 저장을 눌러야 적용된다 — 한 글자 칠 때마다 끊고 다시 붙으면 못 쓴다. */
  const [draft, setDraft] = useState<Record<string, string>>({ ...current });
  const [note, setNote] = useState<string | null>(null);
  const writable = connectionsWritable();
  const dirty = CONNECTION_TARGETS.some((target) => target.fields.some((field) => {
    const key = connectionKey(target.id, field.key);
    return (draft[key] ?? '') !== (current[key] ?? '');
  }));

  const apply = () => {
    const saved = saveConnections(draft);
    setNote(saved
      ? '적용했습니다 — 게이트웨이 주소가 바뀌었으면 끊고 새 주소로 다시 붙습니다.'
      : '이번 세션에만 적용했습니다 — 저장소가 막혀 있어 새로고침하면 기본값으로 돌아갑니다.');
  };
  const restore = () => {
    resetConnections();
    setDraft({});
    setNote('기본값으로 되돌렸습니다.');
  };

  return <aside className="global-panel global-panel--connections">
    <header><b>⇄ 연결 관리</b><button onClick={onClose}>닫기</button></header>
    <p className="connections__lead">
      접속 주소를 여기서 정하고 <b>여기서 확인합니다</b> (<code>VZ-C-07</code>).
      환경변수는 <b>기본값</b>이 되고 여기서 넣은 값이 이깁니다.
      <b>무대에 오르기 전에 넷을 다 눌러 초록을 확인하세요</b> — 시연 중에는 다시 열지 않습니다.
    </p>
    {!writable && <p className="connections__warn">
      저장소가 막혀 있습니다 — 바꿔도 이번 세션에만 적용되고 새로고침하면 기본값으로 돌아갑니다.
    </p>}
    {/* 목록을 그린다. 대상이 늘면 이 파일이 아니라 shared/connections.ts 가 바뀐다. */}
    {CONNECTION_TARGETS.map((target) => <section key={target.id} className={`conn-target${target.live ? '' : ' conn-target--pending'}`}>
      <h3>{target.label}{target.live ? null : <em>연결 예정</em>}</h3>
      <p>{target.what}</p>
      {target.pending && <p className="conn-target__pending">{target.pending}</p>}
      {target.fields.map((field) => {
        const key = connectionKey(target.id, field.key);
        return <label key={key}>
          <span>{field.label}</span>
          {/* 프리셋이 있는 대상은 고르는 자리도 준다 (§2) — 지금은 physical 뿐이다.
              이름이 안 풀릴 때 손으로 IP 를 치는 것보다 고르는 편이 빠르다. */}
          {target.id === 'physical' && <select
            className="conn-preset"
            value={BROKER_PRESETS.find((preset) => preset.url === (draft[key] ?? ''))?.id ?? 'manual'}
            onChange={(event) => {
              const preset = BROKER_PRESETS.find((p) => p.id === event.target.value);
              if (preset && preset.url) setDraft((prev) => ({ ...prev, [key]: preset.url }));
            }}
          >
            {BROKER_PRESETS.map((preset) => <option
              key={preset.id}
              value={preset.id}
              // 값이 빈 프리셋은 **아직 없는 것**이다 — 고를 수 없게 막는다.
              disabled={!presetReady(preset)}
            >{preset.label}{presetReady(preset) || preset.id === 'manual' ? '' : ' (미정)'}</option>)}
          </select>}
          <input
            value={draft[key] ?? ''}
            disabled={!target.live}
            placeholder={target.live ? field.fallback : '상대가 정해지면 열립니다'}
            onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }))} />
        </label>;
      })}
      {/* 상태 · 확인 · 마지막 확인 — 나머지 세 줄 (§2). 확인 방법이 있는 대상만. */}
      {CHECKED_TARGETS.includes(target.id) && <HealthRow
        target={target.id}
        physical={target.id === 'physical' ? (physical ?? null) : null}
      />}
    </section>)}
    <footer className="connections__actions">
      {note && <span className="connections__note">{note}</span>}
      {/* 되돌아올 길. 틀린 주소를 넣으면 아무 데도 못 붙으므로 이 길이 없으면 갇힌다. */}
      <button onClick={restore}>기본값 복원</button>
      <button className="connections__apply" onClick={apply} disabled={!dirty}>적용</button>
    </footer>
  </aside>;
}

/**
 * 대상 하나의 **상태 · 확인 · 마지막 확인** 세 줄.
 *
 * 줄이 여럿일 수 있다 — `physical` 이 브로커와 로봇 둘이다. 한 줄로 뭉치면 발표 직전에
 * 주소를 봐야 하는지 로봇 전원을 봐야 하는지 못 가른다 (§3).
 */
function HealthRow({ target, physical }: { target: ConnectionTargetId; physical: PhysicalProbe | null }) {
  const health = useConnectionHealth();
  // 장비 상태를 구독한다 — 로봇 줄이 그 값으로 채워진다.
  useDeviceStates();
  const state: TargetHealth = health[target] ?? { checking: false, lines: [] };
  return <div className="conn-health">
    <div className="conn-health__lines">
      {state.lines.length === 0
        ? <span className="conn-dot conn-dot--unknown">아직 확인하지 않았습니다</span>
        : state.lines.map((row) => <span key={row.id} className={`conn-dot conn-dot--${row.ok === true ? 'ok' : row.ok === false ? 'bad' : 'unknown'}`}>
          {row.label} {row.ok === true ? '✓' : row.ok === false ? '✕' : '?'}
          {row.roundTripMs !== null && ` ${row.roundTripMs}ms`}
          {row.reason !== null && ` — ${row.reason}`}
        </span>)}
    </div>
    <button
      type="button"
      className="conn-check"
      disabled={state.checking}
      onClick={() => void checkTarget(target, physical, robotFacts)}
    >{state.checking ? '확인 중…' : '확인'}</button>
    {state.lines.length > 0 && <small className="conn-health__at">
      {new Date(state.lines[0].checkedAtIso).toLocaleTimeString()}
    </small>}
  </div>;
}
