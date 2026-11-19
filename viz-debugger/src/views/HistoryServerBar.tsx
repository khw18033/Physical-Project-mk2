/**
 * src/views/HistoryServerBar.tsx (261119 신설 — 임무 이력을 서버 DB 와 잇는다)
 *
 * **임무 이력 탭 맨 위의 서버 칸.** 주소를 넣고, 지금 붙어 있는지를 본다.
 * 연결 관리 판이 아니라 여기에 둔다(지시) — 이력을 보는 자리에서 「어디 이력을 보고 있나」가 바로 보여야 한다.
 *
 * 상태 줄은 넷을 가른다: 미설정 · 붙음 · 닿지 않음 · 임무 이력 서버가 아님. 「연결 안 됨」 하나로 뭉치면
 * 주소가 틀린 것인지 서버가 꺼진 것인지 알 수 없다(연결 관리 배지와 같은 규칙).
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
  const [invalid, setInvalid] = useState(false);
  // 다른 탭 · 검사가 주소를 바꿨으면 칸도 따라간다.
  useEffect(() => { setDraft(server.address); }, [server.address]);

  const normalized = normalizeServerAddress(draft);
  const changed = normalized !== server.address;
  const apply = () => {
    if (!changed) { void checkHistoryServer(); return; }
    setInvalid(!setHistoryServerAddress(draft));
  };

  const line = (() => {
    switch (server.state) {
      case 'unset': return t('hsrv.state.unset');
      case 'checking': return t('hsrv.state.checking');
      case 'connected': return t('hsrv.state.connected', { ms: server.latencyMs ?? 0, n: server.runCount ?? '—' });
      case 'unreachable': return t('hsrv.state.unreachable');
      case 'wrong-service': return t('hsrv.state.wrongService');
      case 'http-error': return t('hsrv.state.httpError', { detail: server.detail ?? '' });
    }
  })();

  return <div className={`history-server is-${server.state}`}>
    <label htmlFor="history-server-address">{t('hsrv.label')}</label>
    <form className="history-server__row" onSubmit={(event) => { event.preventDefault(); apply(); }}>
      <input id="history-server-address" type="text" inputMode="url" spellCheck={false} autoComplete="off"
        value={draft} placeholder={t('hsrv.placeholder')}
        onChange={(event) => { setDraft(event.target.value); setInvalid(false); }} />
      <button type="submit" className="history-action" disabled={normalized === null}>
        {changed ? (normalized === '' ? t('hsrv.disconnect') : t('hsrv.connect')) : t('hsrv.recheck')}
      </button>
    </form>
    {(invalid || normalized === null) && draft.trim() !== '' && <small className="history-why">{t('hsrv.invalid')}</small>}
    <p className="history-server__state" role="status">
      <span className="history-server__lamp" aria-hidden="true" />{line}
    </p>
    {server.state !== 'unset' && <small className="history-server__meta">
      {t('hsrv.checkedAt', { at: clock(server.checkedAtIso) })}
      {server.state !== 'connected' && server.lastOkAtIso !== null && ` · ${t('hsrv.lastOk', { at: clock(server.lastOkAtIso) })}`}
      {server.state !== 'connected' && server.detail !== null && server.state !== 'http-error' && ` · ${server.detail}`}
    </small>}
    {server.state === 'unreachable' && <small className="history-server__meta">{t('hsrv.unreachableHint')}</small>}
    {server.pending > 0 && <small className="history-server__meta is-warn">{t('hsrv.pending', { n: server.pending })}</small>}
    {server.lastRejected !== null && <small className="history-why">{t('hsrv.rejected', { what: server.lastRejected })}</small>}
    {server.address !== '' && <button type="button" className="history-action history-server__clear"
      onClick={() => { setHistoryServerAddress(''); setDraft(''); }}>{t('hsrv.disconnect')}</button>}
  </div>;
}
