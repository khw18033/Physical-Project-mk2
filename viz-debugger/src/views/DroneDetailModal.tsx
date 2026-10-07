/**
 * src/views/DroneDetailModal.tsx (261003 — 하드웨어 카드 상세보기 · 드론)
 *
 * 하드웨어 카드를 더블클릭했는데 **그 장비가 드론이면** `DeviceStatusOverlay` 가 이 판을 연다.
 * 머리줄 한 줄에 `id · [상태판][카메라 · 탐지][RTK][SAR 패스] · 닫기` 이고, 아래 한 칸이 탭마다 바뀐다.
 *
 * | 탭 | 내용 |
 * |---|---|
 * | 상태판 | 드론 파트의 `DroneDashZoom` — 뷰 노드 「드론 상태판」의 확대와 같은 것 |
 * | 카메라 · 탐지 | 기존 상세보기의 두 칸만 — 기체 카메라(`DirectCamera`) · 객체 탐지 추론(`VisionDeviceSection`) |
 * | RTK | `RtkZoom` |
 * | SAR 패스 | `SarPassZoom` **보기 전용** — 시작 · 중단은 아직 이 창에 연결하지 않았다 |
 *
 * ## 세 화면 모두 `deviceId` 로 못 박는다
 *
 * 뷰 노드로 쓸 때는 장비를 안에서 고른다(첫 장비 · 명령 대상). 카드에서 열 때 그렇게 두면 드론이 둘일 때
 * x500-002 카드를 열고 x500-001 을 보게 된다 — 카드가 고른 장비가 곧 이 판의 장비다.
 *
 * ## 안 보이는 탭은 그리지 않는다
 *
 * CSS 로 숨기지 않고 조건부로 그린다. 카메라 탭을 떠나면 `<img>` 가 내려가 연결이 끊긴다 — 상세보기의
 * 「닫으면 끊긴다」와 같은 규칙이다. SAR 탭의 데이터 서버 조회도 그 탭이 열려 있을 때만 돈다.
 *
 * 크기는 탭과 상관없이 고정이다(`.device-modal--drone`) — 탭마다 내용 높이가 달라 창이 출렁이지 않게.
 */

import { useState, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { deviceCandidates, subscribeDeviceIdentity } from '../physical/deviceIdentity.ts';
import { useFcxReports } from '../shared/fcxStatus.ts';
import { directCameraUrl } from '../physical/cameraView.ts';
import { DirectCamera } from '../media/views/DeviceCamera.tsx';
import { VisionDeviceSection } from '../vision/views/VisionViews.tsx';
import { DroneDashZoom } from '../dronedash/DroneDash.tsx';
import { RtkZoom } from '../sar/RtkView.tsx';
import { SarPassZoom } from '../sar/SarPassView.tsx';

const TABS = ['dash', 'camera', 'rtk', 'sar'] as const;
type DroneTab = (typeof TABS)[number];

/**
 * **이 장비가 드론인가.** 장비가 밝힌 종류(`kind`)가 `drone` 이면 드론이다 — 카메라 주소(`cameraView.ts`)와 같은 기준.
 * 종류를 아직 못 받았어도 FC 확장 텔레메트리(`…/fcx`)를 보낸 장비면 드론으로 본다 — 그 토픽은 드론만 낸다.
 *
 * 전역판(`deviceIdentityFor`)을 쓰지 않는다 — 한 브로커에 드론이 둘이면 그쪽은 `null` 이 된다.
 */
export function useIsDrone(deviceId: string): boolean {
  const kind = useSyncExternalStore(subscribeDeviceIdentity,
    () => deviceCandidates().find((c) => c.deviceId === deviceId)?.kind ?? null);
  const fcx = useFcxReports();
  return kind === 'drone' || fcx[deviceId] !== undefined;
}

export function DroneDetailModal({ deviceId, source, onClose }: {
  deviceId: string;
  source: string;
  onClose(): void;
}) {
  useLang();
  const [tab, setTab] = useState<DroneTab>('dash');
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal device-modal device-modal--drone" role="dialog" aria-label={t('dso.aria', { id: deviceId })}>
      <header>
        <div>
          <h2>{deviceId}</h2>
          <small>{t('dso.source', { source })}</small>
        </div>
        <nav className="drone-modal__tabs" role="tablist" aria-label={t('dso.drone.tabs', { id: deviceId })}>
          {TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item}
            onClick={() => setTab(item)}>{t(`dso.drone.tab.${item}`)}</button>)}
        </nav>
        <button type="button" onClick={onClose}>{t('dso.1')}</button>
      </header>
      <div className="drone-modal__body" role="tabpanel">
        {tab === 'dash' && <DroneDashZoom deviceId={deviceId} />}
        {tab === 'camera' && <DroneCameraTab deviceId={deviceId} />}
        {tab === 'rtk' && <RtkZoom deviceId={deviceId} />}
        {tab === 'sar' && <SarPassZoom deviceId={deviceId} readOnly />}
      </div>
    </section>
  </div>;
}

/** 기존 상세보기에서 떼어 온 두 칸 — 기체 카메라 원본 · 객체 탐지 추론. 드론 카메라는 한 대라 위치 칸이 없다. */
function DroneCameraTab({ deviceId }: { deviceId: string }) {
  useLang();
  const direct = directCameraUrl(deviceId, 'front');
  return <>
    <section className="media-section device-cam device-cam--zoom">
      <header className="media-section__head"><h3>{t('dso.drone.camera')}</h3></header>
      {direct === null
        ? <p className="drone-modal__empty">{t('dso.drone.noCamera')}</p>
        : <DirectCamera url={direct.url} frames={direct.kind === 'frames'} live recordLabel={deviceId} />}
    </section>
    <VisionDeviceSection entityId={deviceId} />
  </>;
}
