/**
 * src/views/HistoryServerBar.tsx (261119 신설 — 임무 이력을 서버 DB 와 잇는다)
 *
 * **임무 이력 화면의 서버 띠.** 주소를 넣고, 지금 붙어 있는지를 본다.
 * 연결 관리 판이 아니라 임무 이력 화면에 둔다(지시) — 이력을 보는 자리에서 「어디 이력을 보고 있나」가 바로 보여야 한다.
 *
 * **자리: 상단 바와 목록 · 그래프 칸 사이의 가로 띠 한 줄** (261119 화면 확인 지시 둘).
 *  - 처음엔 목록 기둥(300px) 맨 위의 작은 상자였는데 주소와 상태가 잘 안 보였다 → 가로 띠로.
 *  - 띠가 세 줄로 커지자 「칸이 너무 넓으면 안 된다」 → **한 줄.** 작은 글씨는 확인 시각 · 마지막 연결 · 상태 메시지(끊긴 사유)만.
 *    그 셋은 작은 글씨 줄이 아니라 띠 **오른쪽 빈자리**에 둔다(지시). 저장처 안내 · 대피 판 수 · 올리기 진행 · 거절 사유는 띠에서 뺐다(동작은 그대로다 — `historyUpload.ts`).
 *
 * 상태는 미설정 · 확인 중 · 연결됨 · 불안정 · 닿지 않음 · 임무 이력 서버가 아님 · 서버 오류를 가른다.
 * 「연결 안 됨」 하나로 뭉치면 주소가 틀린 것인지 서버가 꺼진 것인지 알 수 없다(연결 관리 배지와 같은 규칙).
 */

import { useEffect, useState } from 'react';
import {
  checkHistoryServer, normalizeServerAddress, setHistoryServerAddress, useHistoryServer,
} from '../record/historyServer.ts';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';

/** `2026-11-19T10:42:05.000Z` → 이 기기 시각 `10:42:05`. */
const clock = (iso: string | null) => (iso === null ? '—' : new Date(iso).toLocaleTimeString('en-GB', { hour12: false }));

export function HistoryServerBar() {
  useLang();
  const server = useHistoryServer();
  const [draft, setDraft] = useState(server.address);
  // 다른 탭 · 검사가 주소를 바꿨으면 칸도 따라간다.
  useEffect(() => { setDraft(server.address); }, [server.address]);

  const normalized = normalizeServerAddress(draft);
  const changed = normalized !== server.address;
  const apply = () => {
    if (!changed) { void checkHistoryServer(); return; }
    setHistoryServerAddress(draft);
  };

  const line = (() => {
    switch (server.state) {
      case 'unset': return t('hsrv.state.unset');
      case 'checking': return t('hsrv.state.checking');
      case 'connected': return t('hsrv.state.connected', { ms: server.latencyMs ?? 0, n: server.runCount ?? '—' });
      case 'unstable': return t('hsrv.state.unstable', { n: server.okStreak });
      case 'unreachable': return t('hsrv.state.unreachable');
      case 'wrong-service': return t('hsrv.state.wrongService');
      case 'http-error': return t('hsrv.state.httpError', { detail: server.detail ?? '' });
    }
  })();

  // 띠 오른쪽 — 확인 시각 · 마지막 연결 · 상태 메시지(끊긴 사유). 이 셋만.
  const meta = [
    server.state !== 'unset' ? t('hsrv.checkedAt', { at: clock(server.checkedAtIso) }) : null,
    server.state !== 'unset' && server.state !== 'connected' && server.lastOkAtIso !== null ? t('hsrv.lastOk', { at: clock(server.lastOkAtIso) }) : null,
    server.state !== 'connected' && server.state !== 'http-error' && server.detail !== null ? server.detail : null,
  ].filter((item): item is string => item !== null);

  return <section className={`history-server is-${server.state}`} aria-label={t('hsrv.label')}>
    <label htmlFor="history-server-address">{t('hsrv.label')}</label>
    <form className="history-server__form" onSubmit={(event) => { event.preventDefault(); apply(); }}>
      {/* 주소 꼴이 아니면 칸 테두리가 붉어지고 버튼이 꺼진다 — 글로 따로 적지 않는다. */}
      <input id="history-server-address" type="text" inputMode="url" spellCheck={false} autoComplete="off"
        aria-invalid={normalized === null} value={draft} placeholder={t('hsrv.placeholder')}
        onChange={(event) => setDraft(event.target.value)} />
      {/* 주소가 비어 있고 저장된 것도 없으면 누를 것이 없다 — 「다시 확인」이 아니라 꺼진 「연결」. */}
      <button type="submit" className="history-server__btn is-primary" disabled={normalized === null || (normalized === '' && server.address === '')}>
        {changed ? (normalized === '' ? t('hsrv.disconnect') : t('hsrv.connect')) : server.address === '' ? t('hsrv.connect') : t('hsrv.recheck')}
      </button>
      {server.address !== '' && <button type="button" className="history-server__btn"
        onClick={() => { setHistoryServerAddress(''); setDraft(''); }}>{t('hsrv.disconnect')}</button>}
    </form>
    <p className="history-server__state" role="status">
      <span className="history-server__lamp" aria-hidden="true" />{line}
    </p>
    {meta.length > 0 && <p className="history-server__meta">{meta.map((item) => <span key={item}>{item}</span>)}</p>}
  </section>;
}
