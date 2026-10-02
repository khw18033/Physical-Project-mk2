/**
 * src/virtualmap/Virtual3D.tsx (260929 신설 — 3D 가상환경 뷰 노드)
 *
 * **3D 디지털트윈 가상환경을 띄운다.** 주소는 연결 관리의 「3D 가상환경」 칸이고 기본값은 사용자가 준 주소다
 * (`shared/connections.ts` 의 `virtual-3d`). 모든 편 팔레트에 선다.
 *
 * 가상 맵 노드(Unity · 2D)와 다른 노드다 — 그쪽은 자리 편의 경로 · 장치를 그리고, 이것은 가상환경 화면을
 * 그대로 띄운다. 화면은 이 틀과 말을 주고받지 않는다 — 명령 출구는 여전히 하나다.
 *
 * 카드에서는 누름을 막는다(끌기가 먼저다). 조작은 확대에서 한다 — 가상 맵의 Unity 틀과 같은 규칙이다.
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';

export function Virtual3D({ zoom = false }: { zoom?: boolean }) {
  useLang();
  useConnections();
  const url = connectionAddress('virtual-3d', 'base').trim();
  if (url === '') return <p className="vn-line vn-dim">{t('v3d.empty')}</p>;
  return <div className={`vmap vmap--unity v3d${zoom ? ' vmap--zoom' : ''}`}>
    <iframe
      className="vmap__unity v3d__frame"
      src={url}
      title={t('v3d.title')}
      allow="fullscreen; xr-spatial-tracking"
      style={zoom ? undefined : { pointerEvents: 'none' }}
    />
    <p className="vn-line vn-dim">{t('v3d.line', { url })}{zoom ? '' : ` · ${t('v3d.zoomHint')}`}</p>
  </div>;
}
