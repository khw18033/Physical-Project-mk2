/**
 * src/views/AllDevicesOverlay.tsx (261110 — 「전체 카메라 확인」 → 「전체 장치 확인」)
 *
 * **붙어 있는 장비 전부를 한 화면에서 본다.** 머리줄의 탭 둘로 가른다.
 *
 *   카메라      **영상 하나가 한 칸**이다 — 장비 하나가 아니다. 드론 cam0 · cam1, 추론 모델마다 · 원본 보기가 각자 한 칸이다.
 *   장치 상태   **장비 하나가 한 칸**이다 — 드론은 상태판 축약판, Go1 등은 같은 모양의 상태판(`GroundDash`),
 *               고정 카메라 · 3D 가상환경은 카드가 아는 것만 글로.
 *
 * ## 한 화면에 네 칸 (2×2), 넘치면 슬라이더로 한 칸씩
 *
 * 칸 크기를 고정해 영상이 들쭉날쭉하지 않게 한다. 다섯 칸째부터는 아래 슬라이더 · ◀ ▶ 로 **한 칸씩** 민다(지시 — 페이지가
 * 아니다). 칸의 키가 영상마다 고정이라 밀어도 화면에 남는 칸은 다시 붙지 않는다. **화면에서 밀려난 칸은 그리지 않는다** —
 * `<img>` 가 내려가 연결이 끊긴다. 영상 열 개를 다 열어 둔 채 넷만 보이는 일이 없다.
 *
 * ## 장비 단위 고르기는 그리드 밖에
 *
 * 추론 포트 · 모델 · 원본 보기, 로봇 카메라 위치, 고정 카메라 받는 방식은 **장비의** 고름이라 영상 칸 안에 둘 자리가 없다.
 * 그리드 위 접는 줄(「장비별 영상 고르기」)에 모은다. 추론 고름의 저장 키가 카드 상세와 같다 — 같은 고름이다.
 *
 * 규칙은 다른 오버레이와 같다 — `.modal-backdrop` 위 · 뒤를 교체하지 않는다 · 닫는 길은 닫기 버튼 · Esc · 배경 누르기.
 * **안 보이는 탭은 그리지 않는다** — 장치 상태 탭에 있으면 영상이 다 끊긴다. 다시보기 중이면 영상을 띄우지 않는다.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useConnections } from '../shared/connections.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';
import { useDeviceCardIds } from '../shared/registry.ts';
import { useReplayTarget } from '../record/replayMode.ts';
import { DirectCamera } from '../media/views/DeviceCamera.tsx';
import { CAMERA_POSITIONS, type CameraPosition } from '../media/cameraChoice.ts';
import { directCameraPositions, effectiveCameraPosition, useDirectCameraSourcesMany, type LabeledCameraSource } from '../physical/cameraView.ts';
import { feedKindOf, fixedCameraUrl, isFixedCamera, type FeedKind } from '../fixedcam/fixedCamera.ts';
import { CameraStateDash } from '../fixedcam/CameraStateView.tsx';
import { VisionDeviceControls, VisionStream, visionStreamCells } from '../vision/views/VisionViews.tsx';
import { Virtual3D } from '../virtualmap/Virtual3D.tsx';
import { isTwinDevice, useTwinFacts } from '../virtualmap/twinDevice.ts';
import { visionBases, modelLive } from '../vision/visionClient.ts';
import { holdAllVisionSources, useVisionSources } from '../vision/store.ts';
import { useVisionNodeChoices } from '../vision/nodeChoice.ts';
import {
  deviceBrokerHost, deviceDirectBase, resolveVisionBinding, useVisionBindingChoices, type VisionBinding,
} from '../vision/binding.ts';
import { useIsDrone } from './DroneDetailModal.tsx';
import { DroneDashMini } from '../dronedash/DroneDash.tsx';
import { GroundDash } from '../physical/GroundDash.tsx';
import { useTick } from '../sar/useTick.ts';
import { clampStart, SLOTS } from './slideWindow.ts';

const TABS = ['cams', 'status'] as const;
type Tab = (typeof TABS)[number];

/** 카드의 작은 글씨와 같은 갈래 — 이 판에서도 장비가 어느 길로 붙었는지 적는다. */
function originKey(entityId: string): string {
  const source = connectedDevice(entityId)?.source;
  return source === 'camera' ? 'ms.fixedCameraDevice' : source === 'twin' ? 'ms.twinDevice' : source === 'server' ? 'ms.serverDevice' : 'ms.connectedDevice';
}

/** 2×2 그리드 + 한 칸씩 미는 슬라이더. 화면 밖 칸은 그리지 않는다. */
function SlideGrid<T>({ items, keyOf, render, className }: {
  items: readonly T[];
  keyOf(item: T): string;
  render(item: T): ReactNode;
  className: string;
}) {
  useLang();
  const [rawStart, setStart] = useState(0);
  const start = clampStart(rawStart, items.length);
  const max = Math.max(0, items.length - SLOTS);
  const shown = items.slice(start, start + SLOTS);
  const move = (next: number) => setStart(clampStart(next, items.length));
  return <>
    <div className={`adev-grid ${className}`}
      onWheel={(event) => {
        // 가로 휠(터치패드 좌우)만 민다 — 세로 휠은 칸 안 스크롤(상태판)에 양보한다.
        if (max === 0 || Math.abs(event.deltaX) <= Math.abs(event.deltaY) || Math.abs(event.deltaX) < 20) return;
        move(start + (event.deltaX > 0 ? 1 : -1));
      }}>
      {shown.map((item) => <article key={keyOf(item)} className="adev-tile">{render(item)}</article>)}
    </div>
    {max > 0 && <div className="adev-slider">
      <button type="button" onClick={() => move(start - 1)} disabled={start === 0} aria-label={t('adev.prev')}>◀</button>
      <input type="range" min={0} max={max} step={1} value={start} aria-label={t('adev.slider')}
        onChange={(event) => move(Number(event.target.value))} />
      <button type="button" onClick={() => move(start + 1)} disabled={start === max} aria-label={t('adev.next')}>▶</button>
      <span>{t('adev.range', { from: start + 1, to: start + shown.length, n: items.length })}</span>
    </div>}
  </>;
}

/** 칸 머리 — **장비 구분이 먼저다.** 장비 id 를 크게, 그 영상(또는 붙은 길)을 옆에. */
function TileHead({ id, sub }: { id: string; sub: string }) {
  useLang();
  return <header className="adev-tile__head"><b>{id}</b><small>{sub}</small></header>;
}

// ── 카메라 탭 ─────────────────────────────────────────────────────────────────

type Stream =
  | { key: string; deviceId: string; kind: 'twin' }
  | { key: string; deviceId: string; kind: 'fixed'; url: string; feed: FeedKind }
  | { key: string; deviceId: string; kind: 'direct'; source: LabeledCameraSource; position: CameraPosition }
  | { key: string; deviceId: string; kind: 'vision'; base: string; model: string | null };

function streamLabel(stream: Stream): string {
  switch (stream.kind) {
    case 'twin': return t('v3d.title');
    case 'fixed': return t('fcam.title');
    case 'direct': return stream.source.label !== null
      ? `${t('dso.robotCamera')} · ${stream.source.label}`
      : stream.source.kind === 'stream' ? `${t('dso.robotCamera')} · ${stream.position}` : t('dso.robotCamera');
    default: return `${t('vis.sectionTitle')} · ${stream.model ?? t('vis.raw')}`;
  }
}

function StreamTile({ stream }: { stream: Stream }) {
  useLang();
  const id = stream.deviceId;
  return <>
    <TileHead id={id} sub={streamLabel(stream)} />
    <div className={`adev-tile__body adev-tile__body--${stream.kind}`}>
      {stream.kind === 'twin' && <Virtual3D zoom recordPrefix={id} />}
      {/* 방식을 바꾸면 새로 붙는다 — 끝나지 않는 영상을 한 장씩 청하면 매번 처음부터 연다. */}
      {stream.kind === 'fixed' && <DirectCamera key={stream.feed} url={stream.url} frames={stream.feed === 'frames'} live compact recordLabel={id} />}
      {stream.kind === 'direct' && <DirectCamera url={stream.source.url} frames={stream.source.kind === 'frames'} live compact
        recordLabel={`${id}_${stream.source.label ?? stream.position}`} />}
      {stream.kind === 'vision' && <VisionStream entityId={id} base={stream.base} model={stream.model} />}
    </div>
  </>;
}

type CamDevice = { id: string; twin: boolean; fixedUrl: string | null; direct: LabeledCameraSource[]; binding: VisionBinding };

function CamerasTab({ ids }: { ids: readonly string[] }) {
  useLang();
  const sources = useVisionSources();
  const bindingChoices = useVisionBindingChoices();
  const nodeChoices = useVisionNodeChoices();
  const replaying = useReplayTarget();
  const [positions, setPositions] = useState<Record<string, CameraPosition>>({});
  const [feeds, setFeeds] = useState<Record<string, FeedKind>>({});
  const robotIds = ids.filter((id) => !isTwinDevice(id) && !isFixedCamera(id));
  // 그 장비에 없는 위치는 있는 위치로 (261112 — A2 는 front 하나)
  const effective = Object.fromEntries(robotIds.map((id) => [id, effectiveCameraPosition(id, positions[id] ?? 'front')]));
  const directs = useDirectCameraSourcesMany(robotIds, effective);
  const bases = visionBases();

  const devices: CamDevice[] = ids.map((id) => ({
    id,
    twin: isTwinDevice(id),
    fixedUrl: isFixedCamera(id) ? fixedCameraUrl(id) : null,
    direct: directs[id] ?? [],
    binding: resolveVisionBinding(bindingChoices[id] ?? null, deviceBrokerHost(id), sources, bases, deviceDirectBase(id)),
  }));

  // **영상 하나가 한 칸** — 장비 순서대로, 장비 안에서는 바로 받는 영상 → 추론(모델 → 원본) 순.
  const streams: Stream[] = [];
  for (const device of devices) {
    const { id } = device;
    if (device.twin) { streams.push({ key: `${id}|twin`, deviceId: id, kind: 'twin' }); continue; }
    if (device.fixedUrl !== null) {
      streams.push({ key: `${id}|fixed`, deviceId: id, kind: 'fixed', url: device.fixedUrl, feed: feeds[id] ?? feedKindOf(device.fixedUrl) });
    }
    const position = effective[id] ?? 'front';
    for (const source of device.direct) streams.push({ key: `${id}|direct|${source.url}`, deviceId: id, kind: 'direct', source, position });
    // 3D 가상환경은 객체 탐지를 붙이지 않는다(261007).
    const base = device.binding.base;
    if (base !== null) {
      for (const model of visionStreamCells(sources[base] ?? null, nodeChoices[`hw:${id}`] ?? {})) {
        streams.push({ key: `${id}|vision|${base}|${model ?? '__raw'}`, deviceId: id, kind: 'vision', base, model });
      }
    }
  }
  // 고를 것이 있는 장비 — 바로 받는 영상이 있거나 추론 포트가 묶였거나(여럿이라 고르지 않은 것 포함).
  const controllable = devices.filter((d) => d.twin || d.fixedUrl !== null || d.direct.length > 0 || d.binding.base !== null || d.binding.how === 'ambiguous');
  const without = devices.filter((d) => !controllable.includes(d)).map((d) => d.id);
  const withCamera = new Set(streams.map((s) => s.deviceId)).size;

  if (replaying !== null) return <div className="adev-body"><p className="vn-line vn-dim">{t('dcam.replay')}</p></div>;
  return <div className="adev-body">
    <p className="adev-count">{t('adev.camCount', { n: streams.length, d: withCamera, total: ids.length })}</p>
    {controllable.some((d) => !d.twin) && <details className="adev-settings">
      <summary>{t('adev.settings')}</summary>
      {controllable.filter((d) => !d.twin).map((d) => <div key={d.id} className="adev-settings__row">
        <b>{d.id}</b>
        {d.fixedUrl !== null && <label>{t('fcam.kind')}
          <select value={feeds[d.id] ?? feedKindOf(d.fixedUrl)} onChange={(event) => setFeeds({ ...feeds, [d.id]: event.target.value as FeedKind })}>
            <option value="stream">{t('fcam.kindStream')}</option>
            <option value="frames">{t('fcam.kindFrames')}</option>
          </select>
        </label>}
        {/* 카메라가 한 대인 길(드론 말단)은 위치를 안 가린다 — 상세와 같은 규칙. */}
        {d.direct.some((s) => s.kind === 'stream') && (directCameraPositions(d.id) ?? CAMERA_POSITIONS).length > 1 && <label>{t('dcam.position')}
          <select value={effective[d.id] ?? 'front'} onChange={(event) => setPositions({ ...positions, [d.id]: event.target.value as CameraPosition })}>
            {(directCameraPositions(d.id) ?? CAMERA_POSITIONS).map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>}
        <VisionDeviceControls entityId={d.id} />
      </div>)}
    </details>}
    {streams.length === 0
      ? <p className="hardware-panel__none">{ids.length === 0 ? t('ms.noConnectedDevice') : controllable.length > 0 ? t('adev.noStream') : t('acam.none')}</p>
      : <SlideGrid className="adev-grid--cams" items={streams} keyOf={(s) => s.key} render={(s) => <StreamTile stream={s} />} />}
    {without.length > 0 && <p className="adev-without">{t('acam.without', { list: without.join(', ') })}</p>}
  </div>;
}

// ── 장치 상태 탭 ─────────────────────────────────────────────────────────────

/** 고정 카메라 · 3D 가상환경 — 카드가 아는 것만 글로. 영상은 카메라 탭에 있다. */
function CameraDeviceText({ id }: { id: string }) {
  useLang();
  useTick(1000);
  const facts = useTwinFacts();
  const sources = useVisionSources();
  const bindingChoices = useVisionBindingChoices();
  const seen = connectedDevice(id);
  const last = seen === null ? t('fcam.notReceived') : t('hl.secondsAgo', { sec: Math.round((Date.now() - seen.lastSeenMs) / 1000) });
  const rows: Array<[string, string]> = [];
  if (isTwinDevice(id)) {
    rows.push([t('twin.factUrl'), facts?.url ?? '—']);
    rows.push([t('twin.factKind'), facts?.kind === 'topcam' ? t('twin.kindTopcam') : t('twin.kindPage')]);
  } else {
    const url = fixedCameraUrl(id);
    rows.push([t('fcam.factUrl'), url ?? t('fcam.gone', { id })]);
    if (url !== null) rows.push([t('fcam.kind'), feedKindOf(url) === 'frames' ? t('fcam.kindFrames') : t('fcam.kindStream')]);
    const binding = resolveVisionBinding(bindingChoices[id] ?? null, deviceBrokerHost(id), sources, visionBases(), deviceDirectBase(id));
    const state = binding.base === null ? null : sources[binding.base] ?? null;
    const live = (state?.health?.models ?? []).filter(modelLive).map((m) => m.model);
    rows.push([t('adev.visionPort'), binding.base === null
      ? binding.how === 'ambiguous' ? t('adev.visionAmbiguous', { n: binding.candidates.length }) : t('adev.visionNone')
      : t('adev.visionLine', { name: state?.health?.source ?? binding.base, models: live.length === 0 ? '—' : live.join(', ') })]);
  }
  rows.push([t('fcam.factLast'), last]);
  return <dl className="adev-facts">
    {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
  </dl>;
}

function StatusTile({ id }: { id: string }) {
  useLang();
  const drone = useIsDrone(id);
  const viewOnly = isTwinDevice(id) || isFixedCamera(id);
  return <>
    <TileHead id={id} sub={t(originKey(id))} />
    <div className="adev-tile__body adev-tile__body--status">
      {/* 드론은 상태판만(지시) — 축약판. 전체 상태판은 카드 상세에 있다. */}
      {isFixedCamera(id) && <CameraStateDash entityId={id} compact />}
      {viewOnly ? <CameraDeviceText id={id} /> : drone ? <DroneDashMini deviceId={id} /> : <GroundDash entityId={id} compact />}
    </div>
  </>;
}

function StatusTab({ ids }: { ids: readonly string[] }) {
  useLang();
  return <div className="adev-body">
    <p className="adev-count">{t('adev.statusCount', { n: ids.length })}</p>
    {ids.length === 0
      ? <p className="hardware-panel__none">{t('ms.noConnectedDevice')}</p>
      : <SlideGrid className="adev-grid--status" items={ids} keyOf={(id) => id} render={(id) => <StatusTile id={id} />} />}
  </div>;
}

// ── 판 ─────────────────────────────────────────────────────────────────────

export function AllDevicesOverlay({ onClose }: { onClose(): void }) {
  useLang();
  useConnections();
  useConnectedDevices();
  const ids = useDeviceCardIds();
  const [tab, setTab] = useState<Tab>('cams');
  // 장비마다 포트를 맞대 보려면 포트 전부의 `/health` 가 있어야 한다 — 하드웨어 카드와 같은 붙잡기다.
  useEffect(() => holdAllVisionSources(), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal all-devs" role="dialog" aria-label={t('acam.title')}>
      <header>
        <div>
          <h2>{t('acam.title')}</h2>
        </div>
        <nav className="drone-modal__tabs" role="tablist" aria-label={t('adev.tabs')}>
          {TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item}
            onClick={() => setTab(item)}>{t(`adev.tab.${item}`)}</button>)}
        </nav>
        <button type="button" onClick={onClose}>{t('dso.1')}</button>
      </header>
      {/* 안 보이는 탭은 그리지 않는다 — 카메라 탭을 떠나면 영상이 끊긴다. */}
      {tab === 'cams' ? <CamerasTab ids={ids} /> : <StatusTab ids={ids} />}
      <footer>
        <span>{t(tab === 'cams' ? 'acam.footer' : 'adev.footerStatus')}</span>
      </footer>
    </section>
  </div>;
}
