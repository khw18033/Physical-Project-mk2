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
 * 상단의 `conn` 배지는 **상태**(지금 붙어 있나)이고 이 판은 **설정**(어디에 붙을 것인가)이다.
 * 섞으면 「연결 안 됨」이 주소가 틀린 것인지 서버가 죽은 것인지 알 수 없어진다.
 */

import { useState } from 'react';
import {
  CONNECTION_TARGETS,
  connectionKey,
  connectionsWritable,
  resetConnections,
  saveConnections,
  useConnections,
} from '../shared/connections.ts';

export function ConnectionsPanel({ onClose }: { onClose(): void }) {
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
      접속 주소를 여기서 정합니다 (<code>VZ-C-07</code>). 환경변수는 <b>기본값</b>이 되고,
      여기서 넣은 값이 이깁니다. 지금 붙어 있는지는 상단의 연결 배지가 말합니다 —
      <b>이 판은 상태가 아니라 설정입니다.</b>
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
          <input
            value={draft[key] ?? ''}
            disabled={!target.live}
            placeholder={target.live ? field.fallback : '상대가 정해지면 열립니다'}
            onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }))} />
        </label>;
      })}
    </section>)}
    <footer className="connections__actions">
      {note && <span className="connections__note">{note}</span>}
      {/* 되돌아올 길. 틀린 주소를 넣으면 아무 데도 못 붙으므로 이 길이 없으면 갇힌다. */}
      <button onClick={restore}>기본값 복원</button>
      <button className="connections__apply" onClick={apply} disabled={!dirty}>적용</button>
    </footer>
  </aside>;
}
