/**
 * src/fixedcam/FixedCameraSection.tsx (261002 신설 — 고정 카메라)
 *
 * **하드웨어 카드 상세(더블클릭)의 고정 카메라 칸.** 그 주소에서 지금 들어오는 이미지를 그대로 띄운다 — 닫으면 끊긴다.
 * 보여 주는 부품은 로봇 카메라를 바로 보는 것과 같다(`DirectCamera`). 받는 방식(끝나지 않는 영상 · 한 장씩 새로)은
 * 주소로 기본을 정하고 사람이 바꾼다(`feedKindOf` — 주소만으로는 확실히 모른다).
 *
 * 장비 정보(배터리 등)는 아직 안 온다. 오지 않는 칸은 그리지 않는다 — 다른 카드와 같은 규칙이다.
 */

import { useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useConnections } from '../shared/connections.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';
import { DirectCamera } from '../media/views/DeviceCamera.tsx';
import { feedKindOf, fixedCameraUrl, type FeedKind } from './fixedCamera.ts';

export function FixedCameraSection({ entityId }: { entityId: string }) {
  useLang();
  useConnections();
  useConnectedDevices();
  const url = fixedCameraUrl(entityId);
  const [kind, setKind] = useState<FeedKind | null>(null);
  const seen = connectedDevice(entityId);
  if (url === null) return <p className="device-facts device-facts--none">{t('fcam.gone', { id: entityId })}</p>;
  const shown = kind ?? feedKindOf(url);
  return <>
    <dl className="device-facts">
      <div><dt>{t('fcam.factUrl')}</dt><dd><code>{url}</code></dd></div>
      <div><dt>{t('fcam.factLast')}</dt><dd>{seen === null
        ? t('fcam.notReceived')
        : t('hl.secondsAgo', { sec: Math.round((Date.now() - seen.lastSeenMs) / 1000) })}</dd></div>
    </dl>
    <section className="media-section device-cam device-cam--zoom">
      <header className="media-section__head">
        <h3>{t('fcam.title')}</h3>
        <label className="device-cam__pick">{t('fcam.kind')}
          <select value={shown} onChange={(event) => setKind(event.target.value as FeedKind)}>
            <option value="stream">{t('fcam.kindStream')}</option>
            <option value="frames">{t('fcam.kindFrames')}</option>
          </select>
        </label>
      </header>
      {/* 방식을 바꾸면 새로 붙는다 — 끝나지 않는 영상을 한 장씩 청하면 매번 처음부터 연다. */}
      <DirectCamera key={shown} url={url} frames={shown === 'frames'} live recordLabel={entityId} />
    </section>
  </>;
}
