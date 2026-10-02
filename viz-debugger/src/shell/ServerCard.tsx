/**
 * src/shell/ServerCard.tsx (261001 신설 — 백엔드 서버 카드)
 *
 * **서버도 붙어 있는지 칸으로 본다.** 처음에는 하드웨어 패널 맨 위에 임시로 얹었다. 서버는 장비가 아니라서
 * 그 자리가 맞는지 정하지 않았던 것이다.
 *
 * ## 261001 — 오른쪽 기둥의 제 칸으로 (지시 — 「하드웨어 카드 말고 다른 곳에」)
 *
 * 오른쪽 기둥이 **서버 / 하드웨어 / 기능** 셋이 됐다. 셋을 같은 높이로 나누지 않는다 — 서버는 하나뿐이고 한 줄이면
 * 되는데 1/3 을 주면 칸이 비고, 하드웨어 · 기능은 장비 두세 장 · 몇 줄만 보이게 줄어든다. 그래서 **서버 칸은
 * 내용만큼**이고 아래 둘이 1:1 을 나눠 갖는다.
 *
 * 여전히 **끌어서 마일스톤에 놓을 수 없다** — 장치 자리에 서버가 앉으면 안 된다.
 * 게이트웨이가 우리 컴퓨터의 목(`127.0.0.1` · `localhost`)이면 칸째 그리지 않는다 — 목은 서버가 아니다. 그러면
 * 하드웨어 · 기능이 다시 1:1 로 기둥을 채운다.
 *
 * **더블클릭하면 상세**(`ServerStatusOverlay`)를 연다. 장비 카드와 같은 손짓이다.
 */

import { useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import { maskToken, useGatewayFeed } from '../shared/gatewayFeed.ts';
import { ServerStatusOverlay } from './ServerStatusOverlay.tsx';

/** 우리 컴퓨터의 목 게이트웨이인가. */
export function isLocalGateway(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '[::1]';
  } catch {
    return true;
  }
}

/** 화면에 적을 서버 이름 — 주소의 호스트:포트. 주소가 깨져 있으면 토큰만 가린 원문. */
export function serverHost(url: string): string {
  try { return new URL(url).host; } catch { return maskToken(url); }
}

export function ServerCard() {
  useLang();
  useConnections();
  const feed = useGatewayFeed();
  const [open, setOpen] = useState(false);
  const url = connectionAddress('gateway', 'ws').trim();
  if (url === '' || isLocalGateway(url)) return null;
  const ago = feed.lastAtMs === null ? null : Math.max(0, Math.round((Date.now() - feed.lastAtMs) / 1000));
  const devices = Object.keys(feed.serverEntities).length;
  const state = feed.socket === 'open' ? 'ok' : feed.socket === 'closed' ? 'bad' : 'unknown';
  return <aside className="server-panel">
    <article className="server-card" title={t('srv.openHint')} onDoubleClick={() => setOpen(true)}>
      <header><b>{t('srv.title')}</b><small>{serverHost(url)}</small></header>
      <span className="hw-link">
        <em className={`hw-dot hw-dot--${state}`}>{t(`srv.socket.${feed.socket}`)}</em>
        <em className={`hw-dot hw-dot--${ago === null ? 'unknown' : ago <= 15 ? 'ok' : 'unknown'}`}>
          {ago === null ? t('srv.noData') : t('srv.lastData', { sec: ago, n: feed.count })}
        </em>
        <em className="hw-dot hw-dot--plain">{t('srv.devices', { n: devices })}</em>
      </span>
    </article>
    {/* 상세는 **형제로 얹는다** — 칸은 언마운트되지 않으므로 닫으면 같은 자리다 (`DeviceStatusOverlay` 와 같은 규칙). */}
    {open && <ServerStatusOverlay url={url} host={serverHost(url)} onClose={() => setOpen(false)} />}
  </aside>;
}
