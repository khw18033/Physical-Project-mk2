/**
 * src/virtualmap/TwinSection.tsx (261007 신설 — 3D 가상환경 하드웨어 카드 상세)
 *
 * **하드웨어 카드 상세(더블클릭)의 3D 가상환경 칸.** 3D 가상환경 노드의 확대에서 할 수 있는 것을 **그대로** 둔다(261007 지시) —
 * 대본이 붙인 영상 재생(`CuedVideo`) · 상공 카메라 고르기 · 확대 · 회전 · 높이 · 화각 · 틀 화면 조작이 같은 부품이다.
 * 수동 제어 · 객체 탐지는 없다(고정 카메라와 같은 취급).
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useConnectedDevices, connectedDevice } from '../shared/connectedDevices.ts';
import { CuedVideo } from '../imagery/CuedVideo.tsx';
import { Virtual3D } from './Virtual3D.tsx';
import { useTwinFacts } from './twinDevice.ts';

export function TwinSection({ entityId }: { entityId: string }) {
  useLang();
  useConnectedDevices();
  const facts = useTwinFacts();
  const seen = connectedDevice(entityId);
  return <>
    <dl className="device-facts">
      <div><dt>{t('twin.factUrl')}</dt><dd><code>{facts?.url ?? '—'}</code></dd></div>
      <div><dt>{t('twin.factName')}</dt><dd>{facts?.nameFrom === 'tailscale' ? t('twin.nameTailscale') : t('twin.nameAddress')}</dd></div>
      <div><dt>{t('twin.factKind')}</dt><dd>{facts?.kind === 'topcam' ? t('twin.kindTopcam') : t('twin.kindPage')}</dd></div>
      <div><dt>{t('fcam.factLast')}</dt><dd>{seen === null
        ? t('fcam.notReceived')
        : t('hl.secondsAgo', { sec: Math.round((Date.now() - seen.lastSeenMs) / 1000) })}</dd></div>
    </dl>
    <section className="media-section twin-section">
      <header className="media-section__head"><h3>{t('v3d.title')}</h3></header>
      <CuedVideo target="virtual-3d" storageKey="virtual-3d.video" zoom><Virtual3D zoom recordPrefix={entityId} /></CuedVideo>
    </section>
  </>;
}
