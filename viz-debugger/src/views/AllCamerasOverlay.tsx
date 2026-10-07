/**
 * src/views/AllCamerasOverlay.tsx (261002 신설 — 하드웨어 패널 「전체 카메라 확인」)
 *
 * **붙어 있는 장비 여럿의 카메라를 한 화면에서 본다.** 장비가 늘면 카드를 하나씩 더블클릭해 상세를 여는 것으로는 카메라
 * 상황을 한눈에 못 본다. 그래서 화면을 거의 다 차지하는 판 하나에 **장비마다 한 칸**을 둔다.
 *
 * ## 무엇이 「카메라가 있는 장비」인가 — 하드웨어 카드 목록 중
 *
 *   고정 카메라      연결 관리에 적은 이미지 주소 (`src/fixedcam/`)
 *   로봇 카메라      로봇 노드에서 바로 받는 길이 있는 장비(Go1 뷰어 · 드론 영상 말단 — `physical/cameraView.ts`)
 *   추론 스트림      추론 서버의 포트가 묶인 장비 (`vision/binding.ts`)
 *
 * 셋 중 하나라도 있으면 칸이 선다. 없는 장비는 맨 아래에 이름만 적는다 — 「안 보인다」가 「카메라가 없다」인지 「화면이 못
 * 그렸다」인지 가른다.
 *
 * ## 고르는 것은 카드 상세와 같은 것이다
 *
 * 추론 칸은 카드 상세의 그 부품(`VisionDeviceSection`)을 요약 표만 빼고 그대로 쓴다 — 포트 · 모델 · 원본 같이 보기를 여기서도
 * 고르고, 저장 키가 같아서 카드 상세와 **같은 고름**이다. 로봇 카메라의 위치 고름만 이 판 안에서 칸마다 따로 든다
 * (카드 상세도 저장하지 않는다).
 *
 * 규칙은 다른 오버레이와 같다 — `.modal-backdrop` 위 · 뒤를 교체하지 않는다 · 닫는 길은 닫기 버튼 · Esc · 배경 누르기.
 * **닫으면 영상이 다 끊긴다**(`<img>` 가 사라진다). 다시보기 중이면 영상을 띄우지 않는다 — 지금 영상을 지난 판 자리에
 * 띄우면 그때 본 것으로 읽힌다(카메라 노드와 같은 규칙).
 */

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useConnections } from '../shared/connections.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';
import { useDeviceCardIds } from '../shared/registry.ts';
import { useReplayTarget } from '../record/replayMode.ts';
import { DirectCamera } from '../media/views/DeviceCamera.tsx';
import { CAMERA_POSITIONS, type CameraPosition } from '../media/cameraChoice.ts';
import { directCameraUrl } from '../physical/cameraView.ts';
import { feedKindOf, fixedCameraUrl, isFixedCamera, type FeedKind } from '../fixedcam/fixedCamera.ts';
import { VisionDeviceSection } from '../vision/views/VisionViews.tsx';
import { Virtual3D } from '../virtualmap/Virtual3D.tsx';
import { isTwinDevice } from '../virtualmap/twinDevice.ts';
import { fitCameraHeight } from './cameraFit.ts';
import { visionBases } from '../vision/visionClient.ts';
import { holdAllVisionSources, useVisionSources } from '../vision/store.ts';
import {
  deviceBrokerHost, deviceDirectBase, resolveVisionBinding, useVisionBindingChoices,
} from '../vision/binding.ts';

/** 카드의 작은 글씨와 같은 갈래 — 이 판에서도 장비가 어느 길로 붙었는지 적는다. */
function originKey(entityId: string): string {
  const source = connectedDevice(entityId)?.source;
  return source === 'camera' ? 'ms.fixedCameraDevice' : source === 'twin' ? 'ms.twinDevice' : source === 'server' ? 'ms.serverDevice' : 'ms.connectedDevice';
}

/** 고정 카메라 · 로봇 카메라 — 장비에서(또는 서버 링크에서) 바로 받는 영상 한 칸. */
function DirectFeed({ entityId }: { entityId: string }) {
  useLang();
  const [position, setPosition] = useState<CameraPosition>('front');
  const [kind, setKind] = useState<FeedKind | null>(null);
  // 261007 — 3D 가상환경 PC. 노드 확대와 같은 화면이다(상공 카메라마다 녹화 버튼이 선다).
  if (isTwinDevice(entityId)) return <section className="all-cams__feed">
    <header><b>{t('v3d.title')}</b></header>
    <Virtual3D zoom recordPrefix={entityId} />
  </section>;
  const fixedUrl = fixedCameraUrl(entityId);
  if (fixedUrl !== null) {
    const shown = kind ?? feedKindOf(fixedUrl);
    return <section className="all-cams__feed">
      <header>
        <b>{t('fcam.title')}</b>
        <label>{t('fcam.kind')}
          <select value={shown} onChange={(event) => setKind(event.target.value as FeedKind)}>
            <option value="stream">{t('fcam.kindStream')}</option>
            <option value="frames">{t('fcam.kindFrames')}</option>
          </select>
        </label>
      </header>
      <DirectCamera key={shown} url={fixedUrl} frames={shown === 'frames'} live compact recordLabel={entityId} />
    </section>;
  }
  const direct = directCameraUrl(entityId, position);
  if (direct === null) return null;
  return <section className="all-cams__feed">
    <header>
      <b>{t('dso.robotCamera')}</b>
      {/* 카메라가 한 대인 길(드론 말단)은 위치를 안 가린다 — 상세와 같은 규칙. */}
      {direct.kind === 'stream' && <label>{t('dcam.position')}
        <select value={position} onChange={(event) => setPosition(event.target.value as CameraPosition)}>
          {CAMERA_POSITIONS.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>}
    </header>
    <DirectCamera url={direct.url} frames={direct.kind === 'frames'} live compact recordLabel={`${entityId}_${position}`} />
  </section>;
}

/** 칸 안의 영상 요소 — 높이를 `--cam-h` 로 받는 것들. */
const CAM_SELECTOR = '.all-cams__feed .device-cam__canvas, .vision-cell img';

export function AllCamerasOverlay({ onClose }: { onClose(): void }) {
  useLang();
  useConnections();
  useConnectedDevices();
  const ids = useDeviceCardIds();
  const sources = useVisionSources();
  const choices = useVisionBindingChoices();
  const replaying = useReplayTarget();
  // 장비마다 포트를 맞대 보려면 포트 전부의 `/health` 가 있어야 한다 — 하드웨어 카드와 같은 붙잡기다.
  useEffect(() => holdAllVisionSources(), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  /**
   * **영상 높이 맞추기.** 판 · 칸의 크기가 바뀔 때마다(창 크기 · 장비가 붙고 빠짐 · 모델을 더 고름) 다시 잰다. 칸마다 지금 높이에서
   * 영상 몫을 빼 「영상이 아닌 부분」을 얻고(`fitCameraHeight`), 2px 넘게 달라질 때만 바꾼다 — 바꾸면 칸 크기가 다시 바뀌어
   * 관찰자가 또 부르는데, 그때는 같은 값이 나와 멈춘다.
   */
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [camH, setCamH] = useState(360);
  const camHRef = useRef(camH);
  camHRef.current = camH;
  useLayoutEffect(() => {
    const body = bodyRef.current;
    if (body === null) return undefined;
    const fit = () => {
      const grid = body.querySelector<HTMLElement>('.all-cams__grid');
      if (grid === null) return;
      const tiles = [...grid.querySelectorAll<HTMLElement>('.all-cams__tile')];
      if (tiles.length === 0) return;
      // 줄은 칸의 윗변으로 가른다 — 몇 열인지는 CSS(auto-fill)가 창 너비로 정한다.
      const rows = new Map<number, number>();
      for (const tile of tiles) {
        // 한 칸에 영상 줄은 하나다(추론 모델은 가로로 선다 — CSS). 영상이 아직 없는 칸은 전부가 「영상이 아닌 부분」이다.
        const hasCam = tile.querySelector(CAM_SELECTOR) !== null;
        const overhead = tile.offsetHeight - (hasCam ? camHRef.current : 0);
        rows.set(tile.offsetTop, Math.max(rows.get(tile.offsetTop) ?? 0, overhead));
      }
      const style = getComputedStyle(body);
      const gap = parseFloat(getComputedStyle(grid).rowGap) || 0;
      // 판 안에서 그리드 밖의 것(「카메라가 없는 장비」 줄)도 자리를 쓴다.
      const others = [...body.children].filter((child) => child !== grid).reduce((sum, child) => sum + (child as HTMLElement).offsetHeight + (parseFloat(style.rowGap) || 0), 0);
      const available = body.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - others;
      // 영상이 자기 비율대로 칸 너비를 채울 때의 높이 — 그보다 키우면 검은 띠만 는다. 아직 한 장도 안 왔으면 모른다.
      let needed: number | null = null;
      body.querySelectorAll<HTMLImageElement>('img').forEach((img) => {
        if (!img.matches(CAM_SELECTOR) || img.naturalWidth === 0 || img.clientWidth === 0) return;
        const want = (img.clientWidth * img.naturalHeight) / img.naturalWidth;
        needed = needed === null ? want : Math.max(needed, want);
      });
      const next = fitCameraHeight(available, [...rows.values()], gap, needed);
      if (Math.abs(next - camHRef.current) > 2) setCamH(next);
    };
    const observer = new ResizeObserver(fit);
    observer.observe(body);
    const watchTiles = () => body.querySelectorAll('.all-cams__tile').forEach((tile) => observer.observe(tile));
    watchTiles();
    // 칸이 새로 생기면(장비가 붙음) 그 칸도 지켜본다.
    const mutations = new MutationObserver(() => { watchTiles(); fit(); });
    mutations.observe(body, { childList: true, subtree: true });
    // 영상 첫 장이 오면 비율을 안다 — `load` 는 거품이 안 올라오므로 잡는 단계에서 듣는다.
    body.addEventListener('load', fit, true);
    fit();
    return () => { observer.disconnect(); mutations.disconnect(); body.removeEventListener('load', fit, true); };
  }, []);

  const bases = visionBases();
  const rows = ids.map((id) => {
    const binding = resolveVisionBinding(choices[id] ?? null, deviceBrokerHost(id), sources, bases, deviceDirectBase(id));
    const twin = isTwinDevice(id);
    const direct = twin || (isFixedCamera(id) ? fixedCameraUrl(id) !== null : directCameraUrl(id, 'front') !== null);
    // 주소가 같은 포트가 여럿이면(고르지 않은 채) 칸을 세운다 — 여기서 고르면 된다. 「연결 안 함」은 추론을 끈 것이다.
    // 3D 가상환경은 객체 탐지를 붙이지 않는다(261007 — 고정 카메라와 같되 탐지 없음).
    const vision = !twin && (binding.base !== null || binding.how === 'ambiguous');
    return { id, twin, direct, vision, show: direct || vision };
  });
  const shown = rows.filter((row) => row.show);
  const without = rows.filter((row) => !row.show).map((row) => row.id);

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal all-cams" role="dialog" aria-label={t('acam.title')}>
      <header>
        <div>
          <h2>{t('acam.title')}</h2>
          <small>{t('acam.count', { n: shown.length, total: ids.length })}</small>
        </div>
        <button onClick={onClose}>{t('dso.1')}</button>
      </header>
      <div className="all-cams__body" ref={bodyRef} style={{ '--cam-h': `${camH}px` } as CSSProperties}>
        {replaying !== null
          ? <p className="vn-line vn-dim">{t('dcam.replay')}</p>
          : shown.length === 0
            ? <p className="hardware-panel__none">{ids.length === 0 ? t('ms.noConnectedDevice') : t('acam.none')}</p>
            /* **장비는 세로로 쌓는다** (261002 지시). 가로로 나란히 두면 칸마다 원본 · 추론이 다시 반씩 나눠 영상이 작고 여백이 컸다. */
            : <div className="all-cams__grid">
                {shown.map((row) => <article key={row.id} className="all-cams__tile">
                  {/* **장비 구분이 먼저다** — 칸마다 머리에 장비 id 와 붙은 길을 크게 적는다. */}
                  <header className="all-cams__head">
                    <b>{row.id}</b>
                    <small>{t(originKey(row.id))}</small>
                  </header>
                  {/* **바로 받는 영상과 추론은 가로로 나란히** (261002 지시). 카메라 영상이 가로로 긴 그림이 아니라서 위아래로
                      쌓으면 칸만 길어진다. 바로 받는 영상이 없는 장비는 추론이 칸 너비를 다 쓴다. */}
                  <div className={`all-cams__pair${row.direct && !row.twin ? ' all-cams__pair--2' : ''}`}>
                    {row.direct && <DirectFeed entityId={row.id} />}
                    {/* 추론 칸 — 포트 · 모델 · 원본 고르기와 영상. 바로 받는 영상만 있는 장비도 포트를 여기서 묶을 수 있다. */}
                    {!row.twin && <VisionDeviceSection entityId={row.id} compact />}
                  </div>
                </article>)}
              </div>}
        {without.length > 0 && <p className="all-cams__without">{t('acam.without', { list: without.join(', ') })}</p>}
      </div>
      <footer>
        <span>{t('acam.footer')}</span>
      </footer>
    </section>
  </div>;
}
