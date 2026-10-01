/**
 * src/shell/ServerCard.tsx (261001 신설 — 백엔드 서버를 하드웨어 패널에 · **임시**)
 *
 * **서버도 붙어 있는지 카드로 본다.** 서버는 장비가 아니라서 하드웨어 카드 자리가 맞는지는 아직 정하지 않았다
 * (261001 지시 — 「일단 임시로」). 그래서 장비 카드와 모양만 같고 **끌어서 마일스톤에 놓을 수 없다** — 장치 자리에
 * 서버가 앉으면 안 된다.
 *
 * 게이트웨이가 우리 컴퓨터의 목(`127.0.0.1` · `localhost`)이면 그리지 않는다 — 목은 서버가 아니다.
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import { maskToken, useGatewayFeed } from '../shared/gatewayFeed.ts';

/** 우리 컴퓨터의 목 게이트웨이인가. */
export function isLocalGateway(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '[::1]';
  } catch {
    return true;
  }
}

export function ServerCard() {
  useLang();
  useConnections();
  const feed = useGatewayFeed();
  const url = connectionAddress('gateway', 'ws').trim();
  if (url === '' || isLocalGateway(url)) return null;
  const host = (() => { try { return new URL(url).host; } catch { return maskToken(url); } })();
  const ago = feed.lastAtMs === null ? null : Math.max(0, Math.round((Date.now() - feed.lastAtMs) / 1000));
  const devices = Object.keys(feed.serverEntities).length;
  const state = feed.socket === 'open' ? 'ok' : feed.socket === 'closed' ? 'bad' : 'unknown';
  return <article className="server-card" title={maskToken(url)}>
    <b>{t('srv.title')}</b>
    <small>{host}</small>
    <span className="hw-link">
      <em className={`hw-dot hw-dot--${state}`}>{t(`srv.socket.${feed.socket}`)}</em>
      <em className={`hw-dot hw-dot--${ago === null ? 'unknown' : ago <= 15 ? 'ok' : 'unknown'}`}>
        {ago === null ? t('srv.noData') : t('srv.lastData', { sec: ago, n: feed.count })}
      </em>
      <em className="hw-dot hw-dot--plain">{t('srv.devices', { n: devices })}</em>
    </span>
  </article>;
}
