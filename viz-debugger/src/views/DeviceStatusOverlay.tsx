/**
 * src/views/DeviceStatusOverlay.tsx (260904 — 추가 개선 2)
 *
 * 하드웨어 카드를 **더블클릭하면 그 대상의 상태**를 연다. 새 기능이 아니라
 * `VZ-D-07`(대상 배정과 **대상 상태 조회**)의 미구현분이다 — 카드가 드래그로 배정만 되고
 * 눌러도 아무 일이 없었다.
 *
 * ## 규칙은 `VZ-N-05`(확대) 그대로다
 *
 * | 조건 | 여기서 |
 * |---|---|
 * | 오버레이다 | `ZoomOverlay`·`ActionModal` 과 같은 `.modal-backdrop` 위에 얹는다 |
 * | 뒤를 교체하지 않는다 | 마일스톤 목록·하드웨어 목록은 언마운트되지 않는다. 형제로 얹힐 뿐이다 |
 * | 동시 하나 | 상태가 **문자열 하나**(`statusDeviceId`)다. 배열이면 둘이 열린다 |
 * | 닫는 길이 둘 이상 | 닫기 버튼 · Esc · 배경 누르기 |
 *
 * ## 지어내지 않는다 — 다만 오는 것은 보여 준다 (260910)
 *
 * 8/31 결정은 registry 장비의 실측값을 **지어내지 않는다**였고, 그건 값을 줄 채널이
 * 없었기 때문이다. 이제 `zoneA/<type>/<id>/{status,state}` 가 온다.
 *
 * **지어내지 않는 것은 그대로**이고, 안 오는 칸을 「연결 예정」 자리표시로 채우던 것을
 * 걷어냈다 — 시연 화면에서 그 문구가 연결 전 테스트처럼 보인다는 지적이 있었다.
 * 오는 값만 적고, 안 오는 것은 **아예 안 그린다.**
 *
 * 카메라 연결 상태는 여전히 MQTT 로 안 나온다(연동 가이드 §3-4) — 노드 상태 요약에
 * 필드가 추가돼야 한다. 그 칸도 자리표시 대신 없앴다.
 *
 * ## 260921 — 카메라 칸이 돌아왔다
 *
 * 위 문단이 없앤 그 칸이다. **줄 값이 없어서 뺐던 것**이고 이제 생겼다 — `/media` 소켓이
 * 바이트를 준다(`src/media/`). 백엔드도 카메라 상태를 **「VZ-D-07 대상 상태 조회의 한 칸」**
 * 으로 봤다(`vz-media-interface.md` §8).
 *
 * MQTT 로 오는 **연결 상태**는 여전히 없다. 이 칸이 말하는 것은 다른 것이다 —
 * 「지금 이 소켓으로 바이트가 흐르는가」이고, 그건 우리가 세어서 안다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { useEffect, useState, useSyncExternalStore } from 'react';
import type { Hardware } from '../model/types.ts';
import { DeviceStrip } from './DeviceStrip.tsx';
import { DeviceFacts } from '../physical/DeviceFacts.tsx';
import { MediaSection } from '../media/views/MediaSection.tsx';
import { DirectCamera } from '../media/views/DeviceCamera.tsx';
import { CAMERA_POSITIONS, type CameraPosition } from '../media/cameraChoice.ts';
import { directCameraUrl } from '../physical/cameraView.ts';
import { VisionDeviceSection } from '../vision/views/VisionViews.tsx';
import { FixedCameraSection } from '../fixedcam/FixedCameraSection.tsx';
import { isFixedCamera } from '../fixedcam/fixedCamera.ts';
import { TwinSection } from '../virtualmap/TwinSection.tsx';
import { isTwinDevice, useTwinFacts } from '../virtualmap/twinDevice.ts';
import { DroneDetailModal, useIsDrone } from './DroneDetailModal.tsx';
import { deviceCandidates, subscribeDeviceIdentity } from '../physical/deviceIdentity.ts';
import { isManualRobot } from '../physical/manualControl.ts';
import { ManualControlTab } from './ManualControlTab.tsx';

const ROBOT_TABS = ['status', 'manual'] as const;
type RobotTab = (typeof ROBOT_TABS)[number];

export function DeviceStatusOverlay({ deviceId, device, source, onClose }: {
  deviceId: string;
  /** 시나리오에 실측 목록이 실려 있을 때만 있다. 대본 세계에서는 없다. */
  device?: Hardware;
  /** 이 목록이 어디서 왔는가. 화면이 목임을 감추지 않는다. */
  source: string;
  onClose(): void;
}) {
  useLang();
  /**
   * **로봇 카메라를 카드에서 바로** (260928). Go1 이면 로봇 노드(pi7)의 카메라 뷰어에서 바로 받는다 —
   * 백엔드 `/media` 는 실물 영상이 아직 안 오는 길이라(`physical/cameraView.ts`) 그 칸만 두면 늘 비어 있다.
   * 주소를 못 만드는 장비(드론 등)는 이 칸이 없고, 아래 `/media` 칸이 그대로 연다.
   */
  const [position, setPosition] = useState<CameraPosition>('front');
  const directUrl = directCameraUrl(deviceId, position);
  /**
   * **고정 카메라** (261002). 로봇이 아니라 서버 링크에서 이미지를 받는 상대라 장비 상태 · 로봇 카메라 · `/media` 칸이
   * 다 맞지 않는다 — 그 셋 대신 받는 이미지를 띄우고, 추론 스트림 칸은 로봇과 같은 것을 쓴다.
   */
  const fixedCamera = isFixedCamera(deviceId);
  /**
   * **3D 가상환경 PC** (261007). 고정 카메라와 같은 취급이다 — 보기만 한다. 장비 상태 · 로봇 카메라 · 추론 · `/media` 칸 대신
   * 3D 가상환경 노드 확대와 같은 화면을 띄운다(`TwinSection`).
   */
  useTwinFacts();
  const twin = isTwinDevice(deviceId);
  const viewOnly = fixedCamera || twin;
  /**
   * **드론이면 탭 판** (261003). 상태판 · 카메라 · 탐지 · RTK · SAR 패스를 탭으로 오간다(`DroneDetailModal.tsx`).
   * 닫는 길(Esc)은 아래 효과가 그대로 맡는다 — 갈래를 효과 뒤에 둔다.
   */
  const drone = useIsDrone(deviceId);
  /**
   * **로봇이면 수동 제어 탭** (261005). 드론 · 고정 카메라는 아니다 — 판정은 장비가 말한 것으로(`isManualRobot`).
   * 지금 상세보기 내용은 첫 탭에 그대로 있다. 탭을 옮겨도 수동 제어는 켜진 채다 — 키 처리기는 앱에 걸려 있다.
   */
  const facts = useSyncExternalStore(subscribeDeviceIdentity,
    () => deviceCandidates().find((candidate) => candidate.deviceId === deviceId) ?? null);
  const robot = isManualRobot(facts, { drone, fixedCamera: viewOnly });
  const [tab, setTab] = useState<RobotTab>('status');
  // 여는 길이 둘(더블클릭·앞으로 늘 수 있는 다른 경로)이면 닫는 길도 둘 이상이어야 한다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  if (drone && !viewOnly) return <DroneDetailModal deviceId={deviceId} source={source} onClose={onClose} />;

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal device-modal" role="dialog" aria-label={t('dso.aria', { id: deviceId })}>
      <header>
        <div>
          <h2>{t('dso.title', { id: deviceId })}</h2>
          <small>{device ? `${device.kind} · ` : ''}{t('dso.source', { source })}</small>
        </div>
        {robot && <nav className="drone-modal__tabs" role="tablist" aria-label={t('dso.drone.tabs', { id: deviceId })}>
          {ROBOT_TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item}
            onClick={() => setTab(item)}>{t(`dso.robot.tab.${item}`)}</button>)}
        </nav>}
        <button onClick={onClose}>{t('dso.1')}</button>
      </header>
      {robot && tab === 'manual' ? <ManualControlTab deviceId={deviceId} /> : <>
      {/* **오는 값만 적는다** (260910). 안 오는 칸은 자리표시로 채우지 않고 아예 안 그린다. */}
      {twin ? <TwinSection entityId={deviceId} /> : fixedCamera ? <FixedCameraSection entityId={deviceId} /> : <DeviceFacts entityId={deviceId} />}
      {device !== undefined && <DeviceStrip device={device} />}
      {!viewOnly && directUrl !== null && <section className="media-section device-cam device-cam--zoom">
        <header className="media-section__head">
          <h3>{t('dso.robotCamera')}</h3>
          {/* 카메라가 한 대인 길(드론 말단)은 위치를 안 가린다 — 칸을 두면 바꿔도 아무 일이 없다. */}
          {directUrl.kind === 'stream' && <label className="device-cam__pick">{t('dcam.position')}
            <select value={position} onChange={(event) => setPosition(event.target.value as CameraPosition)}>
              {CAMERA_POSITIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>}
        </header>
        {/* 닫으면 끊긴다 — 모달이 내려가면 `<img>` 가 사라지고 연결이 닫힌다. */}
        <DirectCamera url={directUrl.url} frames={directUrl.kind === 'frames'} live recordLabel={`${deviceId}_${position}`} />
      </section>}
      {/* 261001 — 객체 탐지 추론 스트림. 포트를 고르고(자동 맞춤이 기본) 모델별 오버레이를 연다. 닫으면 끊긴다. */}
      {!twin && <VisionDeviceSection entityId={deviceId} />}
      {/* 카메라 영상 — **닫으면 끊긴다.** 붙는 것이 켜기이고 끊는 것이 끄기다.
          로봇 카메라를 바로 보고 있으면 이 칸은 접는다 — 같은 영상을 두 길로 동시에 열 이유가 없다. */}
      {viewOnly ? null : directUrl === null
        ? <MediaSection deviceId={deviceId} />
        : <details className="media-section__fold"><summary>{t('dso.mediaFold')}</summary><MediaSection deviceId={deviceId} /></details>}
      </>}
      <footer>
        <span>{t('dso.2')}</span>
      </footer>
    </section>
  </div>;
}
