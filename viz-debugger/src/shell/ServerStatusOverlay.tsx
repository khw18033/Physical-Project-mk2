/**
 * src/shell/ServerStatusOverlay.tsx (261001 신설 — 서버 칸 더블클릭 상세)
 *
 * 서버 칸은 한 줄 요약이다. **더블클릭하면 그 서버의 상세**를 연다 — 장비 카드의 `DeviceStatusOverlay` 와 같은 손짓 ·
 * 같은 규칙이다(`.modal-backdrop` 위 오버레이 · 뒤를 교체하지 않는다 · 닫는 길은 닫기 버튼 · Esc · 배경 누르기).
 *
 * 장비 상세를 그대로 쓰지 않는다. 그쪽은 장비 id 로 배터리 · 신호 · 카메라를 찾는데 서버에는 그런 값이 없다 —
 * 빈 칸만 늘어선다.
 *
 * ## 무엇을 적나 — **이미 받고 있는 것만**
 *
 * | 칸 | 어디서 |
 * |---|---|
 * | 주소 · 구역 | 연결 관리에 적힌 값. 토큰은 가린다 |
 * | 소켓 · 마지막 수신 · 받은 수 | `gatewayFeed` |
 * | 서버 경유 장비 | `gatewayFeed.serverEntities` — 봉투가 공통 헤더로 스스로 밝힌 장비만 |
 * | 연결 확인 | 연결 관리의 「확인」과 **같은 결과**(`connectionHealth` 의 `gateway`). 여기서 눌러도 같은 자리에 적힌다 |
 *
 * 서버가 따로 내주는 상태(버전 · 부하 등)는 아직 길이 없다. 지어내지 않는다.
 */

import { useEffect, useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress } from '../shared/connections.ts';
import { maskToken, useGatewayFeed } from '../shared/gatewayFeed.ts';
import { useConnectionHealth } from '../shared/connectionHealth.ts';
import { checkTarget } from '../shared/connectionCheck.ts';

/** 몇 초 전인가. 모르면 null. */
function secondsAgo(atMs: number | null, nowMs: number): number | null {
  return atMs === null ? null : Math.max(0, Math.round((nowMs - atMs) / 1000));
}

export function ServerStatusOverlay({ url, host, onClose }: { url: string; host: string; onClose(): void }) {
  useLang();
  const feed = useGatewayFeed();
  const health = useConnectionHealth().gateway ?? { checking: false, lines: [] };
  // 「n초 전」이 멈춰 보이지 않게 1초마다 다시 그린다 — 봉투는 1초 안의 것을 다시 그리지 않는다(`gatewayFeed`).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const zone = connectionAddress('gateway', 'zone').trim();
  const ago = secondsAgo(feed.lastAtMs, now);
  const devices = Object.entries(feed.serverEntities).sort(([a], [b]) => a.localeCompare(b));

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal server-modal" role="dialog" aria-label={t('srv.title')}>
      <header>
        <div>
          <h2>{t('srv.title')}</h2>
          <small>{host}</small>
        </div>
        <button onClick={onClose}>{t('dso.1')}</button>
      </header>
      <div className="server-modal__body">
        <section>
          <h3>{t('srv.detail.connection')}</h3>
          <dl className="server-modal__facts">
            <div><dt>{t('srv.detail.address')}</dt><dd><code>{maskToken(url)}</code></dd></div>
            <div><dt>{t('check.line.gatewayZone')}</dt><dd>{zone === '' ? t('srv.zoneEmpty') : zone}</dd></div>
            <div><dt>{t('check.line.gatewaySocket')}</dt><dd>{t(`srv.socket.${feed.socket}`)}</dd></div>
            <div><dt>{t('srv.detail.lastData')}</dt><dd>{ago === null ? t('srv.noData') : t('srv.detail.ago', { sec: ago })}</dd></div>
            <div><dt>{t('srv.detail.count')}</dt><dd>{feed.count}</dd></div>
          </dl>
        </section>
        <section>
          <h3>{t('srv.detail.devices', { n: devices.length })}</h3>
          {devices.length === 0
            ? <p className="server-modal__none">{t('srv.detail.noDevice')}</p>
            : <table className="server-modal__table">
              <thead><tr><th>{t('srv.detail.deviceId')}</th><th>{t('srv.detail.lastData')}</th></tr></thead>
              <tbody>{devices.map(([id, at]) => <tr key={id}><td>{id}</td><td>{t('srv.detail.ago', { sec: secondsAgo(at, now) ?? 0 })}</td></tr>)}</tbody>
            </table>}
        </section>
        <section>
          <header className="server-modal__check">
            <h3>{t('srv.detail.check')}</h3>
            <button type="button" disabled={health.checking} onClick={() => { void checkTarget('gateway', null); }}>
              {health.checking ? t('conn.checking') : t('conn.check')}
            </button>
          </header>
          {health.lines.length === 0
            ? <p className="server-modal__none">{t('conn.notChecked')}</p>
            : <ul className="server-modal__lines">{health.lines.map((row) => <li key={row.id} className={`conn-dot conn-dot--${row.ok === true ? 'ok' : row.ok === false ? 'bad' : 'unknown'}`}>
              {t(row.labelKey)} {row.ok === true ? '✓' : row.ok === false ? '✕' : '?'}
              {row.roundTripMs !== null && ` ${row.roundTripMs}ms`}
              {row.reason !== null && ` (${row.reason})`}
            </li>)}</ul>}
          {health.lines.length > 0 && <small className="conn-health__at">{new Date(health.lines[0].checkedAtIso).toLocaleTimeString()}</small>}
        </section>
      </div>
      <footer>
        <span>{t('dso.2')}</span>
      </footer>
    </section>
  </div>;
}
