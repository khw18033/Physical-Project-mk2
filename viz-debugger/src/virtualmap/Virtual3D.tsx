/**
 * src/virtualmap/Virtual3D.tsx (260929 신설 — 3D 가상환경 뷰 노드)
 *
 * **3D 디지털트윈 가상환경을 띄운다.** 주소는 연결 관리의 「3D 가상환경」 칸이고 기본값은 사용자가 준 주소다
 * (`shared/connections.ts` 의 `virtual-3d`). 모든 편 팔레트에 선다.
 *
 * 가상 맵 노드(Unity · 2D)와 다른 노드다 — 그쪽은 자리 편의 경로 · 장치를 그리고, 이것은 가상환경 화면을
 * 그대로 띄운다. 화면은 이 틀과 말을 주고받지 않는다 — 명령 출구는 여전히 하나다.
 *
 * 261003 — 주소가 Unity 상공 카메라 서버(`CameraMjpegServer`)면 틀 대신 `TopCamView` 를 그린다(시점 조절 포함).
 *
 * 카드에서는 누름을 막는다(끌기가 먼저다). 조작은 확대에서 한다 — 가상 맵의 Unity 틀과 같은 규칙이다.
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import { TopCamView, useTopCamProbe } from './TopCamView.tsx';
import { RecordFrame } from '../record/RecordFrame.tsx';

export function Virtual3D({ zoom = false, recordPrefix = '3d' }: {
  zoom?: boolean;
  /** 261007 — 녹화 파일 이름 앞머리. 하드웨어 카드에서 열면 그 PC 이름이다. */
  recordPrefix?: string;
}) {
  useLang();
  useConnections();
  const url = connectionAddress('virtual-3d', 'base').trim();
  // 261003 — 주소가 Unity 상공 카메라 서버면 틀 대신 영상 + 시점 조절을 그린다 (TopCamView.tsx)
  const probe = useTopCamProbe(url);
  if (url === '') return <p className="vn-line vn-dim">{t('v3d.empty')}</p>;
  if (probe.kind === 'topcam') return <TopCamView url={url} probe={probe} zoom={zoom} recordPrefix={recordPrefix} />;
  const frame = <iframe
    className="vmap__unity v3d__frame"
    src={url}
    title={t('v3d.title')}
    allow="fullscreen; xr-spatial-tracking"
    style={zoom ? undefined : { pointerEvents: 'none' }}
  />;
  // 261007 — 확대에서는 녹화 버튼을 얹는다(틀 화면도 보이는 그대로 찍힌다 — `screenRecord.ts`).
  return <div className={`vmap vmap--unity v3d${zoom ? ' vmap--zoom' : ''}`}>
    {zoom ? <RecordFrame label={recordPrefix}>{frame}</RecordFrame> : frame}
    <p className="vn-line vn-dim">{t('v3d.line', { url })}{zoom ? '' : ` · ${t('v3d.zoomHint')}`}</p>
  </div>;
}
